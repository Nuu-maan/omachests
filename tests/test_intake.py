import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from intake import prepare


class IntakeTests(unittest.TestCase):
    def test_unlabeled_community_request_is_scanned_but_not_approved(self):
        issue = {'number': 20, 'labels': [], 'body': json.dumps({'repository': 'https://github.com/owner/plugin'}), 'user': {'id': 2, 'login': 'visitor'}}
        class API:
            def pages(self, path):
                return [issue]
        record = {'package': '@owner/plugin', 'repositoryId': 1, 'id': 'owner.plugin', 'commit': 'a' * 40}
        with patch('intake.resolve', return_value={}), patch('intake.verify', return_value=record), patch('intake.scan_repository', return_value=record):
            proposal = prepare(API(), [], [])[0]
        self.assertEqual(proposal['event']['type'], 'submission')
        self.assertNotIn('action', proposal['event'])
        issue['body'] = json.dumps({'action': 'approve', 'package': '@owner/plugin', 'commit': 'a' * 40})
        self.assertIn('Only configured reviewers', prepare(API(), [record], [])[0]['error'])

    def test_resubmission_cannot_replace_a_published_version(self):
        issue = {'number': 21, 'labels': [], 'body': json.dumps({'repository': 'https://github.com/owner/plugin'}), 'user': {'id': 2, 'login': 'visitor'}}
        class API:
            def pages(self, path):
                return [issue]
        published = {'package': '@owner/plugin', 'commit': 'a' * 40, 'version': '1.0.0', 'repositoryId': 1, 'id': 'owner.plugin'}
        resubmission = {**published, 'commit': 'b' * 40}
        with patch('intake.resolve', return_value={}), patch('intake.verify', return_value=resubmission), patch('intake.scan_repository', return_value=resubmission):
            proposal = prepare(API(), [published], [])[0]
        self.assertIn('cannot be replaced', proposal['error'])
