import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from registry import require

MARKER = 'Registry event v2\n```json\n'
CHECKLIST = ['behavior', 'manifest', 'entrypoints', 'malware', 'capabilities', 'ownership',
             'obfuscation', 'downloads', 'credentials', 'shell', 'destructive', 'description']
ACTIONS = {'approve': 'APPROVED', 'reject': 'REJECTED', 'changes': 'CHANGES REQUESTED',
           'flag': 'REVIEW REQUIRED', 'revoke': 'REVOKED'}
REASONS = ['Malware', 'Suspicious behavior', 'Broken plugin', 'Misleading description',
           'Impersonation', 'Spam', 'Copyright issue', 'Security issue', 'Other']


def payload(body):
    require(isinstance(body, str) and len(body) <= 20000, 'Request is missing or too large')
    blocks = re.findall(r'```(?:json)?\s*\n(.*?)```', body, re.S)
    value = json.loads(blocks[0] if len(blocks) == 1 else body)
    require(isinstance(value, dict), 'Expected a JSON object')
    return value


def event_id(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def review(value, actor, records, reviewers):
    require(actor['id'] in reviewers, 'Only configured reviewers can moderate plugins')
    require(value.get('action') in ACTIONS, 'Unknown review action')
    matches = [r for r in records if r['package'] == value.get('package') and r['commit'] == value.get('commit')]
    require(matches, 'The exact commit must have a recorded scan before review')
    record = matches[-1]
    require(isinstance(value.get('notes'), str) and 0 < len(value['notes'].strip()) <= 4000, 'A review reason is required')
    if value['action'] == 'approve':
        checklist = value.get('checklist')
        require(isinstance(checklist, list) and all(isinstance(item, str) for item in checklist) and
                len(checklist) == len(CHECKLIST) and set(checklist) == set(CHECKLIST), 'Complete every review checklist item')
        require(record.get('scan', {}).get('validation') == 'passed', 'Approval requires a successful static scan')
        require(value.get('scanDigest') == event_id(record['scan']), 'Scan changed; review the latest scan')
    recommendation = value.get('recommendation', '')
    require(isinstance(recommendation, str) and len(recommendation) <= 2000, 'Invalid advisory recommendation')
    return {'type': 'review', 'package': record['package'], 'commit': record['commit'],
            'version': record['version'], 'repositoryId': record.get('repositoryId'), 'repository': record.get('repository'), 'action': value['action'], 'notes': value['notes'].strip(),
            'recommendation': recommendation, 'reviewer': actor['login'], 'reviewerId': actor['id'],
            'checklist': value.get('checklist', []), 'scan': record.get('scan'),
            'timestamp': datetime.now(timezone.utc).isoformat()}


def project(records, ledger):
    result = []
    for original in records:
        record = dict(original)
        related = [e for e in ledger if e.get('package') == record['package']]
        rescans = [e for e in related if e['type'] == 'report' and e.get('commit') == record['commit'] and e.get('rescan')]
        if rescans:
            record['scan'] = rescans[-1]['rescan']
        reviews = [e for e in related if e['type'] == 'review']
        exact = [e for e in reviews if e['commit'] == record['commit']]
        approved_by_commit = {}
        for e in reviews:
            if e['action'] == 'approve':
                approved_by_commit[e['commit']] = e
            else:
                approved_by_commit.pop(e['commit'], None)
        approved = list(approved_by_commit.values())
        record['reviews'] = reviews
        reports = [e for e in related if e['type'] == 'report' and (not exact or e['timestamp'] > exact[-1]['timestamp'])]
        record['reports'] = []
        for report in reports:
            public = {key: value for key, value in report.items() if key not in ('rescan', 'rescanError')}
            if report.get('rescan'):
                public['rescanStatus'] = 'completed'
            elif report.get('rescanError'):
                public['rescanStatus'] = 'failed'
            record['reports'].append(public)
        record['verification'] = approved[-1] if approved else None
        record['submissionStatus'] = ACTIONS[exact[-1]['action']] if exact else 'PENDING REVIEW'
        record['status'] = 'verified' if record['submissionStatus'] == 'APPROVED' else 'unverified'
        baseline = (record['verification'] or {}).get('scan') or {}
        current = record.get('scan') or {}
        record['capabilityChanges'] = [key for key, evidence in current.get('capabilities', {}).items()
                                       if evidence and not baseline.get('capabilities', {}).get(key)] if approved else []
        triggers = [e for e in related if (e['type'] in ('report', 'upstream') or (e.get('upstream') and approved)) and
                    (not exact or e['timestamp'] > exact[-1]['timestamp'])]
        identity_changed = approved and (approved[-1].get('repositoryId') != record.get('repositoryId') or approved[-1].get('repository') != record.get('repository'))
        scan_changed = exact and exact[-1]['action'] == 'approve' and (
            current.get('validation') != 'passed' or event_id(current) != event_id(exact[-1].get('scan') or {}))
        if record['capabilityChanges'] or triggers or identity_changed or scan_changed or (approved and not exact):
            record['submissionStatus'] = 'REVIEW REQUIRED'
            record['status'] = 'review-required'
        if exact and exact[-1]['action'] == 'revoke':
            record['submissionStatus'] = 'REVOKED'
            record['status'] = 'revoked'
        record['trustEvents'] = [e for e in related if e['type'] == 'upstream']
        record['scanDigest'] = event_id(current)
        result.append(record)
    return result
