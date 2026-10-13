"""Bounded discovery of unreviewed procedures from published state; no effects."""
import hashlib
from itertools import islice
import re

ID = re.compile(r'[a-z0-9][a-z0-9-]{0,63}\Z')
STOP = set('the a an and or to of for in on my me please with this that it do make use company brain'.split())


def label(value, limit=160):
    return value[:limit] if isinstance(value, str) else None


def review(state, query='', project_id='', limit=8):
    """Return review hints, never accepted knowledge or promotion eligibility."""
    if not isinstance(query, str) or len(query) > 12000:
        raise ValueError('Review query must contain at most 12000 characters.')
    if not isinstance(project_id, str) or (project_id and not ID.fullmatch(project_id)):
        raise ValueError('Invalid registered project ID.')
    if type(limit) is not int or not 1 <= limit <= 32:
        raise ValueError('Review limit must be 1–32.')
    rows = {r['kind']+':'+r['id']: r for r in state['objects']}
    project_ref = 'project:'+project_id
    project = rows.get(project_ref) if project_id else None
    if project_id and (project is None or project['archived']):
        raise ValueError('The selected project is not active in the published state.')
    tokens = set(re.findall(r'\w+', query.casefold()))-STOP
    ranked = []
    for ref, row in rows.items():
        data = row['data']
        if (row['kind'] != 'memory' or row['archived'] or data.get('status') != 'candidate' or
                data.get('type') not in {'learning-candidate', 'skill-improvement'}):
            continue
        bindings = data.get('source_bindings')
        if not isinstance(bindings, dict):
            versions = data.get('source_versions', {})
            bindings = {'memory:'+k: v for k, v in versions.items()} if isinstance(versions, dict) else {}
        # Only the candidate and explicitly bound source/outcome records may
        # establish scope. A shared target skill or a word match cannot do so.
        scope_refs = [ref, *islice(bindings, 32)]
        outcome = data.get('outcome_request_id')
        if isinstance(outcome, str): scope_refs.append('memory:'+outcome)
        scope_links = []
        if project:
            for linked_ref in scope_refs:
                linked = rows.get(linked_ref)
                if linked_ref in project['data'].get('refs', []) or (linked and project_ref in linked['data'].get('refs', [])):
                    scope_links.append(linked_ref)
            if not scope_links: continue
        body = data.get('proposed_instructions', data.get('content', ''))
        body = body if isinstance(body, str) else ''
        name = str(data.get('name', ''))[:160]
        target = data.get('target')
        if not isinstance(target, dict):
            target = {'kind': 'skill-update', 'id': data.get('skill_id'), 'version': data.get('base_version'),
                      'surface': data.get('target_surface', 'registry-only')}
        title_words = set(re.findall(r'\w+', (row['id']+' '+name).casefold()))
        text = ' '.join(str(v)[:20000] for v in (name, body, data.get('scope', ''), data.get('rationale', ''), target.get('id', '')))
        matches = tokens & set(re.findall(r'\w+', text.casefold()))
        exact = bool(re.search(r'(?<![\w-])(?:memory:)?'+re.escape(row['id'])+r'(?![\w-])', query, re.I))
        if query.strip() and not exact and not matches: continue
        issues = []
        digest = hashlib.sha256(body.encode('utf-8')).hexdigest()
        recorded_hash = data.get('candidate_sha256', data.get('candidate_hash'))
        if not body or recorded_hash != digest or any(data[k] != digest for k in ('candidate_sha256', 'candidate_hash') if k in data):
            issues.append('Candidate instruction hash missing or changed.')
        source_cards = []
        if not bindings: issues.append('Source bindings missing; review provenance before reuse.')
        for source_ref, version in islice(bindings.items(), 32):
            source = rows.get(source_ref)
            reason = ''
            if not isinstance(source_ref, str) or ':' not in source_ref or type(version) is not int or version < 1:
                reason = 'Invalid source binding.'
            elif source is None: reason = 'Source missing.'
            elif source['archived']: reason = 'Source archived.'
            elif source['version'] != version: reason = 'Source version changed.'
            elif source['kind'] == 'memory' and not state.get('memory_freshness', {}).get(source['id'], {}).get('current'):
                reason = 'Source is not current accepted evidence.'
            if reason: issues.append(str(source_ref)[:160]+': '+reason)
            source_cards.append({'ref': label(source_ref), 'version': version if type(version) is int else None, 'current_version': source['version'] if source else None,
                                 'drift': reason or None})
        if len(bindings) > 32: issues.append('Source bindings exceed review bound; remaining bindings not inspected.')
        kind = target.get('kind'); target_id = target.get('id'); baseline = target.get('version')
        target_ref = ('loop:' if kind == 'new-workflow' else 'skill:')+str(target_id)
        current_target = rows.get(target_ref)
        if not isinstance(kind, str) or kind not in {'skill-update', 'new-skill', 'new-workflow'} or not isinstance(target_id, str) or not ID.fullmatch(target_id) or type(baseline) is not int:
            issues.append('Invalid target binding.')
        elif kind == 'skill-update':
            if current_target is None: issues.append('Target skill missing.')
            elif current_target['archived']: issues.append('Target skill archived.')
            elif current_target['version'] != baseline: issues.append('Target skill version changed.')
        elif baseline != 0 or current_target is not None:
            issues.append('New target baseline changed or target already exists.')
        acceptance = data.get('acceptance', {})
        acceptance = acceptance if isinstance(acceptance, dict) else {}
        card = {'id': row['id'], 'version': row['version'], 'name': name, 'type': data['type'],
                'origin': str(data.get('origin', 'unspecified'))[:80], 'status': 'unreviewed-proposal',
                'candidate_sha256': label(recorded_hash), 'instruction_sha256': digest,
                'target': {**{k: label(target.get(k)) for k in ('kind', 'id', 'surface')},
                           'version': baseline if type(baseline) is int else None},
                'target_current_version': current_target['version'] if current_target else None,
                'creation_available': False if kind == 'new-skill' or kind == 'new-workflow' else None,
                'scope': str(data.get('scope', ''))[:1200], 'rationale': str(data.get('rationale', ''))[:1200],
                'instruction_excerpt': body[:1200], 'instructions_truncated': len(body) > 1200,
                'acceptance_descriptions': {k: str(acceptance.get(k, ''))[:1200] for k in ('normal', 'counterexample')},
                'sources': source_cards, 'sources_truncated': len(bindings) > 32,
                'outcome_request_id': label(outcome), 'outcome_receipt': label(data.get('outcome_receipt')),
                'drift': issues, 'scope_links': [label(ref) for ref in scope_links[:32]],
                'reason': {'exact_reference': exact, 'matched_terms': sorted(matches)[:32]}}
        ranked.append((exact, 2*len(tokens & title_words)+len(matches), row['id'], card))
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return {'query': query, 'project': project_id or None, 'publication': state.get('_view', {}),
            'candidates': [item[3] for item in ranked[:limit]], 'truncated': len(ranked) > limit,
            'authority': 'Unreviewed discovery hints only; never accepted recall, execution authority or promotion eligibility.',
            'next': 'Review exact current sources and completion receipts; use the existing procedure test and apply gate. Acceptance descriptions are not executed tests. Native installed hashes and artifacts were not inspected.'}
