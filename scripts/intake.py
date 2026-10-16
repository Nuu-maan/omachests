import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, quote
from urllib.error import HTTPError

from registry import REGISTRY, check_release, parse_submission, require, verify
from scan import scan_repository
from trust import REASONS, event_id, payload, project, review


def resolve(api, body):
    value = payload(body)
    repository = value.get('repository', '')
    if repository.startswith('https://'):
        url = urlparse(repository)
        require(url.netloc == 'github.com' and not url.query and not url.fragment, 'Use a public github.com repository URL')
        repository = url.path.strip('/').removesuffix('.git')
    submission = parse_submission(json.dumps({'repository': repository, 'commit': value.get('commit') or '0' * 40, 'path': value.get('path', '')}))
    if not value.get('commit'):
        metadata = api.request('/repos/' + repository)
        submission['commit'] = api.request(f'/repos/{repository}/commits/{quote(metadata["default_branch"], safe="")}')['sha']
    if not submission['path']:
        revision = api.request(f'/repos/{repository}/commits/{submission["commit"]}')
        tree = api.request(f'/repos/{repository}/git/trees/{revision["commit"]["tree"]["sha"]}?recursive=1')
        require(not tree.get('truncated') and len(tree['tree']) <= 5000, 'Repository tree is incomplete or too large')
        manifests = [item['path'] for item in tree['tree'] if item['path'].endswith('/manifest.json') or item['path'] == 'manifest.json']
        if 'manifest.json' not in manifests:
            require(len(manifests) == 1, 'Choose a plugin directory: repository has no root manifest or multiple manifests')
            submission['path'] = manifests[0].rsplit('/', 1)[0]
    return submission


def prepare(api, records, ledger):
    proposals = []
    reviewers = json.loads(Path('data/reviewers.json').read_text())
    seen = {e.get('requestId') for e in ledger}
    for issue in api.pages(f'/repos/{REGISTRY}/issues?state=open&sort=created&direction=asc'):
        labels = {label['name'] for label in issue['labels']}
        if 'pull_request' in issue:
            continue
        if not labels.intersection({'publish', 'review', 'report'}):
            try:
                value = payload(issue['body'])
            except (ValueError, TypeError):
                continue
            if 'action' in value:
                labels.add('review')
            elif 'package' in value and 'reason' in value:
                labels.add('report')
            elif 'repository' in value:
                labels.add('publish')
            else:
                continue
        if len(proposals) >= 20:
            break
        request_id = event_id({'issue': issue['number'], 'body': issue['body'], 'actor': issue['user']['id']})
        if request_id in seen:
            continue
        try:
            if 'review' in labels:
                event = review(payload(issue['body']), issue['user'], project(records, ledger), reviewers)
            elif 'report' in labels:
                value = payload(issue['body'])
                matches = [r for r in records if r['package'] == value.get('package') and r['commit'] == value.get('commit')]
                require(matches and value.get('reason') in REASONS, 'Choose an existing plugin commit and a report reason')
                require(isinstance(value.get('notes', ''), str) and len(value.get('notes', '')) <= 4000, 'Explanation exceeds 4,000 characters')
                latest = matches[-1]
                event = {'type': 'report', 'package': value['package'], 'commit': latest['commit'], 'reason': value['reason'],
                         'notes': value.get('notes', ''), 'reporter': issue['user']['login']}
                try:
                    event['rescan'] = scan_repository(api, dict(latest))['scan']
                except (ValueError, KeyError, HTTPError) as error:
                    event['rescanError'] = str(error)[:1000]
            else:
                submission = resolve(api, issue['body'])
                record = scan_repository(api, verify(api, submission, issue['user']['login'], issue['number'], require_owner=False))
                check_release(records, record)
                event = {'type': 'submission', 'package': record['package'], 'record': record}
            event.update(requestId=request_id, timestamp=datetime.now(timezone.utc).isoformat())
            proposals.append({'issue': issue['number'], 'body': issue['body'], 'actorId': issue['user']['id'], 'event': event})
        except HTTPError as error:
            if error.code not in (404, 422):
                raise
            proposals.append({'issue': issue['number'], 'body': issue['body'], 'actorId': issue['user']['id'], 'error': 'Repository or commit is inaccessible. Use a public GitHub repository and existing commit.'})
        except (ValueError, KeyError, TypeError, UnicodeError) as error:
            proposals.append({'issue': issue['number'], 'body': issue['body'], 'actorId': issue['user']['id'], 'error': str(error)[:1000]})
    return proposals
