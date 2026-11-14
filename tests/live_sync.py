"""Opt-in local synchronization test using a dedicated Yandex.Disk account."""

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
        self.excluded_name = 'excluded-' + self.prefix
        self.folder = '/data/disk/' + self.prefix
        self.containers = []
        self.volumes = []
        self.complete = False
        self.host_storage = None

    def docker(self, *args, data=None, check=True):
        # Never include command output or stdin in exceptions: auth may be sensitive.
        result = subprocess.run(['docker', *args], input=data, check=False, capture_output=True, timeout=self.timeout)
        if check and result.returncode:
            raise RuntimeError('Docker operation failed: ' + args[0])
        return result

    def exec(self, peer, script, *args, data=None):
        return self.docker('exec', '-i', self.prefix + '-' + peer, 'bash', '-c', script, 'live-sync', *args, data=data)

    def state(self, peer):
        result = self.docker('inspect', self.prefix + '-' + peer)
        return json.loads(result.stdout)[0]['State']

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
            print(f'  Client {peer.upper()}: {self.core_status(peer)}', flush=True)

    def storage_paths(self, peer):
        if peer == 'custom':
            return '/storage/custom config', '/storage/custom disk'
        return '/data/config', '/data/disk'

    def storage_mounts(self, peer):
        name = self.prefix + '-' + peer
        if peer == 'custom':
            config, disk = self.storage_paths(peer)
            return [
                '--mount',
                f'type=volume,src={name}-config,dst={config}',
                '--mount',
                f'type=volume,src={name}-disk,dst={disk}',
                # Native client metadata still uses the fixed HOME config link.
                '--mount',
                f'type=volume,src={name}-config,dst=/data/config',
            ]
        return ['--mount', 'type=volume,src=' + name + ',dst=/data']

    def peer_folder(self, peer):
        return self.storage_paths(peer)[1] + '/' + self.prefix

    def start(self, peer, user):
        name = self.prefix + '-' + peer
        self.containers.append(name)
        mounts = []
        if peer == 'host':
            mounts = ['--mount', 'type=bind,src=' + str(self.host_storage) + ',dst=/data/disk']
        options = []
        if peer in ('a', 'custom'):
            options.extend(['--read-only', '--tmpfs', '/tmp', '--tmpfs', '/run'])
        if peer == 'a':
            options.extend(['--env', 'EXCLUDE=' + self.excluded_name])
        if peer == 'custom':
            config, disk = self.storage_paths(peer)
            options.extend(
                [
                    '--env',
                    'CONFIG_DIR=' + config,
                    '--env',
                    'DATA_DIR=' + disk,
                ]
            )
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
            *self.storage_mounts(peer),
            *mounts,
            *options,
            self.image,
        )

    def check_exclusion(self):
        self.prepare('b', '23456:23456')
        self.start('b', '23456:23456')
        self.wait('Waiting for cloud seed source', lambda: self.ready('b'))
        self.wait('Waiting for source initial indexing', lambda: self.settled('b'))
        self.exec(
            'b',
            'mkdir -p -- "$1"; cat > "$1/skip.txt"',
            self.storage_paths('b')[1] + '/' + self.excluded_name,
            data=b'This cloud file must not download to A\n',
        )
        control = (uuid.uuid4().hex + '\n').encode()
        self.exec('b', 'mkdir -p -- "$1"; cat > "$1/from-a.txt"', self.folder, data=control)
        self.sync_and_wait('b', self.prefix + '/from-a.txt', self.excluded_name + '/skip.txt')
        self.stop('b')
        self.prepare('a', '1000:1000')
        self.start('a', '1000:1000')
        self.wait('Checking allowed download while EXCLUDE is active', lambda: self.matches('a', 'from-a.txt', control))
        self.wait('Waiting for exclusion target to finish indexing', lambda: self.settled('a'))
        if not self.excluded_file_absent('a'):
            raise RuntimeError('EXCLUDE failed: excluded cloud file was downloaded')
        self.start('b', '23456:23456')
        self.wait('Waiting for observer before edit checks', lambda: self.ready('b'))

    def check_custom_storage(self):
        print('Checking read-only rootfs and split custom storage paths', flush=True)
        # Both clients use one saved identity; switch between different local
        # layouts only after stopping the previous client.
        self.stop('b')
        self.prepare('custom', '1000:1000')
        self.start('custom', '1000:1000')
        self.wait('Waiting for custom-storage client to connect', lambda: self.ready('custom'))
        self.wait('Waiting for custom initial indexing before writes', lambda: self.settled('custom'))
        folder = self.peer_folder('custom')
        control = (uuid.uuid4().hex + '\n').encode()
        self.exec('custom', 'mkdir -p -- "$1"; cat > "$1/custom-paths.txt"', folder, data=control)
        self.sync_and_wait('custom', self.prefix + '/custom-paths.txt')
        self.stop('custom')
        self.prepare('b', '23456:23456')
        self.start('b', '23456:23456')
        self.wait('Checking upload from custom storage', lambda: self.matches('b', 'custom-paths.txt', control))
        self.wait('Waiting for observer to finish processing', lambda: self.settled('b'))
        reply = (uuid.uuid4().hex + '\n').encode()
        self.exec('b', 'cat > "$1/custom-reply.txt"', self.folder, data=reply)
        self.sync_and_wait('b', self.prefix + '/custom-reply.txt')
        self.stop('b')
        self.prepare('custom', '1000:1000')
        self.start('custom', '1000:1000')
        self.wait('Checking download to custom storage', lambda: self.matches('custom', 'custom-reply.txt', reply))
        self.wait('Waiting for custom storage processing to finish', lambda: self.settled('custom'))
        self.stop('custom')
        self.prepare('b', '23456:23456')
        self.start('b', '23456:23456')
        self.wait('Waiting for observer before host checks', lambda: self.ready('b'))

    def check_host_edits(self):
        self.host_storage = Path(tempfile.mkdtemp(prefix=self.prefix + '-'))
        host_user = f'{os.getuid()}:{os.getgid()}'
        print(f'Checking host bind mount edits as {host_user}', flush=True)
        self.prepare('host', host_user)
        self.start('host', host_user)
        self.wait('Waiting for host-mounted client to connect', lambda: self.ready('host'))
        folder = self.host_storage / self.prefix
        folder.mkdir(exist_ok=True)
        path = folder / 'from-host.txt'
        initial = (uuid.uuid4().hex + '\n').encode()
        path.write_bytes(initial)
        self.wait('Checking file created on host reaches B', lambda: self.matches('b', path.name, initial))

        # Keep the inode and size: detect edits, not just file creation or growth.
        changed = (uuid.uuid4().hex + '\n').encode()
        with path.open('r+b') as file:
            file.write(changed)
        self.wait('Checking same-size host edit reaches B', lambda: self.matches('b', path.name, changed))

        replacement = (uuid.uuid4().hex + '\n').encode()
        temporary = folder / 'replacement.tmp'
        temporary.write_bytes(replacement)
        temporary.replace(path)
        self.wait('Checking atomic host replacement reaches B', lambda: self.matches('b', path.name, replacement))
        self.wait('Waiting for host upload to finish before remote edit', lambda: self.settled('host', 'b'))

        downloaded = (uuid.uuid4().hex + '\n').encode()
        self.exec('b', 'cat > "$1/from-host.txt"', self.folder, data=downloaded)
        self.wait(
            'Checking remote edit reaches host bind mount', lambda: path.is_file() and path.read_bytes() == downloaded
        )
        self.wait('Waiting for remote edit processing to finish', lambda: self.settled('host', 'b'))

    def prepare(self, peer, user):
        volume = self.prefix + '-' + peer
        for suffix in ('-config', '-disk') if peer == 'custom' else ('',):
            # A fresh observer must rescan the cloud, not reuse another layout's
            # cached synchronization state for the copied client identity.
            if volume + suffix in self.volumes:
                self.docker('volume', 'rm', volume + suffix)
                self.volumes.remove(volume + suffix)
            self.docker('volume', 'create', volume + suffix)
            self.volumes.append(volume + suffix)
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode='w') as archive:
            for name, contents in (('passwd', self.auth), ('iid', self.iid)):
                entry = tarfile.TarInfo(name)
                entry.size = len(contents)
                entry.mode = 0o600
                archive.addfile(entry, io.BytesIO(contents))
        # Root only prepares our new Docker volume; the client runs unprivileged.
        self.docker(
            'run',
            '--rm',
            '-i',
            '--platform',
            'linux/amd64',
            '--user',
            '0:0',
            *self.storage_mounts(peer),
            '--entrypoint',
            'bash',
            self.image,
            '-c',
            'set -e; mkdir -p "$2" "$3"; chmod 700 "$2"; tar -xf - -C "$2"; '
            'if [ -n "$4" ]; then mkdir -p "$3/$4"; fi; chown -R "$1" "$2" "$3"',
            'live-sync',
            user,
            *self.storage_paths(peer),
            self.excluded_name if peer == 'a' else '',
            data=payload.getvalue(),
        )

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

    def core_status(self, peer):
        return self.client_status(peer)[0]

    def settled(self, *peers):
        return all(self.core_status(peer) == 'idle' for peer in peers)

    def sync_and_wait(self, peer, *new_paths):
        self.docker('exec', self.prefix + '-' + peer, 'yadisk', 'sync')
        if new_paths:
            # These paths are new on this producer. Idle or sync exit zero can
            # precede event processing; require a positive completion record.
            def recorded():
                result = self.docker('exec', self.prefix + '-' + peer, 'yadisk', 'status', check=False)
                text = result.stdout.decode(errors='replace')
                return result.returncode == 0 and all(path in text for path in new_paths)

            self.wait(f'Waiting for {peer} to record the new files as synchronized', recorded)
        self.wait(f'Waiting for {peer} to finish synchronization before shutdown', lambda: self.settled(peer))

    def check_no_conflicts(self, peer):
        result = self.exec(peer, 'find "$1" -mindepth 1 -maxdepth 1 -printf "%f\\n"', self.peer_folder(peer))
        expected = {'from-a.txt', 'from-b.txt', 'from-host.txt', 'custom-paths.txt', 'custom-reply.txt'}
        if set(result.stdout.decode().splitlines()) != expected:
            raise RuntimeError(f'Unexpected files in test folder on {peer} (possible synchronization conflict)')

    def excluded_file_absent(self, peer):
        path = self.storage_paths(peer)[1] + '/' + self.excluded_name + '/skip.txt'
        return self.exec(peer, '[ -e "$1" ] || printf absent', path).stdout == b'absent'

    def ready(self, peer):
        # Exit zero also occurs while offline. Indexing need not finish before
        # testing our files, but the client must have received the account quota.
        state, quota_received = self.client_status(peer)
        return quota_received and state in ('idle', 'busy', 'index')

    def matches(self, peer, filename, expected):
        result = self.exec(peer, 'if [ -f "$1" ]; then cat -- "$1"; fi', self.peer_folder(peer) + '/' + filename)
        return result.stdout == expected

    def stop(self, peer):
        name = self.prefix + '-' + peer
        self.docker('stop', '--time', '30', name)
        state = self.state(peer)
        if state['OOMKilled'] or state['ExitCode'] not in (0, 143):
            raise RuntimeError('Client did not stop gracefully: ' + peer)
        self.docker('rm', name)
        self.containers.remove(name)

    def run(self):
        image_id = self.docker('image', 'inspect', '--format', '{{.Id}}', self.image).stdout
        self.image = image_id.decode().strip()
        print('Image: ' + self.image, flush=True)
        version = self.docker(
            'run', '--rm', '--platform', 'linux/amd64', '--entrypoint', 'yandex-disk', self.image, '--version'
        )
        print('Client: ' + version.stdout.decode().strip(), flush=True)
        unknown = '23456:23456'
        for filename, column in (('/etc/passwd', 2), ('/etc/group', 2)):
            result = self.docker(
                'run', '--rm', '--platform', 'linux/amd64', '--entrypoint', 'cat', self.image, filename
            )
            if any(line.split(':')[column] == '23456' for line in result.stdout.decode().splitlines() if ':' in line):
                raise RuntimeError('Test UID/GID 23456 must be absent from the image')
        print('Cloud folder: ' + self.prefix, flush=True)
        print('Cloud exclusion folder: ' + self.excluded_name, flush=True)
        print('Preparing read-only rootfs client 1000:1000 and observer ' + unknown, flush=True)
        self.check_exclusion()
        for sender, receiver in (('a', 'b'), ('b', 'a')):
            changed = ('changed-' + uuid.uuid4().hex + '\n').encode()
            self.exec(sender, 'cat > "$1/from-a.txt"', self.folder, data=changed)
            self.wait(
                f'Checking existing file edit from {sender.upper()} reaches {receiver.upper()}',
                lambda receiver=receiver, changed=changed: self.matches(receiver, 'from-a.txt', changed),
            )
            self.wait('Waiting for file processing before switching writer', lambda: self.settled('a', 'b'))
        print('Stopping A and writing through B', flush=True)
        self.stop('a')
        second = ('restart-' + uuid.uuid4().hex + '\n').encode()
        self.exec('b', 'cat > "$1/from-b.txt"', self.folder, data=second)
        self.start('a', '1000:1000')
        self.wait(
            'Checking synchronization after recreating A',
            lambda: self.ready('a') and self.matches('a', 'from-b.txt', second),
        )
        self.stop('a')
        self.check_custom_storage()
        self.check_host_edits()
        for peer in ('host', 'b'):
            self.check_no_conflicts(peer)
            if self.excluded_file_absent(peer):
                raise RuntimeError(
                    f'EXCLUDE control invalid: unfiltered client {peer} did not receive the cloud marker'
                )
        # Remove only this run's cloud folder, through the synchronizing client.
        self.exec('b', 'rm -rf -- "$1" "$2"', self.folder, self.storage_paths('b')[1] + '/' + self.excluded_name)
        self.wait(
            'Waiting for cloud deletion to reach host bind mount',
            lambda: (
                not (self.host_storage / self.prefix).exists() and not (self.host_storage / self.excluded_name).exists()
            ),
        )
        for peer in ('host', 'b'):
            self.stop(peer)
        self.complete = True
        print('Live synchronization checks passed', flush=True)

    def cleanup(self):
        success = True
        for name in reversed(self.containers):
            try:
                self.docker('rm', '-f', name)
            except (RuntimeError, subprocess.TimeoutExpired):
                success = False
                print('Could not remove container: ' + name, file=sys.stderr)
        for volume in reversed(self.volumes):
            try:
                self.docker('volume', 'rm', volume)
            except (RuntimeError, subprocess.TimeoutExpired):
                success = False
                print('Could not remove volume: ' + volume, file=sys.stderr)
        if not self.complete:
            print('Cloud cleanup was not confirmed. Check only folder: ' + self.prefix, file=sys.stderr)
            print('Also check for an unexpectedly uploaded folder: ' + self.excluded_name, file=sys.stderr)
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
        test.run()
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
