"""Exercise upstream metadata updates in temporary repository files without network access."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / '.github/scripts/check_upstream.py'
FILES = ('Dockerfile', 'README.md', 'DOCKERHUB.md', '.upstream.json')


class UpstreamTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='yadisk-upstream-tests-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        for name in FILES:
            (self.base / name).write_bytes((ROOT / name).read_bytes())
        self.tracked = json.loads((self.base / '.upstream.json').read_text())
        self.output = self.base / 'github-output'

    def index(self, version='0.1.6.9999', sha256='a' * 64, package='yandex-disk', architecture='amd64'):
        fields = {'Package': package, 'Version': version, 'Architecture': architecture, 'SHA256': sha256}
        return '\n'.join(name + ': ' + value for name, value in fields.items() if value is not None) + '\n\n'

    def snapshot(self):
        return {name: (self.base / name).read_bytes() if (self.base / name).exists() else None for name in FILES}

    def run_update(self, index):
        self.output.unlink(missing_ok=True)
        return subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=self.base,
            input=index,
            env=dict(os.environ, GITHUB_OUTPUT=str(self.output)),
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )

    def assert_rejected(self, index, message):
        before = self.snapshot()
        result = self.run_update(index)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(message, result.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.output.exists())

    def test_selects_exact_package_and_architecture_and_updates_versions_literally(self):
        old_version = self.tracked['version']
        sentinel = old_version.replace('.', 'x')
        for name in ('README.md', 'DOCKERHUB.md'):
            with (self.base / name).open('a') as document:
                document.write('\nPreserve: ' + sentinel + '\n')
        index = (
            self.index(package='other-package')
            + self.index(package='yandex-disk-extra')
            + self.index(architecture='i386')
            + self.index()
        )
        result = self.run_update(index)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads((self.base / '.upstream.json').read_text()),
            {'package': 'yandex-disk', 'version': '0.1.6.9999', 'sha256': 'a' * 64},
        )
        dockerfile = (self.base / 'Dockerfile').read_text()
        self.assertIn('ARG YADISK_VERSION=0.1.6.9999\n', dockerfile)
        self.assertIn('ARG YADISK_SHA256=' + 'a' * 64 + '\n', dockerfile)
        self.assertIn('${YADISK_VERSION}_amd64.deb', dockerfile)
        for name in ('README.md', 'DOCKERHUB.md'):
            contents = (self.base / name).read_text()
            self.assertNotIn(old_version, contents)
            self.assertIn('0.1.6.9999', contents)
            self.assertIn(sentinel, contents)
        self.assertEqual(
            dict(line.split('=', 1) for line in self.output.read_text().splitlines()),
            {'has_update': 'true', 'old_version': old_version, 'new_version': '0.1.6.9999', 'new_sha256': 'a' * 64},
        )

    def test_unchanged_version_and_hash_leave_repository_untouched(self):
        before = self.snapshot()
        result = self.run_update(self.index(self.tracked['version'], self.tracked['sha256'].upper()))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.output.read_text(), 'has_update=false\n')

    def test_changed_hash_without_version_change_is_rejected(self):
        self.assert_rejected(self.index(version=self.tracked['version']), 'SHA256 changed without a version change')

    def test_missing_or_ambiguous_package_is_rejected(self):
        for index in (
            '',
            self.index(package='other-package'),
            self.index(architecture='i386'),
            self.index() + self.index(version='0.1.6.9998'),
        ):
            with self.subTest(index=index):
                self.assert_rejected(index, 'Expected exactly one yandex-disk amd64 record')

    def test_missing_or_invalid_version_and_hash_are_rejected(self):
        for version in (None, '', 'not a version', '1.2/3'):
            with self.subTest(version=version):
                self.assert_rejected(self.index(version=version), 'invalid package version')
        for sha256 in (None, '', 'abcd', 'x' * 64):
            with self.subTest(sha256=sha256):
                self.assert_rejected(self.index(sha256=sha256), 'invalid package SHA256')

    def test_invalid_tracked_metadata_is_not_silently_replaced(self):
        for contents in ('not json', '[]', '{}', '{"package": "yandex-disk", "version": "1"}'):
            with self.subTest(contents=contents):
                (self.base / '.upstream.json').write_text(contents)
                self.assert_rejected(self.index(), '::error::')

    def test_invalid_dockerfile_assignments_are_rejected_before_any_changes(self):
        original = (ROOT / 'Dockerfile').read_text()
        for name, value in (('YADISK_VERSION', self.tracked['version']), ('YADISK_SHA256', self.tracked['sha256'])):
            assignment = f'ARG {name}={value}'
            for contents in (original.replace(assignment, f'ARG {name}'), original + '\n' + assignment + '\n'):
                with self.subTest(name=name, contents=contents):
                    (self.base / 'Dockerfile').write_text(contents)
                    self.assert_rejected(self.index(), f'Expected exactly one ARG {name}=')

    def test_missing_tracking_file_can_be_initialized(self):
        documents = {name: (self.base / name).read_bytes() for name in ('README.md', 'DOCKERHUB.md')}
        (self.base / '.upstream.json').unlink()
        result = self.run_update(self.index())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads((self.base / '.upstream.json').read_text()),
            {'package': 'yandex-disk', 'version': '0.1.6.9999', 'sha256': 'a' * 64},
        )
        dockerfile = (self.base / 'Dockerfile').read_text()
        self.assertIn('ARG YADISK_VERSION=0.1.6.9999\n', dockerfile)
        self.assertIn('ARG YADISK_SHA256=' + 'a' * 64 + '\n', dockerfile)
        self.assertEqual({name: (self.base / name).read_bytes() for name in documents}, documents)
        self.assertIn('old_version=\n', self.output.read_text())


if __name__ == '__main__':
    unittest.main()
