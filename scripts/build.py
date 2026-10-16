import hashlib
import json
from collections import defaultdict
from xml.etree.ElementTree import Element, SubElement, tostring
from pathlib import Path

from registry import parse_submission
from trust import project

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'public'


def version_key(record):
    core, _, prerelease = record['version'].partition('-')
    return (tuple(int(v) for v in core.split('.')), not prerelease,
            tuple((0, int(p)) if p.isdigit() else (1, p) for p in prerelease.split('.')))


def listing_key(record):
    return version_key(record), record.get('publishedAt') or record.get('importedAt') or ''


def load_records():
    seeds = json.loads((ROOT / 'data/seed.json').read_text())
    live_path = ROOT / '_records.json'
    live = json.loads(live_path.read_text()) if live_path.exists() else []
    records = []
    for record in seeds + live:
        parse_submission(json.dumps({k: record[k] for k in ('repository', 'commit', 'path')}))
        records.append(record)
    ledger_path = ROOT / '_events.json'
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else []
    return project(records, ledger)


def build():
    records = [{**record, 'slug': hashlib.sha256(record['package'].encode()).hexdigest()[:20]} for record in load_records()]
    grouped = defaultdict(list)
    for record in records:
        grouped[record['package']].append(record)
    latest = []
    for history in grouped.values():
        record = max(history, key=listing_key)
        if record['status'] in ('checked', 'discovered'):
            record = {**record, 'status': 'unverified', 'submissionStatus': 'PENDING REVIEW', 'reviews': [], 'reports': [], 'verification': None, 'capabilityChanges': []}
        latest.append({**record, 'slug': hashlib.sha256(record['package'].encode()).hexdigest()[:20]})
    latest.sort(key=lambda r: (r['status'] != 'verified', r['name'].lower()))
    revisions = {(r['package'], r['commit']): r for r in records if r.get('publishedAt')}
    activity = sorted(revisions.values(), key=lambda r: r['publishedAt'], reverse=True)
    OUT.mkdir(exist_ok=True, parents=True)
    (OUT / 'registry.json').write_text(json.dumps({'schemaVersion': 1, 'plugins': latest, 'releases': activity}, separators=(',', ':')))
    sitemap = Element('urlset', xmlns='http://www.sitemaps.org/schemas/sitemap/0.9')
    for path in ['/', '/publish/', '/review/', '/security/', '/activity/'] + [f'/packages/{r["slug"]}/' for r in latest]:
        SubElement(SubElement(sitemap, 'url'), 'loc').text = 'https://omachests.com' + path
    (OUT / 'sitemap.xml').write_bytes(tostring(sitemap, encoding='utf-8', xml_declaration=True))
    print(f'Exported {len(latest)} plugins and {len(activity)} releases.')


if __name__ == '__main__':
    build()
