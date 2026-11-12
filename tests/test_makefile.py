"""Check Make targets against a fake Docker CLI without publishing files."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MakefileTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='yadisk-make-tests-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.log = self.base / 'args.json'
        docker = self.base / 'docker'
        docker.write_text('#!' + sys.executable + '\n'
                          'import json, os, pathlib, sys\n'
                          'pathlib.Path(os.environ["DOCKER_LOG"]).write_text(json.dumps(sys.argv[1:]))\n')
        docker.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.base) + ':' + os.environ['PATH'],
                        DOCKER_LOG=str(self.log))
        for name in ('FILE', 'MAKEFLAGS', 'MAKEOVERRIDES', 'MFLAGS'):
            self.env.pop(name, None)

    def run_make(self, target, file=None, source='argument'):
        self.log.unlink(missing_ok=True)
        args = ['make', '--no-print-directory', '-f', str(ROOT / 'Makefile'), target]
        env = dict(self.env)
        if file is not None:
            if source == 'argument':
                args.append('FILE=' + file)
            else:
                env['FILE'] = file
        return subprocess.run(args, cwd=self.base, env=env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=5)

    def test_publish_and_unpublish_preserve_literal_file_arguments(self):
        paths = ('Photos/a file.zip', 'Photos/a"b.zip', "Photos/a'b.zip",
                 'Photos/$HOME;*[a]\\b.zip', 'Photos/a\nb.zip',
                 'Photos/$(shell touch make-expanded).zip',
                 'Photos/`touch shell-expanded`.zip',
                 'Photos/$$(touch shell-expanded).zip')
        for target in ('publish', 'unpublish'):
            for source in ('argument', 'environment'):
                for path in paths:
                    with self.subTest(target=target, source=source, path=path):
                        result = self.run_make(target, path, source)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(json.loads(self.log.read_text()),
                                         ['compose', 'exec', 'yandex-disk', 'yadisk', target, path])
                        self.assertFalse((self.base / 'make-expanded').exists())
                        self.assertFalse((self.base / 'shell-expanded').exists())

    def test_publish_and_unpublish_require_a_file_before_invoking_docker(self):
        for target in ('publish', 'unpublish'):
            for file, source in ((None, 'argument'), ('', 'argument'), ('', 'environment')):
                with self.subTest(target=target, file=file, source=source):
                    result = self.run_make(target, file, source)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('Usage: make ' + target + ' FILE=<path>', result.stdout)
                    self.assertFalse(self.log.exists())


if __name__ == '__main__':
    unittest.main()
