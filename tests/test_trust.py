import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from scan import analyze
from trust import CHECKLIST, event_id, project, review


class TrustTests(unittest.TestCase):
    def test_review_requires_identity_checklist_and_exact_scan(self):
        scan = analyze({'x.qml': 'Item { property string url: "https://example.com" }'}, lint=False)
        record = {'package': '@a/b', 'commit': 'a' * 40, 'version': '1.0.0', 'scan': scan}
        self.assertEqual(project([record], [{'type': 'submission', 'package': '@a/b', 'upstream': True, 'timestamp': '2026-09-10'}])[0]['submissionStatus'], 'PENDING REVIEW')
        value = {'package': '@a/b', 'commit': 'a' * 40, 'action': 'approve', 'notes': 'Inspected code', 'checklist': CHECKLIST, 'scanDigest': event_id(scan)}
        with self.assertRaises(ValueError):
            review(value, {'id': 2, 'login': 'stranger'}, [record], [1])
        with self.assertRaises(ValueError):
            review({**value, 'scanDigest': 'old'}, {'id': 1, 'login': 'owner'}, [record], [1])
        approved = review(value, {'id': 1, 'login': 'owner'}, [record], [1])
        self.assertEqual(project([record], [approved])[0]['status'], 'verified')
        rejected = {**approved, 'action': 'reject', 'timestamp': '2026-09-11'}
        rejected_record = project([record], [approved, rejected])[0]
        self.assertEqual(rejected_record['status'], 'unverified')
        self.assertIsNone(rejected_record['verification'])
        updated = {**record, 'commit': 'b' * 40, 'scan': analyze({'x.sh': 'bash command'}, lint=False)}
        self.assertEqual(project([updated], [approved])[0]['status'], 'review-required')
        revoked = {**approved, 'action': 'revoke'}
        self.assertEqual(project([record], [approved, revoked])[0]['status'], 'revoked')
        reapproved = {**approved, 'timestamp': '2026-09-11'}
        restored = project([record], [approved, revoked, reapproved])[0]
        self.assertEqual(restored['status'], 'verified')
        self.assertIsNotNone(restored['verification'])
        self.assertEqual(scan['capabilities']['network'][0]['line'], 1)

    def test_malformed_checklists_are_rejected_and_rescans_require_review(self):
        scan = analyze({'x.qml': 'Item {}'}, lint=False)
        record = {'package': '@a/b', 'commit': 'a' * 40, 'version': '1.0.0', 'scan': scan}
        value = {'package': '@a/b', 'commit': record['commit'], 'action': 'approve',
                 'notes': 'Inspected code', 'checklist': CHECKLIST, 'scanDigest': event_id(scan)}
        actor = {'id': 1, 'login': 'owner'}
        for checklist in [None, {}, [None], [{}], CHECKLIST + [CHECKLIST[0]]]:
            with self.subTest(checklist=checklist), self.assertRaises(ValueError):
                review({**value, 'checklist': checklist}, actor, [record], [1])
        approved = review(value, actor, [record], [1])
        changed = {**record, 'scan': {**scan, 'method': 'Updated scanner'}}
        self.assertEqual(project([changed], [approved])[0]['status'], 'review-required')
        failed = {**record, 'scan': {**scan, 'validation': 'failed'}}
        self.assertEqual(project([failed], [approved])[0]['status'], 'review-required')

    def test_report_rescan_replaces_the_projected_scan(self):
        old_scan = analyze({'x.qml': 'Item {}'}, lint=False)
        new_scan = analyze({'x.qml': 'Item { property string url: "https://example.com" }'}, lint=False)
        record = {'package': '@a/b', 'commit': 'a' * 40, 'version': '1.0.0', 'scan': old_scan}
        report = {'type': 'report', 'package': '@a/b', 'commit': record['commit'], 'reason': 'Security issue',
                  'notes': 'Please check network access', 'timestamp': '2026-09-11', 'rescan': new_scan}
        projected = project([record], [report])[0]
        self.assertEqual(projected['scan'], new_scan)
        self.assertEqual(projected['scanDigest'], event_id(new_scan))

    def test_qml_parser_rejects_invalid_syntax(self):
        self.assertEqual(analyze({'Valid.qml': 'import QtQuick\nItem {}'})['validation'], 'passed')
        with self.assertRaises(ValueError):
            analyze({'Invalid.qml': 'import QtQuick\nItem { broken : }'})

    def test_qmllint_timeout_is_a_clean_scan_failure(self):
        with patch('scan.subprocess.run', side_effect=subprocess.TimeoutExpired(cmd='qmllint', timeout=15)):
            with self.assertRaises(ValueError):
                analyze({'x.qml': 'Item {}'})

    def test_qmllint_empty_files_response_does_not_crash(self):
        with patch('scan.subprocess.run', return_value=Mock(stdout=b'{"files":[]}', returncode=0)):
            result = analyze({'x.qml': 'Item {}'})
            self.assertEqual(result['qml'][0]['warnings'], 0)
