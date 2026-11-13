"""Offline checks for the opt-in live test's waits and resource lifecycle."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from live_sync import LiveSync, auth_file_from_env, main


class LiveSyncTest(unittest.TestCase):
    def setUp(self):
        self.test = LiveSync('image', b'secret', 35)

    def test_wait_retries_until_remote_content_arrives(self):
        self.test.containers = [self.test.prefix + '-a']
        with patch.object(self.test, 'state', return_value={'Running': True}), patch('live_sync.time.sleep') as sleep:
            attempts = iter((False, False, True))
            self.test.wait('download', lambda: next(attempts))
        self.assertEqual(sleep.call_count, 2)

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

    def test_forced_shutdown_is_not_reported_as_graceful(self):
        name = self.test.prefix + '-a'
        self.test.containers = [name]
        with patch.object(self.test, 'docker') as docker, patch.object(
            self.test, 'state', return_value={'OOMKilled': False, 'ExitCode': 137}
        ), self.assertRaisesRegex(RuntimeError, 'did not stop gracefully'):
            self.test.stop('a')
        docker.assert_called_once_with('stop', '--time', '30', name)
        self.assertEqual(self.test.containers, [name])

    def test_cleanup_attempts_remaining_resources_after_failure(self):
        self.test.containers = [self.test.prefix + '-a', self.test.prefix + '-b']
        self.test.volumes = [self.test.prefix + '-a', self.test.prefix + '-b']
        with patch.object(self.test, 'docker', side_effect=[RuntimeError('failed'), None, None, None]) as docker, patch(
            'sys.stderr'
        ):
            self.test.cleanup()
        self.assertEqual(docker.call_count, 4)

    def test_docker_failure_does_not_disclose_authorization(self):
        result = subprocess.CompletedProcess([], 1, stdout=b'secret', stderr=b'secret')
        with patch('live_sync.subprocess.run', return_value=result), self.assertRaises(RuntimeError) as error:
            self.test.docker('run', data=b'secret')
        self.assertNotIn('secret', str(error.exception))


class AuthFileTest(unittest.TestCase):
    def test_env_file_paths_and_literal_shell_expressions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / '.env'
            self.assertIsNone(auth_file_from_env(path))
            for value, expected in [
                ('"auth files/passwd"', 'auth files/passwd'),
                ("'$(touch should-not-exist)'", '$(touch should-not-exist)'),
                ('/absolute/passwd', '/absolute/passwd'),
            ]:
                with self.subTest(value=value):
                    path.write_text('# Comment\nOTHER=ignored\nYADISK_AUTH_FILE=' + value + '\n')
                    self.assertEqual(auth_file_from_env(path), str(path.parent / expected))

    def test_explicit_settings_skip_dotenv(self):
        for arguments, environment, expected in [
            (['--auth-file', '/cli/passwd'], {'YADISK_AUTH_FILE': '/env/passwd'}, '/cli/passwd'),
            ([], {'YADISK_AUTH_FILE': '/env/passwd'}, '/env/passwd'),
            ([], {}, '/dotenv/passwd'),
        ]:
            with self.subTest(arguments=arguments, environment=environment), patch(
                'sys.argv', ['live_sync.py', *arguments]
            ), patch.dict('os.environ', environment, clear=True), patch(
                'live_sync.auth_file_from_env', return_value='/dotenv/passwd'
            ) as dotenv, patch('live_sync.Path.read_bytes', autospec=True, return_value=b'token') as read, patch(
                'live_sync.LiveSync'
            ) as live:
                self.assertEqual(main(), 0)
                self.assertEqual(dotenv.call_count, int(not arguments and not environment))
                live.assert_called_once_with('yandex-disk:latest', b'token', 300)
                read.assert_called_once_with(Path(expected))


if __name__ == '__main__':
    unittest.main()
