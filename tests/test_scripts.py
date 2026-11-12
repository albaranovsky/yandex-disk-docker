"""Run shell scripts against temporary storage and a fake Yandex.Disk client."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ScriptsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='yadisk-tests-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.config = self.base / 'custom storage/configuration'
        self.disk = self.base / 'custom storage/files'
        self.bin = self.base / 'bin'
        for path in (self.config, self.disk, self.bin):
            path.mkdir(parents=True)
        self.log = self.base / 'args.json'
        client = self.bin / 'yandex-disk'
        client.write_text('#!' + sys.executable + '\n'
                          'import json, os, pathlib, sys\n'
                          'pathlib.Path(os.environ["CLIENT_LOG"]).write_text(json.dumps(sys.argv[1:]))\n'
                          'sys.exit(int(os.environ.get("CLIENT_EXIT", "0")))\n')
        client.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'],
                        CONFIG_DIR=str(self.config), DATA_DIR=str(self.disk),
                        CLIENT_LOG=str(self.log), PUID='', PGID='', EXCLUDE='', PROXY='')

    def run_script(self, script, *args, **env):
        self.log.unlink(missing_ok=True)
        return subprocess.run(['bash', str(ROOT / script), *args],
                              env=dict(self.env, **env), stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=5)

    def authenticate(self):
        (self.config / 'passwd').write_text('dummy-token')

    def test_entrypoint_creates_storage_and_preserves_arguments_and_exit_code(self):
        self.config.rmdir()
        self.disk.rmdir()
        result = self.run_script('entrypoint.sh', 'yandex-disk', 'publish', 'a file', CLIENT_EXIT='7')
        self.assertEqual(result.returncode, 7)
        self.assertTrue(self.config.is_dir())
        self.assertTrue(self.disk.is_dir())
        self.assertEqual(json.loads(self.log.read_text()), ['publish', 'a file'])

    def test_legacy_identity_variables_require_migration(self):
        for name in ('PUID', 'PGID'):
            with self.subTest(name=name):
                result = self.run_script('entrypoint.sh', 'yandex-disk', **{name: '1001'})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('--user', result.stderr)
                self.assertFalse(self.log.exists())

    def test_entrypoint_reports_storage_creation_failure(self):
        self.config.rmdir()
        self.config.write_text('not a directory')
        result = self.run_script('entrypoint.sh', 'yandex-disk')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Prepare writable', result.stderr)
        self.assertFalse(self.log.exists())

    def test_help_does_not_invoke_client(self):
        result = self.run_script('yadisk', '--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Usage: yadisk', result.stdout)
        self.assertIn('default: ' + str(self.config / 'passwd'), result.stdout)
        self.assertFalse(self.log.exists())

    def test_start_requires_nonempty_token_and_exits_immediately(self):
        for empty_token in (False, True):
            with self.subTest(empty_token=empty_token):
                if empty_token:
                    (self.config / 'passwd').touch()
                result = self.run_script('yadisk', 'start')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Run make setup', result.stderr)
                self.assertFalse(self.log.exists())

    def test_start_help_does_not_require_token_or_storage(self):
        self.disk.rmdir()
        for token in (None, '', 'dummy-token'):
            if token is not None:
                (self.config / 'passwd').write_text(token)
            for flag in ('--help', '-h'):
                for args in ((flag,), ('--read-only', flag), (flag, '--read-only')):
                    with self.subTest(token=token, args=args):
                        result = self.run_script('yadisk', 'start', *args,
                                                 EXCLUDE='temp', PROXY='invalid-proxy')
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stderr, '')
                        self.assertEqual(json.loads(self.log.read_text()), ['--help'])

    def test_start_passes_foreground_options_and_preserves_files(self):
        self.authenticate()
        (self.config / 'config.cfg').write_text('ignored in foreground mode')
        sentinel = self.disk / '.yadisk_rw_test'
        sentinel.write_text('keep me')
        result = self.run_script('yadisk', 'start', '--read-only', '--overwrite',
                                 EXCLUDE='a,b', PROXY='https,proxy.local,8080', CLIENT_EXIT='7')
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(json.loads(self.log.read_text()), [
            '--proxy=https,proxy.local,8080', '--dir=' + str(self.disk),
            '--auth=' + str(self.config / 'passwd'), '--no-daemon',
            '--exclude-dirs=a,b', '--read-only', '--overwrite'])
        self.assertEqual(sentinel.read_text(), 'keep me')
        self.assertEqual(list(self.disk.iterdir()), [sentinel])

    def test_start_requires_storage_directories(self):
        self.authenticate()
        self.disk.rmdir()
        self.disk.write_text('not a directory')
        result = self.run_script('yadisk', 'start')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Storage is not accessible', result.stderr)
        self.assertFalse(self.log.exists())

    @unittest.skipIf(os.geteuid() == 0, 'Root bypasses Unix write permissions')
    def test_start_reports_unwritable_storage(self):
        self.authenticate()
        self.disk.chmod(0o555)
        try:
            result = self.run_script('yadisk', 'start')
        finally:
            self.disk.chmod(0o755)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Storage is not accessible', result.stderr)
        self.assertFalse(self.log.exists())

    def test_publish_preserves_paths_and_uses_saved_configuration(self):
        self.authenticate()
        (self.config / 'config.cfg').touch()
        result = self.run_script('yadisk', 'publish', 'Photos/a file.zip')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.log.read_text()), [
            '--config=' + str(self.config / 'config.cfg'), '--dir=' + str(self.disk),
            '--auth=' + str(self.config / 'passwd'), 'publish', 'Photos/a file.zip'])

    def test_token_has_explicit_default_path_and_accepts_custom_path(self):
        for supplied, expected in (([], str(self.config / 'passwd')), (['a token'], 'a token')):
            with self.subTest(supplied=supplied):
                result = self.run_script('yadisk', 'token', *supplied)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(self.log.read_text()), ['token', expected])

    def test_setup_is_explicit_and_propagates_failure(self):
        result = self.run_script('yadisk', 'setup', CLIENT_EXIT='7')
        self.assertEqual(result.returncode, 7)
        self.assertEqual(json.loads(self.log.read_text()), [
            '--config=' + str(self.config / 'config.cfg'), '--dir=' + str(self.disk),
            '--auth=' + str(self.config / 'passwd'), 'setup'])

    def test_unknown_command_is_forwarded(self):
        result = self.run_script('yadisk', '--version')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.log.read_text()), ['--version'])


if __name__ == '__main__':
    unittest.main()
