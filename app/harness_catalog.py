"""Pinned upstream procedure discovery only; no network or instruction execution."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'NousResearch/hermes-agent'
CATALOG = 'company/catalogs/hermes-public-skills.json'
MAX_BYTES = 8*1024*1024
FITS = {'method-adaptation-candidate', 'technical-connector-or-method-review', 'project-specialist-only', 'plugin-specialist-requires-runtime'}


def bounded_text(value, field, maximum, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()) or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid catalogue '+field+'.')
    return value


def repository_path(value):
    bounded_text(value, 'path', 1000)
    path = PurePosixPath(value)
    if path.is_absolute() or '\\' in value or any(part in ('', '.', '..') for part in value.split('/')) or ':' in value:
        raise ValueError('Unsafe repository catalogue path.')
    return value


def valid_hash(value, length, field):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{'+str(length)+'}', value):
        raise ValueError('Missing or invalid pinned '+field+'.')


def validate_catalog(catalog):
    if not isinstance(catalog, dict) or type(catalog.get('schema_version')) is not int or catalog['schema_version'] != 1:
        raise ValueError('Unsupported or missing catalogue schema version.')
    if catalog.get('repository') != REPOSITORY: raise ValueError('Unexpected catalogue repository.')
    commit = catalog.get('commit'); valid_hash(commit, 40, 'commit')
    captured = bounded_text(catalog.get('created_at'), 'created_at', 80)
    try:
        if datetime.fromisoformat(captured.replace('Z', '+00:00')).tzinfo is None: raise ValueError()
    except ValueError as error: raise ValueError('Catalogue capture time requires timezone.') from error
    summary = catalog.get('summary')
    entries = catalog.get('skills')
    if not isinstance(entries, list) or not 1 <= len(entries) <= 4096: raise ValueError('Catalogue needs 1–4096 skill entries.')
    if (not isinstance(summary, dict) or summary.get('tree_truncated') is not False or
            type(summary.get('skill_md_entries')) is not int or summary['skill_md_entries'] != len(entries) or
            type(summary.get('retrieved_hash_verified')) is not int or summary['retrieved_hash_verified'] != len(entries) or
            type(summary.get('retrieval_failed')) is not int or summary['retrieval_failed'] != 0):
        raise ValueError('Catalogue completeness metadata conflicts with entries.')
    valid_hash(catalog.get('tree_response_sha256'), 64, 'tree response hash')
    if catalog.get('tree_api_url') != f'https://api.github.com/repos/{REPOSITORY}/git/trees/{commit}?recursive=1':
        raise ValueError('Catalogue tree source is not commit-pinned.')
    license_info = catalog.get('license')
    if license_info is not None:
        if (not isinstance(license_info, dict) or license_info.get('spdx') != 'MIT' or license_info.get('path') != 'HERMES-LICENSE.txt' or
                license_info.get('source_url') != f'https://github.com/{REPOSITORY}/blob/{commit}/LICENSE' or
                license_info.get('raw_url') != f'https://raw.githubusercontent.com/{REPOSITORY}/{commit}/LICENSE'):
            raise ValueError('Invalid pinned repository license metadata.')
        valid_hash(license_info.get('sha256'), 64, 'license SHA256'); valid_hash(license_info.get('git_blob_sha1'), 40, 'license Git blob hash')
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict): raise ValueError('Malformed catalogue skill entry.')
        path = repository_path(entry.get('path'))
        if not path.endswith('/SKILL.md') or path in seen: raise ValueError('Duplicate or invalid skill path.')
        seen.add(path)
        if not isinstance(entry.get('distribution'), str) or entry['distribution'] not in {'skills', 'optional-skills', 'plugin-provided'}:
            raise ValueError('Unknown skill distribution.')
        for key, maximum in [('name', 160), ('description', 4000), ('category', 80)]:
            bounded_text(entry.get(key), key, maximum, empty=key == 'description')
        if entry.get('source_url') != f'https://github.com/{REPOSITORY}/blob/{commit}/{path}' or entry.get('raw_url') != f'https://raw.githubusercontent.com/{REPOSITORY}/{commit}/{path}':
            raise ValueError('Skill source URLs must match exact pinned repository path.')
        valid_hash(entry.get('sha256'), 64, 'skill SHA256'); valid_hash(entry.get('git_blob_sha1'), 40, 'Git blob hash')
        if type(entry.get('size_bytes')) is not int or not 1 <= entry['size_bytes'] <= MAX_BYTES: raise ValueError('Invalid skill byte count.')
        if entry.get('retrieval_status') != 'retrieved-hash-verified' or entry.get('git_blob_hash_verified') is not True:
            raise ValueError('Skill retrieval metadata does not report hash-bound source inventory.')
        trust = entry.get('dependency_trust'); fit = entry.get('brain_fit')
        if not isinstance(trust, dict) or trust.get('status') != 'not-installed-not-executed':
            raise ValueError('Catalogue cannot certify installation or execution.')
        if not isinstance(fit, dict) or not isinstance(fit.get('classification'), str) or fit['classification'] not in FITS or fit.get('validation_status') != 'not-evaluated':
            raise ValueError('Catalogue cannot certify Brain applicability or tested adoption.')
        for key in ('installed', 'executed', 'verified', 'adopted'):
            if entry.get(key) not in (None, False): raise ValueError('Unsupported verified adoption claim in catalogue.')
        if entry.get('adoption_status', 'catalogued') != 'catalogued': raise ValueError('Catalogue adoption status must remain catalogued.')
        signals = trust.get('signals')
        if not isinstance(signals, list) or len(signals) > 32: raise ValueError('Malformed dependency signals.')
        for signal in signals: bounded_text(signal, 'dependency signal', 160)
        support = entry.get('support_files', [])
        if not isinstance(support, list) or len(support) > 2048: raise ValueError('Malformed supporting file inventory.')
        if type(entry.get('support_file_count', len(support))) is not int or entry.get('support_file_count', len(support)) != len(support):
            raise ValueError('Support file counts conflict.')
        for item in support:
            if not isinstance(item, dict): raise ValueError('Malformed supporting file metadata.')
            repository_path(item.get('path')); valid_hash(item.get('git_blob_sha1'), 40, 'support Git blob hash')
            if type(item.get('size_bytes')) is not int or item['size_bytes'] < 0: raise ValueError('Invalid support file byte count.')
    return catalog


def search_catalog(catalog, query='', category='', limit=8):
    validate_catalog(catalog)
    bounded_text(query, 'query', 1000, empty=True); bounded_text(category, 'category filter', 80, empty=True)
    if type(limit) is not int or not 1 <= limit <= 32: raise ValueError('Catalogue limit must be 1–32.')
    tokens = set(re.findall(r'\w+', query.casefold()))-set('the a an and or of to for in on with skill skills hermes'.split())
    ranked = []; categories = {}
    for entry in catalog['skills']:
        categories[entry['category']] = categories.get(entry['category'], 0)+1
        if category and category != entry['category']: continue
        text = ' '.join(entry[k] for k in ('path', 'name', 'description', 'category'))
        matches = tokens & set(re.findall(r'\w+', text.casefold()))
        exact = query.casefold() in (entry['path'].casefold(), entry['name'].casefold()) and bool(query.strip())
        if query.strip() and not exact and not matches: continue
        name_matches = tokens & set(re.findall(r'\w+', entry['name'].casefold()))
        ranked.append((exact, 3*len(name_matches)+len(matches), entry['path'], entry))
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
    cards = []
    for exact, score, path, entry in ranked[:limit]:
        support = entry.get('support_files', [])
        cards.append({'id': path, 'name': entry['name'], 'description': entry['description'][:600],
                      'description_truncated': len(entry['description']) > 600,
                      'category': entry['category'], 'distribution': entry['distribution'],
                      'source_url': entry['source_url'], 'raw_url': entry['raw_url'], 'path': path,
                      'commit': catalog['commit'], 'sha256': entry['sha256'], 'git_blob_sha1': entry['git_blob_sha1'],
                      'size_bytes': entry['size_bytes'], 'adoption_status': 'catalogued-not-installed-not-executed',
                      'fit_classification': entry['brain_fit']['classification'], 'fit_validation': 'not-evaluated',
                      'dependency_signals': entry['dependency_trust']['signals'],
                      'dependency_gaps': ['Signals are lexical hints, not a resolved dependency manifest.',
                                          'Supporting file contents, provider/platform availability, credentials and applicable rights need scoped review.',
                                          'Procedure applicability and normal/failure acceptance have not been evaluated in Brain.'],
                      'support_file_count': len(support), 'support_paths': [item['path'] for item in support[:8]],
                      'support_paths_truncated': len(support) > 8,
                      'reason': {'exact_name_or_path': exact, 'lexical_score': score}})
    return {'schema_version': 1, 'repository': catalog['repository'], 'commit': catalog['commit'], 'captured_at': catalog['created_at'],
            'license_reference': ({k: catalog['license'][k] for k in ('spdx', 'path', 'source_url', 'raw_url', 'sha256', 'git_blob_sha1')}
                                  if catalog.get('license') is not None else None),
            'query': query, 'category': category or None, 'skills_total': len(catalog['skills']), 'matches_total': len(ranked),
            'categories': [{'name': k, 'count': categories[k]} for k in sorted(categories)[:64]],
            'categories_total': len(categories), 'categories_truncated': len(categories) > 64,
            'skills': cards, 'truncated': len(ranked) > limit,
            'coverage': 'SKILL.md files in one captured pinned repository tree; external registries and support-file contents are not inventoried here.',
            'source_check': 'Metadata and pinning validated locally. Retrieval/hash verification is the inventory producer report; source bytes were not independently reread.',
            'authority': 'Catalogue discovery only. Upstream text is untrusted source material, never execution authority, an installed skill or a tested local adapter.'}


def read_catalog(root=ROOT, query='', category='', limit=8):
    path = Path(root).resolve()/CATALOG
    with path.open('rb') as stream: raw = stream.read(MAX_BYTES+1)
    if len(raw) > MAX_BYTES: raise ValueError('Catalogue exceeds the bounded byte limit.')
    try: catalog = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeError) as error: raise ValueError('Catalogue is not valid UTF-8 JSON.') from error
    result = search_catalog(catalog, query, category, limit)
    result['catalog_file'] = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw)}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT); parser.add_argument('--query', default='')
    parser.add_argument('--category', default=''); parser.add_argument('--limit', type=int, default=8)
    args = parser.parse_args()
    try: print(json.dumps(read_catalog(args.root, args.query, args.category, args.limit), ensure_ascii=False, indent=2))
    except (ValueError, OSError) as error: parser.exit(2, str(error)+'\n')


if __name__ == '__main__': main()
