import json
import os
from pathlib import Path
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import quote

from github import GitHub
from intake import prepare
from registry import BOT_ID, MARKER as RECEIPT_MARKER, REGISTRY, check_identity, verify
from scan import SCANNER_VERSION, scan_repository
from trust import MARKER as EVENT_MARKER, event_id, payload, project, review


def load(api):
    ledger = []
    records = []
    # shortcut: scan at most 10,000 comments; use indexed storage beyond that.
    for comment in api.pages(f'/repos/{REGISTRY}/issues/comments'):
        if comment['user']['id'] != BOT_ID:
            continue
        body = comment.get('body', '')
        if body.startswith(EVENT_MARKER):
            event = json.loads(body[len(EVENT_MARKER):].split('\n```', 1)[0])
            event['receipt'] = comment['html_url']
            ledger.append(event)
        elif body.startswith(RECEIPT_MARKER):
            record = json.loads(body[len(RECEIPT_MARKER):].split('\n```', 1)[0])
            record['receipt'] = comment['html_url']
            records.append(record)
    records.extend({**e['record'], 'receipt': e['receipt']} for e in ledger if e['type'] == 'submission')
    return records, ledger


def monitor(api, records, ledger):
    latest = {r['package']: r for r in records}
    proposals = []
    for package, record in latest.items():
        try:
            metadata = api.request(f'/repositories/{record["repositoryId"]}')
            releases = api.request(f'/repos/{metadata["full_name"]}/releases?per_page=10')
            release_state = [{'id': r['id'], 'tag': r['tag_name'], 'authorId': r['author']['id'], 'updatedAt': r['updated_at']} for r in releases]
            state = {'releases': release_state, 'repository': metadata['full_name'], 'archived': metadata['archived'], 'disabled': metadata.get('disabled', False)}
            sha = api.request(f'/repos/{metadata["full_name"]}/commits/{quote(metadata["default_branch"], safe="")}')['sha']
            changed = release_state != record.get('releaseState', []) or (record.get('scan') or {}).get('scannerVersion') != SCANNER_VERSION or sha != record['commit'] or metadata['full_name'] != record['repository'] or state['archived'] or state['disabled']
            if not changed:
                continue
            identity = event_id({'package': package, 'commit': sha, 'scannerVersion': SCANNER_VERSION, **state})
            if any(e.get('requestId') == identity for e in ledger):
                continue
            event = {'type': 'upstream', 'package': package, 'commit': sha, 'state': state, 'requestId': identity,
                     'timestamp': datetime.now(timezone.utc).isoformat()}
            try:
                fresh = verify(api, {'repository': metadata['full_name'], 'commit': sha, 'path': record['path']}, record.get('publisher') or '', 0, require_owner=False)
                fresh['package'] = package
                check_identity(records, fresh)
                fresh['releaseState'] = release_state
                if releases:
                    fresh['changelog'] = (releases[0].get('body') or '')[:4000]
                    fresh['releaseUrl'] = releases[0]['html_url']
                fresh = scan_repository(api, fresh)
                if sha != record['commit']:
                    try:
                        comparison = api.request(f'/repos/{metadata["full_name"]}/compare/{record["commit"]}...{sha}')
                        fresh['changedFiles'] = [item['filename'] for item in comparison.get('files', [])]
                        fresh['compareUrl'] = f'https://github.com/{metadata["full_name"]}/compare/{record["commit"]}...{sha}'
                    except HTTPError as error:
                        if error.code not in (404, 409, 422):
                            raise
                        fresh['warnings'].append('Commit comparison is unavailable; inspect the repository history directly.')
                event['record'] = fresh
                event['type'] = 'submission'
                event['upstream'] = True
            except (ValueError, KeyError) as error:
                event['notes'] = str(error)[:1000]
            proposals.append({'issue': 11, 'event': event})
        except HTTPError as error:
            if error.code != 404:
                raise
            identity = event_id({'package': package, 'unavailable': True})
            if not any(e.get('requestId') == identity for e in ledger):
                proposals.append({'issue': 11, 'event': {'type': 'upstream', 'package': package,
                    'notes': 'Repository is unavailable or no longer public.', 'requestId': identity,
                    'timestamp': datetime.now(timezone.utc).isoformat()}})
    return proposals


def persist(api, proposals):
    records, ledger = load(api)
    reviewers = json.loads(Path('data/reviewers.json').read_text())
    known = project(json.loads(Path('data/seed.json').read_text()) + records, ledger)
    for proposal in proposals:
        endpoint = f'/repos/{REGISTRY}/issues/{proposal["issue"]}'
        issue = api.request(endpoint)
        if 'body' in proposal and (issue['body'] != proposal['body'] or issue['user']['id'] != proposal['actorId'] or issue['state'] != 'open'):
            continue
        if 'error' in proposal:
            body = 'CHANGES REQUESTED\n\n' + proposal['error'] + '\n\nCorrect this request and reopen it. No verification was granted.'
        else:
            event = proposal['event']
            if any(e.get('requestId') == event['requestId'] for e in ledger):
                continue
            if event['type'] == 'review':
                checked = review(payload(issue['body']), issue['user'], known, reviewers)
                event = {**checked, 'requestId': event['requestId']}
            body = EVENT_MARKER + json.dumps(event, separators=(',', ':')) + '\n```\n\n' + ('PENDING REVIEW — automated analysis is not a guarantee of safety.' if event['type'] == 'submission' else 'Recorded in the public review history.')
            if len(body) > 60000:
                raise ValueError('Record exceeds GitHub comment limit')
        api.request(endpoint + '/comments', 'POST', {'body': body})
        if 'body' in proposal:
            api.request(endpoint, 'PATCH', {'state': 'closed', 'state_reason': 'not_planned' if 'error' in proposal else 'completed'})


if __name__ == '__main__':
    api = GitHub()
    mode = os.environ.get('REGISTRY_MODE', 'export')
    if mode == 'persist':
        persist(api, json.loads(Path('_proposals.json').read_text()))
    records, ledger = load(api)
    if mode == 'scan':
        seeds = json.loads(Path('data/seed.json').read_text())
        proposals = prepare(api, seeds + records, ledger) + monitor(api, seeds + records, ledger)
        Path('_proposals.json').write_text(json.dumps(proposals))
    Path('_records.json').write_text(json.dumps(records))
    Path('_events.json').write_text(json.dumps(ledger))
