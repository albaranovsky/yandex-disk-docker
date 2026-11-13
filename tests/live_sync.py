"""Opt-in local synchronization test using a dedicated Yandex.Disk account."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid


def auth_file_from_env(path):
    """Read only YADISK_AUTH_FILE; do not execute or expand .env contents."""
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        key, separator, value = line.partition('=')
        if separator and key.strip() == 'YADISK_AUTH_FILE':
            value = value.strip()
            if value.startswith(('"', "'")):
                if len(value) < 2 or value[-1] != value[0]:
                    raise ValueError('Unclosed quote for YADISK_AUTH_FILE in .env')
                value = value[1:-1]
            return str(path.parent / Path(value).expanduser()) if value else ''
    return None


class LiveSync:
    def __init__(self, image, auth, timeout):
        self.image = image
        self.auth = auth
        self.timeout = timeout
        self.prefix = 'yadisk-live-' + uuid.uuid4().hex
        self.folder = '/data/disk/' + self.prefix
        self.containers = []
        self.volumes = []
        self.complete = False

    def docker(self, *args, data=None, check=True):
        # Never include command output or stdin in exceptions: auth may be sensitive.
        result = subprocess.run(['docker', *args], input=data, capture_output=True,
                                timeout=self.timeout)
        if check and result.returncode:
            raise RuntimeError('Docker operation failed: ' + args[0])
        return result

    def exec(self, peer, script, *args, data=None):
        return self.docker('exec', '-i', self.prefix + '-' + peer,
                           'bash', '-c', script, 'live-sync', *args, data=data)

    def state(self, peer):
        result = self.docker('inspect', self.prefix + '-' + peer)
        return json.loads(result.stdout)[0]['State']

    def wait(self, description, condition):
        print(description, flush=True)
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            for name in self.containers:
                peer = name.rsplit('-', 1)[1]
                if not self.state(peer)['Running']:
                    raise RuntimeError('Client stopped unexpectedly: ' + peer)
            if condition():
                return
            time.sleep(1)
        raise RuntimeError('Timed out: ' + description)

    def start(self, peer, user):
        name = self.prefix + '-' + peer
        self.containers.append(name)
        self.docker('run', '-d', '--platform', 'linux/amd64', '--name', name,
                    '--user', user, '--mount', 'type=volume,src=' + name + ',dst=/data',
                    self.image)

    def prepare(self, peer, user):
        volume = self.prefix + '-' + peer
        self.docker('volume', 'create', volume)
        self.volumes.append(volume)
        # Root only prepares our new Docker volume; the client runs unprivileged.
        self.docker('run', '--rm', '-i', '--platform', 'linux/amd64',
                    '--user', '0:0', '--mount', 'type=volume,src=' + volume + ',dst=/data',
                    '--entrypoint', 'bash', self.image, '-c',
                    'set -e; mkdir -p /data/config /data/disk; '
                    'chmod 700 /data/config; umask 077; cat > /data/config/passwd; '
                    'chown -R "$1" /data', 'live-sync', user, data=self.auth)

    def ready(self, peer):
        result = self.docker('exec', self.prefix + '-' + peer, 'yadisk', 'status', check=False)
        return result.returncode == 0

    def matches(self, peer, filename, expected):
        result = self.exec(peer, 'if [ -f "$1" ]; then cat -- "$1"; fi',
                           self.folder + '/' + filename)
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
        version = self.docker('run', '--rm', '--platform', 'linux/amd64',
                              '--entrypoint', 'yandex-disk', self.image, '--version')
        print('Client: ' + version.stdout.decode().strip(), flush=True)
        unknown = '23456:23456'
        for filename, column in (('/etc/passwd', 2), ('/etc/group', 2)):
            result = self.docker('run', '--rm', '--platform', 'linux/amd64',
                                 '--entrypoint', 'cat', self.image, filename)
            if any(line.split(':')[column] == '23456'
                   for line in result.stdout.decode().splitlines() if ':' in line):
                raise RuntimeError('Test UID/GID 23456 must be absent from the image')
        print('Cloud folder: ' + self.prefix, flush=True)
        print('Preparing separate volumes for 1000:1000 and ' + unknown, flush=True)
        for peer, user in (('a', '1000:1000'), ('b', unknown)):
            self.prepare(peer, user)
            self.start(peer, user)
        self.wait('Waiting for both authenticated clients',
                  lambda: self.ready('a') and self.ready('b'))
        first = ('upload-' + uuid.uuid4().hex + '\n').encode()
        self.exec('a', 'mkdir -p -- "$1"; cat > "$1/from-a.txt"', self.folder, data=first)
        self.wait('Checking upload from A and download to B',
                  lambda: self.matches('b', 'from-a.txt', first))
        print('Stopping A and writing through B', flush=True)
        self.stop('a')
        second = ('restart-' + uuid.uuid4().hex + '\n').encode()
        self.exec('b', 'cat > "$1/from-b.txt"', self.folder, data=second)
        self.start('a', '1000:1000')
        self.wait('Checking synchronization after recreating A',
                  lambda: self.ready('a') and self.matches('a', 'from-b.txt', second))
        # Remove only this run's cloud folder, through the synchronizing client.
        self.exec('b', 'rm -r -- "$1"', self.folder)
        self.wait('Waiting for cloud deletion to reach A',
                  lambda: self.exec('a', '[ -e "$1" ] || printf absent',
                                    self.folder).stdout == b'absent')
        for peer in ('a', 'b'):
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
            print('Cloud cleanup was not confirmed. Check only folder: ' + self.prefix,
                  file=sys.stderr)
        return success


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='yandex-disk:latest')
    parser.add_argument('--auth-file',
                        help='Existing passwd file (fallback: YADISK_AUTH_FILE in environment or root .env)')
    parser.add_argument('--timeout', type=int, default=300,
                        help='Timeout in seconds per wait or Docker operation (default: 300)')
    args = parser.parse_args()
    if args.auth_file is None:
        args.auth_file = os.environ.get('YADISK_AUTH_FILE')
    if args.auth_file is None:
        try:
            args.auth_file = auth_file_from_env(Path(__file__).resolve().parents[1] / '.env')
        except (OSError, ValueError):
            parser.error('Cannot read YADISK_AUTH_FILE from .env; check file access and quotes')
    if not args.auth_file or args.timeout < 35:
        parser.error('Provide --auth-file or YADISK_AUTH_FILE and a timeout of at least 35 seconds')
    if os.environ.get('CI'):
        parser.error('This test is for explicit local use, not CI')
    try:
        auth = Path(args.auth_file).expanduser().read_bytes()
    except OSError:
        parser.error('Cannot read authorization file')
    if not auth:
        parser.error('Authorization file is empty')
    test = LiveSync(args.image, auth, args.timeout)
    result = 0
    try:
        test.run()
    except (RuntimeError, OSError, subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        print('Live test failed: ' + (str(error) if isinstance(error, RuntimeError)
                                     else type(error).__name__), file=sys.stderr)
        result = 1
    finally:
        if not test.cleanup():
            result = 1
    return result


if __name__ == '__main__':
    sys.exit(main())
