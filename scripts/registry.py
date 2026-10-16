import base64
import hashlib
import json
import re
from datetime import datetime, timezone

REGISTRY = 'Nuu-maan/omachests'
BOT_ID = 41898282
MARKER = 'Registry receipt v1\n```json\n'
KINDS = {'bar-widget': 'barWidget', 'panel': 'panel', 'overlay': 'overlay',
         'menu': 'menu', 'service': 'service', 'bar': 'bar'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def safe_path(value, empty=False):
    require(isinstance(value, str), 'Path must be a string')
    if value == '' and empty:
        return value
    require(len(value) <= 200 and re.fullmatch(r'[A-Za-z0-9_. /-]+', value)
            and not value.startswith('/') and all(p not in ('', '.', '..') for p in value.split('/')),
            'Use a relative path without traversal or special characters')
    return value


def parse_submission(body):
    require(isinstance(body, str) and len(body) <= 10000, 'Submission is missing or too large')
    blocks = re.findall(r'```(?:json)?\s*\n(.*?)```', body, re.S)
    value = json.loads(blocks[0] if len(blocks) == 1 else body)
    require(isinstance(value, dict) and set(value) <= {'repository', 'commit', 'path'}, 'Unexpected submission fields')
    repo, commit = value.get('repository'), value.get('commit')
    require(isinstance(repo, str) and re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]{1,100}', repo)
            and repo.split('/')[1] not in ('.', '..'), 'Use owner/repository, without a URL')
    require(isinstance(commit, str) and re.fullmatch(r'[0-9a-f]{40}', commit), 'Use a full lowercase 40-character commit SHA')
    return {'repository': repo, 'commit': commit, 'path': safe_path(value.get('path', ''), empty=True)}


def validate_manifest(manifest, files):
    require(isinstance(manifest, dict) and manifest.get('schemaVersion') == 1, 'Expected manifest schemaVersion 1')
    for field, limit in [('name', 100), ('description', 500), ('author', 100), ('license', 100)]:
        value = manifest.get(field)
        require(isinstance(value, str) and 0 < len(value.strip()) <= limit
                and not any(ord(c) < 32 for c in value), f'Invalid manifest {field}')
    require(isinstance(manifest.get('id'), str) and re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,119}', manifest['id'])
            and '.' in manifest['id'] and not manifest['id'].startswith('omarchy.'), 'Invalid or reserved plugin ID')
    version = manifest.get('version')
    require(isinstance(version, str) and len(version) < 80 and re.fullmatch(
        r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?', version),
        'Version must be major.minor.patch with an optional prerelease')
    kinds = manifest.get('kinds')
    require(isinstance(kinds, list) and 0 < len(kinds) <= 6
            and all(isinstance(k, str) and k in KINDS for k in kinds), 'Unsupported plugin kinds')
    entries = manifest.get('entryPoints')
    require(isinstance(entries, dict) and len(entries) <= 6, 'Invalid entryPoints')
    for kind in kinds:
        require(KINDS[kind] in entries, f'Missing {KINDS[kind]} entry point')
    for key, path in entries.items():
        require(key in KINDS.values(), 'Unknown entry point')
        safe_path(path)
        require(path.endswith('.qml') and path in files, f'Entry point does not exist: {path}')
    require(any(p.lower() in ('readme', 'readme.md', 'readme.txt') for p in files), 'A README is required')
    require(any(p.lower() in ('license', 'license.md', 'license.txt', 'copying') for p in files), 'A license file is required')


def read_blob(api, repository, item, limit=100000):
    require(item['type'] == 'blob' and item.get('mode') in ('100644', '100755') and item.get('size', limit + 1) <= limit, 'File is too large or is not a regular file')
    data = api.request(f'/repos/{repository}/git/blobs/{item["sha"]}')
    require(data.get('encoding') == 'base64', 'Unsupported blob encoding')
    raw = base64.b64decode(data['content'], validate=False)
    require(len(raw) <= limit, 'Decoded file exceeds size limit')
    return raw


def verify(api, submission, actor, issue_number, require_owner=True):
    repo = api.request('/repos/' + submission['repository'])
    require(not repo['private'] and not repo['archived'] and not repo.get('disabled'), 'Repository must be public and active')
    repository = repo['full_name']
    require(repository.lower() == submission['repository'].lower(), 'Repository moved; submit its canonical name')
    commit = submission['commit']
    revision = api.request(f'/repos/{repository}/commits/{commit}')
    require(revision['sha'] == commit, 'Commit did not resolve exactly')
    tree_sha = revision['commit']['tree']['sha']
    tree = api.request(f'/repos/{repository}/git/trees/{tree_sha}?recursive=1')
    require(not tree.get('truncated') and len(tree['tree']) <= 5000, 'Repository tree is incomplete or exceeds 5,000 entries')
    prefix = submission['path'] + '/' if submission['path'] else ''
    files = {item['path'][len(prefix):]: item for item in tree['tree'] if item['path'].startswith(prefix)}
    require(files and all(i.get('mode') not in ('120000', '160000') for i in files.values()), 'Plugin cannot contain symlinks or submodules')
    require(sum(i.get('size', 0) for i in files.values()) <= 50_000_000, 'Plugin exceeds 50 MB')
    if require_owner and (repo['owner']['type'] != 'User' or actor.lower() != repo['owner']['login'].lower()):
        proof_item = next((i for i in tree['tree'] if i['path'] == '.omarchy-registry.json'), None)
        require(proof_item is not None, 'Non-owner maintainers must add .omarchy-registry.json ownership proof; see publishing guide')
        proof = json.loads(read_blob(api, repository, proof_item))
        require(proof == {'registry': REGISTRY, 'publisher': actor,
                          'issue': f'https://github.com/{REGISTRY}/issues/{issue_number}'}, 'Ownership proof does not match this publisher and issue')
    require('manifest.json' in files, 'manifest.json was not found at the selected path')
    files = {path: item for path, item in files.items() if item['type'] == 'blob'}
    require('manifest.json' in files, 'Manifest must be a regular file')
    raw = read_blob(api, repository, files['manifest.json'])
    manifest = json.loads(raw)
    validate_manifest(manifest, files)
    warnings = []
    for path in manifest['entryPoints'].values():
        source = read_blob(api, repository, files[path], 500000).decode('utf-8')
        if re.search(r'\b(Process|exec|sudo|pkexec|XMLHttpRequest)\b', source):
            warnings.append(f'{path}: process execution, privilege escalation, or network access; inspect source')
    return {'package': '@' + repository.lower() + ('/' + submission['path'] if prefix else ''),
            'repository': repository, 'repositoryId': repo['id'], 'path': submission['path'],
            'commit': commit, 'tree': tree_sha, 'manifestSha256': hashlib.sha256(raw).hexdigest(),
            **{k: manifest[k] for k in ('id', 'name', 'description', 'author', 'license', 'version', 'kinds')},
            'publisher': actor, 'publishedAt': datetime.now(timezone.utc).isoformat(),
            'repositoryCreatedAt': repo['created_at'], 'stars': repo['stargazers_count'],
            'forks': repo['forks_count'], 'warnings': warnings, 'status': 'checked',
            'issue': f'https://github.com/{REGISTRY}/issues/{issue_number}'}


def check_identity(records, record):
    previous = [r for r in records if r['package'] == record['package']]
    require(all(r['repositoryId'] == record['repositoryId'] for r in previous), 'Repository identity changed; contact registry administrators')
    require(all(r['package'] == record['package'] for r in records if r.get('id') == record['id']), 'Plugin ID is already used by another package')


def check_release(records, record):
    check_identity(records, record)
    previous = [r for r in records if r['package'] == record['package']]
    same = [r for r in previous if r['version'] == record['version']]
    require(not same or all(r['commit'] == record['commit'] for r in same), 'A published version cannot be replaced; bump the version')
    return not same
