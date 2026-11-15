"""Opt-in local checks of the container with a dedicated Yandex.Disk account."""

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from pathlib import Path


def auth_dir_from_env(path):
    """Read only YADISK_AUTH_DIR; do not execute or expand .env contents."""
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        key, separator, value = line.partition('=')
        if separator and key.strip() == 'YADISK_AUTH_DIR':
            value = value.strip()
            if value.startswith(('"', "'")):
                if len(value) < 2 or value[-1] != value[0]:
                    raise ValueError('Unclosed quote for YADISK_AUTH_DIR in .env')
                value = value[1:-1]
            return str(path.parent / Path(value).expanduser()) if value else ''
    return None


class LiveSync:
    def __init__(self, image, auth, timeout, iid):
        self.image = image
        self.auth = auth
        self.iid = iid
        self.timeout = timeout
        self.prefix = 'yadisk-live-' + uuid.uuid4().hex
        self.folder = '/data/disk/' + self.prefix
        self.containers = []
        self.volumes = []
        self.complete = False
        self.host_storage = None

    def docker(self, *args, data=None, check=True):
        # Never include command output or stdin in errors: auth may be sensitive.
        result = subprocess.run(['docker', *args], input=data, check=False, capture_output=True, timeout=self.timeout)
        if check and result.returncode:
            raise RuntimeError('Docker operation failed: ' + args[0])
        return result

    def exec(self, peer, script, *args, data=None):
        return self.docker('exec', '-i', self.prefix + '-' + peer, 'bash', '-c', script, 'live-sync', *args, data=data)

    def state(self, peer):
        result = self.docker('inspect', self.prefix + '-' + peer)
        return json.loads(result.stdout)[0]['State']

    def client_status(self, peer):
        result = self.docker('exec', '-e', 'LC_ALL=C', self.prefix + '-' + peer, 'yadisk', 'status', check=False)
        if result.returncode:
            return f'status unavailable (exit {result.returncode})', False
        lines = result.stdout.decode(errors='replace').splitlines()
        quota_received = any(line.strip().startswith('Total:') for line in lines)
        for line in lines:
            if line.startswith('Synchronization core status:'):
                return line.partition(':')[2].strip(), quota_received
        return 'unknown status', False

    def ready(self, peer):
        # Exit zero also occurs while offline; transfer assertions check contents.
        state, quota_received = self.client_status(peer)
        return quota_received and state in ('idle', 'busy', 'index')

    def settled(self):
        return all(self.client_status(peer)[0] == 'idle' for peer in ('a', 'b'))

    def wait(self, description, condition):
        print(description, flush=True)
        deadline = time.monotonic() + self.timeout
        next_report = 0
        while time.monotonic() < deadline:
            for name in self.containers:
                peer = name.rsplit('-', 1)[1]
                if not self.state(peer)['Running']:
                    raise RuntimeError('Client stopped unexpectedly: ' + peer)
            if condition():
                return
            if time.monotonic() >= next_report:
                self.report_status()
                next_report = time.monotonic() + 15
            time.sleep(1)
        self.report_status()
        raise RuntimeError('Timed out: ' + description)

    def report_status(self):
        # Report only the core state, never filenames, account details or logs.
        for name in self.containers:
            peer = name.rsplit('-', 1)[1]
            print(f'  Client {peer.upper()}: {self.client_status(peer)[0]}', flush=True)

    def mounts(self, peer, include_host=True):
        name = self.prefix + '-' + peer
        if peer == 'b':
            return [('volume', name, '/data')]
        mounts = [('volume', name + '-config', '/data/config')]
        if self.host_storage is None:
            mounts.append(('volume', name + '-disk', '/data/disk'))
        elif include_host:
            mounts.append(('bind', str(self.host_storage), '/data/disk'))
        return mounts

    def mount_args(self, peer, include_host=True):
        return [
            arg
            for kind, source, target in self.mounts(peer, include_host)
            for arg in ('--mount', f'type={kind},src={source},dst={target}')
        ]

    def prepare(self, peer, user):
        for kind, source, _ in self.mounts(peer, include_host=False):
            if kind == 'volume':
                self.docker('volume', 'create', source)
                self.volumes.append(source)
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode='w') as archive:
            for name, contents in (('passwd', self.auth), ('iid', self.iid)):
                entry = tarfile.TarInfo(name)
                entry.size = len(contents)
                entry.mode = 0o600
                archive.addfile(entry, io.BytesIO(contents))
        # This helper prepares only disposable Docker volumes, never the host bind.
        self.docker(
            'run',
            '--rm',
            '-i',
            '--platform',
            'linux/amd64',
            '--user',
            '0:0',
            *self.mount_args(peer, include_host=False),
            '--entrypoint',
            'bash',
            self.image,
            '-c',
            'set -e; mkdir -p /data/config /data/disk; chmod 700 /data/config; '
            'tar -xf - -C /data/config; chown -R "$1" /data/config /data/disk',
            'live-sync',
            user,
            data=payload.getvalue(),
        )

    def start(self, peer, user):
        name = self.prefix + '-' + peer
        options = (
            ['--read-only', '--tmpfs', '/tmp', '--tmpfs', '/run'] if peer == 'a' and self.host_storage is None else []
        )
        self.containers.append(name)
        self.docker(
            'run',
            '-d',
            '--platform',
            'linux/amd64',
            '--name',
            name,
            '--user',
            user,
            '--env',
            'LC_ALL=C',
            *self.mount_args(peer),
            *options,
            self.image,
        )

    def matches(self, peer, filename, expected):
        return self.exec(peer, 'if [ -f "$1" ]; then cat -- "$1"; fi', self.folder + '/' + filename).stdout == expected

    def stop(self, peer):
        name = self.prefix + '-' + peer
        self.docker('stop', '--timeout', '30', name)
        state = self.state(peer)
        if state['OOMKilled'] or state['ExitCode'] not in (0, 143):
            raise RuntimeError('Client required a forced stop or failed: ' + peer)
        self.docker('rm', name)
        self.containers.remove(name)

    def check_smoke(self):
        uploaded = (uuid.uuid4().hex + '\n').encode()
        self.exec('a', 'mkdir -p -- "$1"; cat > "$1/upload.txt"', self.folder, data=uploaded)
        self.wait(
            'Checking upload through split storage and read-only rootfs',
            lambda: self.matches('b', 'upload.txt', uploaded),
        )
        self.stop('a')
        downloaded = (uuid.uuid4().hex + '\n').encode()
        self.exec('b', 'cat > "$1/download.txt"', self.folder, data=downloaded)
        self.start('a', '1000:1000')
        self.wait(
            'Checking download after container recreation with the original storage',
            lambda: self.ready('a') and self.matches('a', 'download.txt', downloaded),
        )

    def check_host_edits(self):
        folder = self.host_storage / self.prefix
        path = folder / 'from-host.txt'
        initial = (uuid.uuid4().hex + '\n').encode()
        path.write_bytes(initial)
        self.wait('Checking file created on host reaches B', lambda: self.matches('b', path.name, initial))
        # Keep the inode and size, then emulate an editor's atomic save.
        changed = (uuid.uuid4().hex + '\n').encode()
        with path.open('r+b') as file:
            file.write(changed)
        self.wait('Checking same-size host edit reaches B', lambda: self.matches('b', path.name, changed))
        replacement = (uuid.uuid4().hex + '\n').encode()
        temporary = folder / 'replacement.tmp'
        temporary.write_bytes(replacement)
        temporary.replace(path)
        self.wait('Checking atomic host replacement reaches B', lambda: self.matches('b', path.name, replacement))
        self.wait('Waiting before switching writer', self.settled)
        downloaded = (uuid.uuid4().hex + '\n').encode()
        self.exec('b', 'cat > "$1/from-host.txt"', self.folder, data=downloaded)
        self.wait(
            'Checking remote edit reaches host bind mount', lambda: path.is_file() and path.read_bytes() == downloaded
        )

    def run(self, scenario='smoke'):
        self.image = self.docker('image', 'inspect', '--format', '{{.Id}}', self.image).stdout.decode().strip()
        print('Image: ' + self.image, flush=True)
        version = self.docker(
            'run', '--rm', '--platform', 'linux/amd64', '--entrypoint', 'yandex-disk', self.image, '--version'
        )
        print('Client: ' + version.stdout.decode().strip(), flush=True)
        for filename in ('/etc/passwd', '/etc/group'):
            result = self.docker(
                'run', '--rm', '--platform', 'linux/amd64', '--entrypoint', 'cat', self.image, filename
            )
            if any(line.split(':')[2] == '23456' for line in result.stdout.decode().splitlines() if ':' in line):
                raise RuntimeError('Test UID/GID 23456 must be absent from the image')
        producer_user = '1000:1000'
        if scenario == 'host':
            self.host_storage = Path(tempfile.mkdtemp(prefix=self.prefix + '-'))
            # The native client may miss watches for new host-created folders on macOS.
            # This scenario checks file edits in a folder present at startup.
            (self.host_storage / self.prefix).mkdir()
            producer_user = f'{os.getuid()}:{os.getgid()}'
        print('Cloud folder: ' + self.prefix, flush=True)
        for peer, user in (('a', producer_user), ('b', '23456:23456')):
            self.prepare(peer, user)
            self.start(peer, user)
        self.wait('Waiting for authenticated clients', lambda: self.ready('a') and self.ready('b'))
        if scenario == 'host':
            self.check_host_edits()
        else:
            self.check_smoke()
        self.wait('Waiting before cleanup', self.settled)
        self.exec('b', 'rm -r -- "$1"', self.folder)
        self.wait(
            'Checking cloud deletion reaches A',
            lambda: self.exec('a', '[ -e "$1" ] || printf absent', self.folder).stdout == b'absent',
        )
        for peer in ('a', 'b'):
            self.stop(peer)
        self.complete = True
        print(f'Live {scenario} checks passed', flush=True)

    def cleanup(self):
        success = True
        for name in reversed(self.containers):
            try:
                self.docker('rm', '-f', name)
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                success = False
                print('Could not remove container: ' + name, file=sys.stderr)
        for volume in reversed(self.volumes):
            try:
                self.docker('volume', 'rm', volume)
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                success = False
                print('Could not remove volume: ' + volume, file=sys.stderr)
        if not self.complete:
            print('Cloud cleanup was not confirmed. Check only folder: ' + self.prefix, file=sys.stderr)
        if self.host_storage is not None:
            if success:
                try:
                    shutil.rmtree(self.host_storage)
                except OSError:
                    success = False
                    print('Could not remove host storage: ' + str(self.host_storage), file=sys.stderr)
            else:
                print('Host storage cleanup deferred: ' + str(self.host_storage), file=sys.stderr)
        return success


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='yandex-disk:latest')
    parser.add_argument('--scenario', choices=('smoke', 'host'), default='smoke')
    parser.add_argument(
        '--auth-dir', help='Directory containing passwd and iid (fallback: YADISK_AUTH_DIR in environment or root .env)'
    )
    parser.add_argument(
        '--timeout', type=int, default=300, help='Timeout in seconds per wait or Docker operation (default: 300)'
    )
    args = parser.parse_args()
    if args.auth_dir is None:
        args.auth_dir = os.environ.get('YADISK_AUTH_DIR')
    if args.auth_dir is None:
        try:
            args.auth_dir = auth_dir_from_env(Path(__file__).resolve().parents[1] / '.env')
        except (OSError, ValueError):
            parser.error('Cannot read YADISK_AUTH_DIR from .env; check file access and quotes')
    if not args.auth_dir or args.timeout < 35:
        parser.error('Provide --auth-dir or YADISK_AUTH_DIR and a timeout of at least 35 seconds')
    if os.environ.get('CI'):
        parser.error('This test is for explicit local use, not CI')
    try:
        auth_dir = Path(args.auth_dir).expanduser()
        auth = (auth_dir / 'passwd').read_bytes()
    except OSError:
        parser.error('Cannot read passwd in the authorization directory')
    if not auth:
        parser.error('Authorization file is empty')
    try:
        iid = (auth_dir / 'iid').read_bytes()
    except OSError:
        parser.error('Cannot read iid in the authorization directory; use passwd and iid from the same configuration')
    if not iid:
        parser.error('The iid file in the authorization directory is empty')
    test = LiveSync(args.image, auth, args.timeout, iid)
    result = 0
    try:
        test.run(args.scenario)
    except (RuntimeError, OSError, subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        print(
            'Live test failed: ' + (str(error) if isinstance(error, RuntimeError) else type(error).__name__),
            file=sys.stderr,
        )
        result = 1
    finally:
        if not test.cleanup():
            result = 1
    return result


if __name__ == '__main__':
    sys.exit(main())
