"""Offline checks for the opt-in live test's waits and resource lifecycle."""

import io
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from live_sync import LiveSync, auth_dir_from_env, main


class LiveSyncTest(unittest.TestCase):
    def setUp(self):
        self.test = LiveSync('image', b'secret', 35, b'original-instance')
        status = patch.object(self.test, 'report_status')
        self.addCleanup(status.stop)
        status.start()

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
        self.test.report_status.assert_called_once_with()

    def test_wait_reports_client_state_while_waiting(self):
        with patch('live_sync.time.monotonic', side_effect=(0, 1, 1, 1, 2)), patch('live_sync.time.sleep'):
            attempts = iter((False, True))
            self.test.wait('download', lambda: next(attempts))
        self.test.report_status.assert_called_once_with()

    def test_successful_status_exit_does_not_mean_client_is_ready(self):
        for state in ('no internet access', 'busy', 'paused', 'error', 'idle'):
            with self.subTest(state=state):
                output = ('Synchronization core status: ' + state + '\nTotal: 5 GB\n').encode()
                result = subprocess.CompletedProcess([], 0, stdout=output, stderr=b'')
                with patch.object(self.test, 'docker', return_value=result):
                    self.assertEqual(self.test.ready('a'), state in ('idle', 'busy'))

    def test_unavailable_or_unrecognized_status_is_not_ready(self):
        for code, output in ((1, b'error'), (0, b''), (0, b'Synchronization core status: index\n')):
            with self.subTest(code=code, output=output):
                result = subprocess.CompletedProcess([], code, stdout=output, stderr=b'')
                with patch.object(self.test, 'docker', return_value=result):
                    self.assertFalse(self.test.ready('a'))

    def test_indexing_with_received_quota_can_proceed_to_file_checks(self):
        output = b'Synchronization core status: index\nTotal: 5 GB\n'
        result = subprocess.CompletedProcess([], 0, stdout=output, stderr=b'')
        with patch.object(self.test, 'docker', return_value=result):
            self.assertTrue(self.test.ready('b'))

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

    def test_prepared_configuration_preserves_authorization_pair_and_permissions(self):
        with patch.object(self.test, 'docker') as docker:
            self.test.prepare('a', '1000:1000')
        payload = docker.call_args.kwargs['data']
        with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
            self.assertEqual(archive.getnames(), ['passwd', 'iid'])
            for name, expected in (('passwd', b'secret'), ('iid', b'original-instance')):
                self.assertEqual(archive.extractfile(name).read(), expected)
                self.assertEqual(archive.getmember(name).mode, 0o600)


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
            (['--auth-dir', '/cli/config'], {'YADISK_AUTH_DIR': '/env/config'}, '/cli/config'),
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
