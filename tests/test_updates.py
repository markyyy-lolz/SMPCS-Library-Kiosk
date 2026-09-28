import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from shared import updates

class ReleaseTests(unittest.TestCase):
    def release(self, tag, **extra):
        data = {'tag_name': tag, **extra}
        def opener(req, timeout):
            self.assertEqual(req.full_url, 'https://api.github.com/repos/school/library/releases/latest')
            self.assertEqual(timeout, 12)
            return io.BytesIO(json.dumps(data).encode())
        return updates.fetch_release('school/library', opener)

    def test_newer_equal_older(self):
        self.assertTrue(self.release('v1.10.0')['newer'])
        self.assertFalse(self.release('v1.1.0')['newer'])
        self.assertFalse(self.release('v1.0.9')['newer'])
        self.assertTrue(self.release('v2.0.0')['newer'])

    def test_installed_version_is_not_an_update(self):
        self.assertFalse(self.release('v' + updates.VERSION)['newer'])

    def test_tags_and_drafts(self):
        for tag in ('latest', 'v1.2.0-beta', '2026'):
            with self.assertRaises(ValueError): self.release(tag)
        with self.assertRaises(ValueError): self.release('v2.0.0', draft=True)
        with self.assertRaises(ValueError): self.release('v2.0.0', prerelease=True)

    def test_repo_validation(self):
        self.assertEqual(updates.normalize_repo(' https://github.com/school/library.git/ '), 'school/library')
        for bad in ('https://evil.test/school/library', 'school/library/releases', '../repo', 'school/repo?x=1'):
            with self.assertRaises(ValueError): updates.normalize_repo(bad)

    def test_errors(self):
        for code, expected in ((404, 'No public'), (403, 'limited'), (429, 'limited'), (500, 'HTTP 500')):
            def fail(*a, **k): raise HTTPError('url', code, 'error', {}, None)
            with self.assertRaisesRegex(ValueError, expected): updates.fetch_release('school/library', fail)
        def offline(*a, **k): raise URLError('offline')
        with self.assertRaisesRegex(ValueError, 'still be used'): updates.fetch_release('school/library', offline)

    def test_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(updates, 'SETTINGS', Path(folder)/'updates.json'):
                updates.write_settings('school/library', False)
                self.assertEqual(updates.read_settings(), {'repository':'school/library', 'enabled':False})
                with self.assertRaises(ValueError): updates.write_settings('bad-url', True)
                self.assertFalse(updates.read_settings()['enabled'])

    def test_url_is_trusted(self):
        result = self.release('v1.2.0', html_url='https://evil.test/')
        self.assertEqual(result['url'], 'https://github.com/school/library/releases/latest')

if __name__ == '__main__': unittest.main()
