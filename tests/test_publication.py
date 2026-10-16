import base64
import copy
import json
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build
import publish
from registry import verify


class API:
    def __init__(self):
        self.manifest = {'schemaVersion': 1, 'id': 'owner.clock', 'name': 'Clock', 'description': 'Clock widget',
                         'author': 'Owner', 'license': 'MIT', 'version': '1.0.0', 'kinds': ['bar-widget'],
                         'entryPoints': {'barWidget': 'Bar.qml'}}
        self.tree = [{'path': path, 'sha': path, 'type': 'blob', 'mode': '100644', 'size': 1000}
                     for path in ('manifest.json', 'README.md', 'LICENSE', 'Bar.qml')]
        self.organization = False
        self.proof = {}

    def request(self, path):
        if '/git/blobs/' in path:
            name = path.rsplit('/', 1)[-1]
            value = json.dumps(self.manifest) if name == 'manifest.json' else (
                json.dumps(self.proof) if name == '.omarchy-registry.json' else 'import QtQuick\nItem {}')
            return {'encoding': 'base64', 'content': base64.b64encode(value.encode()).decode()}
        if '/git/trees/' in path:
            return {'tree': self.tree, 'truncated': False}
        if '/commits/' in path:
            return {'sha': 'a' * 40, 'commit': {'tree': {'sha': 'b' * 40}}}
        return {'full_name': 'owner/clock', 'private': False, 'archived': False, 'id': 1,
                'owner': {'login': 'owner', 'type': 'Organization' if self.organization else 'User'},
                'created_at': '2020-01-01T00:00:00Z', 'stargazers_count': 2, 'forks_count': 0}


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.api = API()
        self.submission = {'repository': 'owner/clock', 'commit': 'a' * 40, 'path': ''}

    def test_owner_publishes_pinned_manifest_without_execution(self):
        result = verify(self.api, self.submission, 'owner', 1)
        self.assertEqual(result['version'], '1.0.0')
        self.assertEqual(len(result['manifestSha256']), 64)
        self.assertEqual(result['repositoryId'], 1)

    def test_non_owner_and_organization_need_issue_bound_proof(self):
        for actor in ('intruder', 'owner'):
            self.api.organization = True
            with self.assertRaises(ValueError):
                verify(self.api, self.submission, actor, 1)
        self.api.tree.append({'path': '.omarchy-registry.json', 'sha': '.omarchy-registry.json',
                              'type': 'blob', 'mode': '100644', 'size': 1000})
        self.api.proof = {'registry': 'Nuu-maan/omachests', 'publisher': 'member',
                          'issue': 'https://github.com/Nuu-maan/omachests/issues/1'}
        self.assertEqual(verify(self.api, self.submission, 'member', 1)['publisher'], 'member')
        with self.assertRaises(ValueError):
            verify(self.api, self.submission, 'member', 2)

    def test_symlinks_submodules_and_directories_are_rejected(self):
        for mode in ('120000', '160000'):
            self.api.tree[3]['mode'] = mode
            with self.assertRaises(ValueError):
                verify(self.api, self.submission, 'owner', 1)
        self.api.tree[3].update(mode='040000', type='tree')
        with self.assertRaises(ValueError):
            verify(self.api, self.submission, 'owner', 1)

    def test_export_keeps_untrusted_metadata_as_json(self):
        record = json.loads((build.ROOT / 'data/seed.json').read_text())[0]
        record['name'] = '<script>alert(1)</script>'
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            with patch.object(build, 'OUT', out), patch.object(build, 'load_records', return_value=[record, {**record, 'publishedAt': '2026-09-10', 'receipt': 'https://github.com/example/1'}, {**record, 'publishedAt': '2026-09-11', 'receipt': 'https://github.com/example/2'}]):
                build.build()
            exported = json.loads((out / 'registry.json').read_text())['plugins'][0]
            self.assertEqual(exported['name'], record['name'])
            self.assertEqual(exported['status'], 'unverified')
            self.assertEqual(len(exported['slug']), 20)
            releases = json.loads((out / 'registry.json').read_text())['releases']
            self.assertEqual(len(releases), 1)
            self.assertEqual(releases[0]['receipt'], 'https://github.com/example/2')

    def test_semantic_release_order(self):
        versions = ['1.0.0-beta.10', '1.0.0-beta.2', '1.0.0', '0.9.9', '1.0.1']
        self.assertEqual(sorted(versions, key=lambda v: build.version_key({'version': v})),
                         ['0.9.9', '1.0.0-beta.2', '1.0.0-beta.10', '1.0.0', '1.0.1'])

    def test_latest_listing_is_chosen_by_version_not_append_order(self):
        record = json.loads((build.ROOT / 'data/seed.json').read_text())[0]
        newer = {**record, 'commit': 'c' * 40, 'version': '2.0.0', 'publishedAt': '2026-09-10'}
        older = {**record, 'commit': 'd' * 40, 'version': '1.0.0', 'publishedAt': '2026-09-11'}
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            with patch.object(build, 'OUT', out), patch.object(build, 'load_records', return_value=[newer, older]):
                build.build()
            exported = json.loads((out / 'registry.json').read_text())['plugins'][0]
            self.assertEqual(exported['version'], '2.0.0')

    def test_latest_listing_uses_newest_scan_when_version_is_unchanged(self):
        record = json.loads((build.ROOT / 'data/seed.json').read_text())[0]
        old = {**record, 'commit': 'c' * 40, 'version': '2.0.0', 'publishedAt': '2026-09-10'}
        new = {**record, 'commit': 'd' * 40, 'version': '2.0.0', 'publishedAt': '2026-09-11'}
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(build, 'OUT', Path(directory)), patch.object(build, 'load_records', return_value=[old, new]):
                build.build()
            exported = json.loads((Path(directory) / 'registry.json').read_text())['plugins'][0]
            self.assertEqual(exported['commit'], new['commit'])


if __name__ == '__main__':
    unittest.main()
