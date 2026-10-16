import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from registry import read_blob, require

SCANNER_VERSION = 1
PATTERNS = {
    'network': r'https?://|XMLHttpRequest|\bfetch\s*\(|\bsocket\b',
    'shell': r'\b(?:bash|sh|zsh|fish|sudo|pkexec)\b|shell\s*[:=]',
    'process': r'\b(?:Process|exec|spawn|Popen|subprocess)\b',
    'filesystemRead': r'\b(?:FileView|readFile|openSync|read_text|read_bytes|cat)\b',
    'filesystemWrite': r'\b(?:writeFile|write_text|write_bytes|unlink|remove|rm|mkdir|setText)\b',
    'environment': r'\b(?:getenv|environ|environment|Quickshell\.env)\b|\$\{?[A-Z_][A-Z_0-9]*',
    'downloads': r'\b(?:curl|wget|download|urlretrieve)\b',
    'downloadExecution': r'(?:curl|wget).*(?:\|\s*(?:ba)?sh|chmod|exec)|eval\s*\(',
    'obfuscation': r'\b(?:base64|atob|fromCharCode|b64decode)\b|[A-Za-z0-9+/]{200,}={0,2}',
    'credentials': r'\b(?:password|secret|token|credential|private_key)\b|\.ssh|\.aws',
}


def analyze(sources, lint=True):
    capabilities = {key: [] for key in PATTERNS}
    counts = {key: 0 for key in PATTERNS}
    for path, source in sources.items():
        for number, line in enumerate(source.splitlines(), 1):
            for key, pattern in PATTERNS.items():
                if re.search(pattern, line, re.I):
                    counts[key] += 1
                    if len(capabilities[key]) < 12:
                        capabilities[key].append({'file': path, 'line': number, 'evidence': line.strip()[:240]})
    diagnostics = []
    tool = next((p for p in ['/usr/lib/qt6/bin/qmllint'] if Path(p).exists()), None) or shutil.which('qmllint')
    require(not lint or tool, 'qmllint is required for a complete scan')
    if lint:
        with tempfile.TemporaryDirectory() as directory:
            for index, (path, source) in enumerate(sources.items()):
                if not path.endswith('.qml'):
                    continue
                target = Path(directory) / f'{index}.qml'
                target.write_text(source)
                try:
                    completed = subprocess.run([tool, '--ignore-settings', '--bare', '--json', '-', '--', str(target)],
                                               capture_output=True, timeout=15, env={'PATH': '/usr/bin:/bin', 'HOME': directory})
                except subprocess.TimeoutExpired:
                    raise ValueError(f'QML linting timed out in {path}') from None
                require(len(completed.stdout) < 1_000_000, 'QML diagnostics exceed limit')
                output = json.loads(completed.stdout)
                warnings = (output.get('files') or [{}])[0].get('warnings', [])
                require(not any(w.get('type') in ('critical', 'fatal') or w.get('id') == 'syntax' for w in warnings), f'QML syntax error in {path}')
                require(completed.returncode in (0, 255), f'QML validation failed in {path}')
                diagnostics.append({'file': path, 'warnings': len(warnings), 'note': 'Static parser only; Omarchy imports may be unavailable.'})
    return {'scannerVersion': SCANNER_VERSION, 'validation': 'passed', 'capabilities': capabilities, 'counts': counts, 'qml': diagnostics,
            'method': 'Static pattern analysis and qmllint parsing. Up to 12 evidence samples per capability; all matching lines counted. Absence of a match does not establish absence of a capability.'}


def scan_repository(api, record):
    tree = api.request(f'/repos/{record["repository"]}/git/trees/{record["tree"]}?recursive=1')
    require(not tree.get('truncated') and len(tree['tree']) <= 5000, 'Incomplete or oversized repository')
    prefix = record['path'] + '/' if record['path'] else ''
    sources = {}
    total = 0
    for item in tree['tree']:
        if item['type'] != 'blob' or not item['path'].startswith(prefix):
            continue
        path = item['path'][len(prefix):]
        if Path(path).suffix.lower() not in ('.qml', '.js', '.mjs', '.ts', '.sh', '.bash', '.py', '.json', '') and item.get('mode') != '100755':
            continue
        total += item.get('size', 0)
        require(total <= 2_000_000 and len(sources) < 100, 'Source scan exceeds 2 MB or 100 files')
        sources[path] = read_blob(api, record['repository'], item, 500000).decode('utf-8')
    record['manifest'] = json.loads(sources['manifest.json'])
    record['scan'] = analyze(sources)
    return record
