import base64
import copy
import json
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build
import publish
from registry import BOT_ID, MARKER as RECEIPT_MARKER, verify
from scan import analyze
from trust import CHECKLIST, MARKER as EVENT_MARKER, event_id


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

    def test_public_ledger_is_loaded_in_one_pass(self):
        class LedgerAPI:
            calls = 0

            def pages(self, path):
                self.calls += 1
                return [
                    {'user': {'id': BOT_ID}, 'body': RECEIPT_MARKER + '{"package":"@a/b"}\n```', 'html_url': 'https://github.com/receipt'},
                    {'user': {'id': BOT_ID}, 'body': EVENT_MARKER + '{"type":"report","package":"@a/b"}\n```', 'html_url': 'https://github.com/event'},
                    {'user': {'id': 123}, 'body': RECEIPT_MARKER + '{"package":"@evil/repo"}\n```', 'html_url': 'https://github.com/ignored'},
                ]

        api = LedgerAPI()
        records, ledger = publish.load(api)
        self.assertEqual(api.calls, 1)
        self.assertEqual([record['package'] for record in records], ['@a/b'])
        self.assertEqual([event['package'] for event in ledger], ['@a/b'])

    def test_writer_skips_an_issue_changed_after_scanning(self):
        class WriterAPI:
            writes = []

            def pages(self, path):
                return []

            def request(self, path, method='GET', data=None):
                if method == 'GET':
                    return {'body': 'changed', 'user': {'id': 1}, 'state': 'open'}
                self.writes.append((method, data))

        api = WriterAPI()
        publish.persist(api, [{'issue': 1, 'body': 'original', 'actorId': 1,
                               'event': {'type': 'report', 'requestId': 'request'}}])
        self.assertEqual(api.writes, [])

    def test_writer_revalidates_review_before_recording_it(self):
        scan = analyze({'x.qml': 'Item {}'}, lint=False)
        record = {'package': '@owner/clock', 'commit': 'a' * 40, 'version': '1.0.0', 'repositoryId': 1,
                  'repository': 'owner/clock', 'scan': scan}
        value = {'package': record['package'], 'commit': record['commit'], 'action': 'approve', 'notes': 'Inspected code',
                 'checklist': CHECKLIST, 'scanDigest': event_id(scan)}
        body = json.dumps(value)

        class WriterAPI:
            writes = []

            def request(self, path, method='GET', data=None):
                if method == 'GET':
                    return {'body': body, 'user': {'id': 174859539, 'login': 'Nuu-maan'}, 'state': 'open'}
                self.writes.append((method, data))

        api = WriterAPI()
        proposal = {'issue': 1, 'body': body, 'actorId': 174859539,
                    'event': {'type': 'review', 'requestId': 'request'}}
        with patch('publish.load', return_value=([record], [])):
            publish.persist(api, [proposal])
        self.assertEqual([method for method, _ in api.writes], ['POST', 'PATCH'])
        self.assertIn('"action":"approve"', api.writes[0][1]['body'])

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

    def test_monitor_keeps_new_scan_when_comparison_is_unavailable(self):
        old_commit = 'a' * 40
        new_commit = 'b' * 40
        compare_error = HTTPError('', 404, 'Not Found', {}, None)
        record = {'package': '@owner/clock', 'repositoryId': 1, 'repository': 'owner/clock', 'id': 'owner.clock', 'path': '',
                  'commit': old_commit, 'publisher': 'owner', 'releaseState': [], 'scan': {'validation': 'passed'}}

        class MonitorAPI:
            def request(self, path):
                if path == '/repositories/1':
                    return {'full_name': 'owner/clock', 'archived': False, 'disabled': False, 'default_branch': 'main'}
                if path.endswith('/releases?per_page=10'):
                    return []
                if path.endswith('/commits/main'):
                    return {'sha': new_commit}
                if '/compare/' in path:
                    raise compare_error
                raise AssertionError(path)

        fresh = {**record, 'commit': new_commit, 'warnings': []}
        with patch('publish.verify', return_value=fresh), patch('publish.scan_repository', return_value=fresh):
            event = publish.monitor(MonitorAPI(), [record], [])[0]['event']
        compare_error.close()
        self.assertEqual(event['type'], 'submission')
        self.assertEqual(event['record']['commit'], new_commit)
        self.assertIn('comparison is unavailable', event['record']['warnings'][0])

    def test_monitor_rescans_records_from_an_older_scanner(self):
        commit = 'a' * 40
        record = {'package': '@owner/clock', 'repositoryId': 1, 'repository': 'owner/clock', 'id': 'owner.clock', 'path': '',
                  'commit': commit, 'publisher': 'owner', 'releaseState': [], 'scan': {'scannerVersion': 0}}

        class MonitorAPI:
            def request(self, path):
                if path == '/repositories/1':
                    return {'full_name': 'owner/clock', 'archived': False, 'disabled': False, 'default_branch': 'main'}
                if path.endswith('/releases?per_page=10'):
                    return []
                if path.endswith('/commits/main'):
                    return {'sha': commit}
                raise AssertionError(path)

        fresh = {**record, 'warnings': []}
        with patch('publish.verify', return_value=fresh), patch('publish.scan_repository', return_value=fresh):
            event = publish.monitor(MonitorAPI(), [record], [])[0]['event']
        self.assertEqual(event['type'], 'submission')


if __name__ == '__main__':
    unittest.main()
