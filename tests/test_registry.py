import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from registry import BOT_ID, MARKER, check_release, parse_submission, receipts, safe_path, validate_manifest


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {'schemaVersion': 1, 'id': 'someone.clock', 'name': 'Clock', 'description': 'A clock',
                         'author': 'Someone', 'license': 'MIT', 'version': '1.0.0',
                         'kinds': ['bar-widget'], 'entryPoints': {'barWidget': 'Bar.qml'}}
        self.files = {'Bar.qml', 'README.md', 'LICENSE'}

    def test_manifest_and_submission(self):
        validate_manifest(self.manifest, self.files)
        request = {'repository': 'someone/clock', 'commit': 'a' * 40}
        self.assertEqual(parse_submission('### Release\n```json\n' + json.dumps(request) + '\n```')['path'], '')

    def test_rejects_malformed_manifest(self):
        for key, value in [('id', 'omarchy.clock'), ('version', '1.0'), ('kinds', ['unknown']),
                           ('kinds', [{}]), ('name', '<clock>\n'), ('entryPoints', {'barWidget': '../Bar.qml'})]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_manifest({**self.manifest, key: value}, self.files)
        with self.assertRaises(ValueError):
            validate_manifest(self.manifest, {'README.md', 'LICENSE'})

    def test_path_and_repository_boundaries(self):
        for path in ('../x', '/x', 'x/../y', 'x//y', 'x\\y', 'x;touch z', 'x\n', ''):
            with self.subTest(path=path), self.assertRaises(ValueError):
                safe_path(path)
        for repo in ('https://github.com/a/b', 'a/b?ref=x', 'a/..', 'a/b/c'):
            with self.subTest(repo=repo), self.assertRaises(ValueError):
                parse_submission(json.dumps({'repository': repo, 'commit': 'a' * 40}))
        with self.assertRaises(ValueError):
            parse_submission(json.dumps({'repository': 'a/b', 'commit': 'main'}))

    def test_versions_cannot_be_overwritten_or_taken_over(self):
        old = {'package': '@someone/clock', 'repositoryId': 1, 'id': 'someone.clock', 'version': '1.0.0', 'commit': 'a' * 40}
        self.assertFalse(check_release([old], old))
        self.assertTrue(check_release([old], {**old, 'version': '1.0.1'}))
        for change in ({'commit': 'b' * 40}, {'repositoryId': 2}):
            with self.assertRaises(ValueError):
                check_release([old], {**old, **change})
        with self.assertRaises(ValueError):
            check_release([old], {**old, 'package': '@other/clock', 'repositoryId': 2})

    def test_only_registry_bot_receipts_are_read(self):
        class API:
            def pages(self, path):
                return [{'user': {'id': user}, 'body': MARKER + '{"package":"@a/b"}\n```',
                         'html_url': 'https://github.com/receipt'} for user in (123, BOT_ID)]
        self.assertEqual(len(receipts(API())), 1)


if __name__ == '__main__':
    unittest.main()
