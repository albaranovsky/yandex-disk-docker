"""Offline checks for the opt-in live test's waits and resource lifecycle."""

import io
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from live_sync import LiveSync, auth_dir_from_env, main


class LiveSyncTest(unittest.TestCase):
    def setUp(self):
        self.test = LiveSync('image', b'secret', 35, b'original-instance')
        status = patch.object(self.test, 'report_status')
        self.addCleanup(status.stop)
        status.start()

    def test_wait_retries_until_remote_content_arrives(self):
        self.test.containers = [self.test.prefix + '-a']
        attempts = []

        def ready():
            attempts.append(len(attempts) == 2)
            return attempts[-1]

        with patch.object(self.test, 'state', return_value={'Running': True}), patch('live_sync.time.sleep'):
            self.test.wait('download', ready)
        self.assertTrue(attempts[-1])
        self.test.report_status.assert_called_once_with()

    def test_wait_fails_if_client_exits(self):
        self.test.containers = [self.test.prefix + '-b']
        with patch.object(self.test, 'state', return_value={'Running': False}), self.assertRaisesRegex(
            RuntimeError, 'stopped unexpectedly: b'
        ):
            self.test.wait('download', lambda: True)

    def test_wait_has_deadline(self):
        with patch('live_sync.time.monotonic', side_effect=(0, 36)), self.assertRaisesRegex(
            RuntimeError, 'Timed out: download'
        ):
            self.test.wait('download', lambda: False)
        self.test.report_status.assert_called_once_with()

    def test_forced_shutdown_is_not_reported_as_graceful(self):
        name = self.test.prefix + '-a'
        self.test.containers = [name]
        with patch.object(self.test, 'docker') as docker, patch.object(
            self.test, 'state', return_value={'OOMKilled': False, 'ExitCode': 137}
        ), self.assertRaisesRegex(RuntimeError, 'forced stop'):
            self.test.stop('a')
        docker.assert_called_once_with('stop', '--timeout', '30', name)
        self.assertEqual(self.test.containers, [name])

    def test_cleanup_attempts_remaining_resources_after_failure(self):
        self.test.containers = [self.test.prefix + '-a', self.test.prefix + '-b']
        self.test.volumes = [self.test.prefix + '-a', self.test.prefix + '-b']
        with patch.object(self.test, 'docker', side_effect=[RuntimeError('failed'), None, None, None]) as docker, patch(
            'sys.stderr'
        ):
            self.assertFalse(self.test.cleanup())
        a, b = self.test.prefix + '-a', self.test.prefix + '-b'
        self.assertEqual(
            docker.call_args_list,
            [call('rm', '-f', b), call('rm', '-f', a), call('volume', 'rm', b), call('volume', 'rm', a)],
        )

    def test_readiness_requires_known_active_state_and_quota(self):
        for code, state, quota, expected in (
            (0, 'idle', True, True),
            (0, 'busy', True, True),
            (0, 'index', True, True),
            (0, 'no internet access', True, False),
            (0, 'paused', True, False),
            (0, 'idle', False, False),
            (0, 'index', False, False),
            (1, 'idle', True, False),
            (0, None, True, False),
        ):
            with self.subTest(code=code, state=state, quota=quota):
                text = f'Synchronization core status: {state}\n' if state else ''
                text += 'Total: 5 GB\n' if quota else ''
                result = subprocess.CompletedProcess([], code, stdout=text.encode())
                with patch.object(self.test, 'docker', return_value=result):
                    self.assertEqual(self.test.ready('a'), expected)

    def test_docker_failure_does_not_disclose_authorization(self):
        result = subprocess.CompletedProcess([], 1, stdout=b'secret', stderr=b'secret')
        with patch('live_sync.subprocess.run', return_value=result), self.assertRaises(RuntimeError) as error:
            self.test.docker('run', data=b'secret')
        self.assertNotIn('secret', str(error.exception))

    def test_prepared_configuration_preserves_authorization_pair_and_permissions(self):
        with patch.object(self.test, 'docker') as docker:
            self.test.prepare('a', '1000:1000')
        payload = docker.call_args.kwargs['data']
        with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
            self.assertEqual(archive.getnames(), ['passwd', 'iid'])
            for name, expected in (('passwd', b'secret'), ('iid', b'original-instance')):
                self.assertEqual(archive.extractfile(name).read(), expected)
                self.assertEqual(archive.getmember(name).mode, 0o600)

    def test_host_storage_is_preserved_if_container_cleanup_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            self.test.host_storage = Path(directory) / 'host-data'
            self.test.host_storage.mkdir()
            self.test.containers = [self.test.prefix + '-host']
            with patch.object(self.test, 'docker', side_effect=RuntimeError('failed')), patch('sys.stderr'):
                self.assertFalse(self.test.cleanup())
            self.assertTrue(self.test.host_storage.is_dir())


class AuthDirTest(unittest.TestCase):
    def test_env_file_paths_and_literal_shell_expressions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / '.env'
            self.assertIsNone(auth_dir_from_env(path))
            for value, expected in [
                ('"auth files/config"', 'auth files/config'),
                ("'$(touch should-not-exist)'", '$(touch should-not-exist)'),
                ('/absolute/config', '/absolute/config'),
            ]:
                with self.subTest(value=value):
                    path.write_text('# Comment\nOTHER=ignored\nYADISK_AUTH_DIR=' + value + '\n')
                    self.assertEqual(auth_dir_from_env(path), str(path.parent / expected))

    def test_explicit_settings_skip_dotenv(self):
        for arguments, environment, expected in [
            (['--auth-dir', '/cli/config', '--scenario', 'host'], {'YADISK_AUTH_DIR': '/env/config'}, '/cli/config'),
            ([], {'YADISK_AUTH_DIR': '/env/config'}, '/env/config'),
            ([], {}, '/dotenv/config'),
        ]:
            with self.subTest(arguments=arguments, environment=environment), patch(
                'sys.argv', ['live_sync.py', *arguments]
            ), patch.dict('os.environ', environment, clear=True), patch(
                'live_sync.auth_dir_from_env', return_value='/dotenv/config'
            ) as dotenv, patch('live_sync.Path.read_bytes', autospec=True, return_value=b'token') as read, patch(
                'live_sync.LiveSync'
            ) as live:
                self.assertEqual(main(), 0)
                self.assertEqual(dotenv.call_count, int(not arguments and not environment))
                live.assert_called_once_with('yandex-disk:latest', b'token', 300, b'token')
                live.return_value.run.assert_called_once_with('host' if '--scenario' in arguments else 'smoke')
                self.assertEqual(
                    [call.args[0] for call in read.call_args_list], [Path(expected) / 'passwd', Path(expected) / 'iid']
                )

    def test_missing_iid_fails_before_starting_docker(self):
        with patch('sys.argv', ['live_sync.py', '--auth-dir', '/auth/config']), patch.dict(
            'os.environ', {}, clear=True
        ), patch('live_sync.Path.read_bytes', side_effect=[b'token', FileNotFoundError]), patch(
            'live_sync.LiveSync'
        ) as live, patch('sys.stderr'), self.assertRaises(SystemExit) as error:
            main()
        self.assertEqual(error.exception.code, 2)
        live.assert_not_called()


if __name__ == '__main__':
    unittest.main()
