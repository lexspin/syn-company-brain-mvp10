"""Read-only skill curation hints; never remove, merge or promote procedures."""
import hashlib
from itertools import islice
from pathlib import Path
import re

ID = re.compile(r'[a-z0-9][a-z0-9-]{0,63}\Z')
GATE = ['Bind current skill/source versions and owner scope.',
        'Review applicability and differences; identical text alone does not establish interchangeable roles.',
        'Verify a retained replacement against representative normal/failure cases and every affected consumer.',
        'Preserve predecessor instructions, references and a checked rollback path.',
        'Use a separately authorized expected-version change; this command makes no changes.']


def curate(state, activity=(), histories=None, project_id='', limit=8, telemetry_truncated=False, query=''):
    if not isinstance(query, str) or len(query) > 1000: raise ValueError('Curation query must contain at most 1000 characters.')
    if not isinstance(project_id, str) or (project_id and not ID.fullmatch(project_id)):
        raise ValueError('Invalid registered project ID.')
    if type(limit) is not int or not 1 <= limit <= 32: raise ValueError('Curation limit must be 1–32.')
    rows = {r['kind']+':'+r['id']: r for r in state['objects']}
    project_ref = 'project:'+project_id
    project = rows.get(project_ref) if project_id else None
    if project_id and (project is None or project['archived']):
        raise ValueError('The selected project is not active in the published state.')
    skills = [r for r in rows.values() if r['kind'] == 'skill' and not r['archived']]
    groups = {}
    for skill in skills:
        body = skill['data'].get('instructions', '')
        if isinstance(body, str) and body.strip():
            groups.setdefault(hashlib.sha256(body.encode('utf-8')).hexdigest(), []).append('skill:'+skill['id'])
    histories = histories or {}; cards = []
    for skill in skills:
        ref = 'skill:'+skill['id']; data = skill['data']
        if project and ref not in project['data'].get('refs', []) and project_ref not in data.get('refs', []):
            continue
        body = data.get('instructions', '')
        body = body if isinstance(body, str) else ''
        sha = hashlib.sha256(body.encode('utf-8')).hexdigest()
        peers = sorted(r for r in groups.get(sha, []) if r != ref)
        protection = []; consumers = []
        for other in rows.values():
            if other['archived'] or other['kind'] != 'loop': continue
            d = other['data']; execution = d.get('execution', {})
            step_consumer = any(isinstance(step, dict) and step.get('skill') == skill['id'] for step in d.get('steps', []))
            if ref in d.get('refs', []) or execution.get('skill_id') == skill['id'] or d.get('skill_id') == skill['id'] or step_consumer:
                consumers.append({'ref': 'loop:'+other['id'], 'version': other['version']})
        if consumers: protection.append('Referenced by a nonarchived workflow; preserve its consumers.')
        for field in ('pinned', 'canonical', 'owner_directed', 'owner_direction'):
            if data.get(field): protection.append('Explicit '+field+' metadata requires owner-scoped review.')
        active = []; read_events = set(); execution_events = set(); observed_edges = set()
        native_path = (Path.home()/'.codex/skills'/skill['id']/'SKILL.md').as_posix().casefold()
        for task in activity:
            tid = task['task_id']
            endpoints = {edge.get(k) for edge in task.get('edges', []) for k in ('source', 'target')}
            task_reads = {str(read.get('reference', '')).replace('\\', '/').casefold() for read in task.get('reads', [])}
            if task.get('status') == 'running' and (ref in task.get('area_refs', []) or ref in endpoints or ref.casefold() in task_reads or native_path in task_reads):
                active.append(tid)
            history = histories.get(tid, {})
            if history.get('truncated'): telemetry_truncated = True
            for event in history.get('events', []):
                eid = event['event_id']
                for read in event.get('reads', []):
                    pointer = str(read.get('reference', '')).replace('\\', '/').casefold()
                    if pointer in (ref.casefold(), native_path): read_events.add(eid)
                for edge in event.get('edges', []):
                    if edge.get('observation') != 'observed' or ref not in (edge.get('source'), edge.get('target')): continue
                    observed_edges.add(eid)
                    if edge.get('relation') in {'executes', 'executed', 'invokes', 'invoked', 'runs'}:
                        execution_events.add(eid)
        if active: protection.append('Selected by currently running explicitly reported work.')
        versions = data.get('source_versions', {})
        bindings = {('memory:'+k if ':' not in k else k): v for k, v in versions.items()} if isinstance(versions, dict) else {}
        if isinstance(data.get('source_bindings'), dict): bindings.update(data['source_bindings'])
        for source_ref in data.get('refs', []):
            if isinstance(source_ref, str) and source_ref.startswith('memory:'): bindings.setdefault(source_ref, None)
        sources = []; drift = []; source_notes = []
        for source_id, version in islice(bindings.items(), 32):
            source_ref = source_id if ':' in source_id else 'memory:'+source_id
            source = rows.get(source_ref)
            reason = ''
            if source is None: reason = 'missing'
            elif source['archived']: reason = 'archived'
            elif version is not None and source['version'] != version: reason = 'version changed'
            elif source['kind'] == 'memory' and not state.get('memory_freshness', {}).get(source['id'], {}).get('current'): reason = 'not current accepted evidence'
            sources.append({'ref': source_ref[:160], 'version': version if type(version) is int else None,
                            'current_version': source['version'] if source else None, 'version_bound': version is not None,
                            'drift': (reason or None) if version is not None else None,
                            'linked_source_status': (reason or None) if version is None else None})
            if reason:
                (drift if version is not None else source_notes).append(source_ref[:160]+': '+reason)
        if len(bindings) > 32: source_notes.append('Source pointers truncated; remaining dependencies not reviewed.')
        recommendation = 'review-overlap' if peers else 'review-source-drift' if drift else 'review-source-context' if source_notes else 'retain'
        cards.append({'ref': ref, 'version': skill['version'], 'name': str(data.get('name', skill['id']))[:160],
                      'instruction_sha256': sha, 'recommendation': recommendation,
                      'identical_body_peers': [{'ref': peer, 'version': rows[peer]['version']} for peer in peers[:32]],
                      'peers_total': len(peers), 'peers_truncated': len(peers) > 32,
                      'protection': protection, 'workflow_consumers': consumers[:32], 'consumers_total': len(consumers),
                      'active_tasks': active[:32], 'active_tasks_total': len(active),
                      'sources': sources, 'sources_total': len(bindings), 'source_drift': drift, 'source_review_notes': source_notes,
                      'usage': {'source_read_events': len(read_events), 'observed_relationship_events': len(observed_edges),
                                'reported_execution_events': len(execution_events),
                                'meaning': 'Public caller reports in a bounded telemetry window; reads and catalog relationships are not execution proof.'},
                      'review_gate': GATE,
                      'retention_reason': 'Keep usable or ambiguous methods. Age and absent observed use never authorize deletion or archival.'})
    cards.sort(key=lambda c: (c['recommendation'] == 'retain', c['ref']))
    tokens = set(re.findall(r'\w+', query.casefold()))-set('the a an and or of to for in on with company brain skill memory project loop'.split())
    ranked = []
    for card in cards:
        data = rows[card['ref']]['data']
        text = ' '.join(str(data.get(k, ''))[:20000] for k in ('name', 'description', 'scope', 'instructions'))+' '+card['ref']
        matched = len(tokens & set(re.findall(r'\w+', text.casefold())))
        exact = bool(re.search(r'(?<![\w-])'+re.escape(card['ref'])+r'(?![\w-])', query, re.I))
        if query.strip() and not exact and not matched: continue
        ranked.append((exact, matched, card))
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]['recommendation'] == 'retain', item[2]['ref']))
    return {'project': project_id or None, 'query': query, 'publication': state.get('_view', {}),
            'skills_total': len(skills), 'scoped_skills_total': len(cards),
            'recommendation_counts': {k: sum(c['recommendation'] == k for c in cards) for k in ('review-overlap', 'review-source-drift', 'review-source-context', 'retain')},
            'query_matches_total': len(ranked), 'recommendations': [item[2] for item in ranked[:limit]], 'truncated': len(ranked) > limit,
            'telemetry': {'tasks_inspected': len(activity), 'truncated_or_at_bound': telemetry_truncated,
                          'coverage': 'Only explicitly instrumented tasks and bounded retained event history; unreported use remains unknown.'},
            'authority': 'Read-only review recommendations. No merge, archive, deletion, promotion or new execution is authorized.'}


def read_curation(root, state, project_id='', limit=8, query=''):
    from native_activity import read_activity, read_events
    tasks = read_activity(root, limit=128)
    histories = {task['task_id']: read_events(root, task['task_id'], limit=32) for task in tasks}
    return curate(state, tasks, histories, project_id, limit, telemetry_truncated=len(tasks) == 128, query=query)
