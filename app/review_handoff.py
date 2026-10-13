"""Explicit accepted archive -> new connected review; never retroactive completion."""
import argparse
import hashlib
import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError

from change_events import record_binding
from completion_check import command_receipt, same_record
from operating_policy import interpret, require_allowed
from routed_execution import PublishedClient

ROOT = Path('C:/Users/USER/OneDrive/SYN Company Brain/V2')
LOOP = 'connected-change-review'
IMPACT_KINDS = {'workflow-change', 'source-change', 'new-research', 'owner-correction'}
ID = re.compile(r'[a-z0-9][a-z0-9-]{0,63}\Z')
REVIEW_SKILLS = frozenset({'company-brain-prompt-review', 'company-brain-system-review',
                          'company-brain-interface-audit', 'company-brain-self-improvement',
                          'company-brain-dreaming'})


def fingerprint(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def preparation(client, *, source_id, source_version, content_sha256,
                archive_receipt, source_chat, project_id, scope, impact_kind, root=ROOT):
    """Read exact current evidence and return a bounded candidate save payload."""
    root = Path(root).resolve()
    if not isinstance(impact_kind, str) or impact_kind not in IMPACT_KINDS:
        raise ValueError('Declare a relevant source-impact category; pure checks are excluded.')
    for value in (source_id, project_id):
        if not isinstance(value, str) or not ID.fullmatch(value):
            raise ValueError('Exact source and project IDs are required.')
    if type(source_version) is not int or source_version < 1:
        raise ValueError('Exact positive source version required.')
    if not isinstance(content_sha256, str) or not re.fullmatch(r'[a-f0-9]{64}', content_sha256):
        raise ValueError('Exact UTF-8 content SHA256 required.')
    for value in (scope, source_chat):
        if not isinstance(value, str) or not value.strip() or len(value) > 2000 or any(ord(c) < 32 for c in value):
            raise ValueError('Bounded nonempty scope and actual source chat required.')
    state = client.state()
    if Path(state.get('root', '')).resolve() != root:
        raise ValueError('Publication belongs to another workspace.')
    try:
        view = state['_view']
        age = (datetime.now(timezone.utc)-datetime.fromisoformat(view['asof'])).total_seconds()
        if view.get('stale') or not -5 <= age <= 30:
            raise ValueError('Publication is stale or future-dated.')
    except (KeyError, TypeError) as error:
        raise ValueError('Fresh publication identity required.') from error
    require_allowed(interpret(next((r for r in state['objects'] if r['kind'] == 'stack' and r['id'] == 'operating-policy'), None), previously_configured=True), 'routine')
    rows = {r['kind']+':'+r['id']: r for r in state['objects']}
    source = rows.get('memory:'+source_id)
    if (not source or source.get('archived') or source['version'] != source_version or
            source['data'].get('status') != 'accepted' or
            source['data'].get('type') == 'native-work-request' or
            not state.get('memory_freshness', {}).get(source_id, {}).get('current')):
        raise ValueError('Source must be the exact current accepted archive.')
    # Structured provenance only: no classification from names or source prose.
    for ref in source['data'].get('refs', []):
        linked = rows.get(ref)
        if linked and linked['kind'] == 'memory' and linked['data'].get('type') == 'native-work-request':
            linked = rows.get('loop:'+str(linked['data'].get('loop_id')))
        if linked and linked['kind'] == 'loop' and (linked['id'] == LOOP or linked['data'].get('execution', {}).get('skill_id') in REVIEW_SKILLS):
            raise ValueError('Reviewer-generated source is excluded from passive handoff; avoid self-churn.')
    content = source['data'].get('content')
    if not isinstance(content, str) or not 1 <= len(content) <= 100000 or fingerprint(content) != content_sha256:
        raise ValueError('Source content fingerprint mismatch.')
    request, durable = command_receipt(root, archive_receipt)
    returned = client.receipt(archive_receipt)
    if (durable != returned or request['action'] != 'archive-research' or
            returned.get('id') != archive_receipt or not same_record(source, returned.get('result', {})) or
            not returned['result'].get('capture_status')):
        raise ValueError('Completed archive receipt does not own this exact source.')
    provenance = source['data'].get('capture', {}).get('provenance', {})
    payload = request.get('payload', {})
    if (provenance.get('chat_id') != source_chat or payload.get('provenance', {}).get('chat_id') != source_chat or
            payload.get('content') != content or payload.get('project_id') != project_id):
        raise ValueError('Archive request source/chat/project ownership mismatch.')
    project = rows.get('project:'+project_id)
    loop = rows.get('loop:'+LOOP)
    if (not project or project.get('archived') or not loop or loop.get('archived') or
            not loop['data'].get('execution') or 'project:'+project_id not in source['data'].get('refs', []) or
            'memory:'+source_id not in project['data'].get('refs', [])):
        raise ValueError('Active project/workflow and reciprocal archive links required.')
    review_skill = loop['data']['execution'].get('skill_id')
    skill = rows.get('skill:'+str(review_skill))
    if not skill or skill.get('archived'):
        raise ValueError('Existing workflow executor skill is unavailable.')
    sources = {'memory:'+source_id: record_binding(source), 'skill:'+review_skill: record_binding(skill)}
    context = {'schema_version': 1, 'source_ref': 'memory:'+source_id, 'source_version': source_version,
               'content_sha256': content_sha256, 'archive_receipt': archive_receipt,
               'source_chat': source_chat, 'project_ref': 'project:'+project_id,
               'project_root': project['data']['path'], 'scope': scope, 'impact_kind': impact_kind,
               'loop_version': loop['version'], 'change_sources': sources,
               'acceptance': 'Read this exact archived source and its relevant current consumers. Retain a NEW checked review result after the actual claim, linked to source memory, project, request and workflow. Preserve source text. Record useful learning as a candidate only after receipt-bound completion; do not replay original work or infer approval.'}
    encoded = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    ident = 'handoff-'+fingerprint(encoded)[:32]
    inspected = 0
    # Ownership survives procedure/scope drift: a new hash is not a new licence
    # to repeat the same source review while its original owner is unresolved.
    for row in state['objects']:
        if row['kind'] != 'memory' or row['data'].get('type') != 'native-work-request' or not row['id'].startswith('handoff-'):
            continue
        inspected += 1
        if inspected > 128:
            raise ValueError('Handoff ownership inventory exceeds bound; reconcile before queueing.')
        try: previous = json.loads(row['data'].get('request_input', ''))
        except (ValueError, TypeError): continue
        if not isinstance(previous, dict): continue
        identity_fields = ('source_ref', 'source_version', 'content_sha256', 'archive_receipt', 'project_ref')
        if all(previous.get(k) == context[k] for k in identity_fields) and row['data'].get('request_state') in {'queued', 'running', 'uncertain', 'pending'}:
            return {'request_id': row['id'], 'existing': {'version': row['version'], 'state': row['data']['request_state']}, 'context': previous}
    data = {'name': 'Review accepted native result', 'type': 'native-work-request', 'status': 'candidate',
            'request_state': 'queued', 'source': 'Explicit accepted-result review handoff; source remains unchanged.',
            'content': 'New review of an accepted archive; not completion of the originating task.',
            'request_input': encoded, 'loop_id': LOOP, 'loop_version': loop['version'],
            'refs': ['loop:'+LOOP, 'project:'+project_id, 'memory:'+source_id, 'skill:'+review_skill],
            'source_versions': {source_id: source_version}, 'change_sources': sources, 'change_event_id': ident}
    existing = rows.get('memory:'+ident)
    if existing:
        immutable = ('request_input', 'loop_id', 'loop_version', 'change_sources', 'change_event_id', 'source_versions')
        if existing.get('archived') or any(existing['data'].get(k) != data[k] for k in immutable):
            raise ValueError('Existing handoff identity conflicts; reconcile without replay.')
        return {'request_id': ident, 'existing': {'version': existing['version'], 'state': existing['data'].get('request_state')}, 'context': context}
    return {'request_id': ident, 'save_payload': {'kind': 'memory', 'id': ident, 'version': 0, 'data': data}, 'context': context}


def queue_handoff(reader, writer, **bindings):
    """Explicit write only: reconcile original deterministic save before sending."""
    prepared = preparation(reader, **bindings)
    if 'existing' in prepared:
        return prepared
    payload = prepared['save_payload']
    # Client.command uses this exact stable ID. A pending/uncertain receipt is
    # returned for reconciliation, never resubmitted under a new identity.
    # Use the Client's established algorithm rather than guessing its encoding.
    module = _archive_module()
    identity = module.stable_id('save', payload)
    try:
        receipt = writer.receipt(identity)
    except HTTPError as error:
        if error.code != 404:
            raise
        error.close()
        refreshed = preparation(reader, **bindings)
        if refreshed != prepared:
            raise ValueError('Handoff changed before queue submission; reprepare.')
        receipt = writer.command('save', payload)
    if not isinstance(receipt, dict) or receipt.get('id') != identity or receipt.get('action') != 'save':
        raise ValueError('Handoff save receipt identity mismatch; reconcile.')
    if receipt.get('state') == 'completed':
        result = receipt.get('result', {})
        if not receipt.get('ok') or result.get('kind') != 'memory' or result.get('id') != prepared['request_id'] or result.get('version') != 1 or result.get('data') != payload['data']:
            raise ValueError('Handoff receipt differs from exact queued save; reconcile.')
    return {**prepared, 'queue_receipt': receipt}


def _archive_module():
    path = Path.home()/'.codex/skills/company-brain-archive-research/scripts/archive_research.py'
    spec = importlib.util.spec_from_file_location('_review_handoff_archive_client', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ('source-id', 'content-sha256', 'archive-receipt', 'source-chat', 'project-id', 'scope'):
        p.add_argument('--'+flag, required=True)
    p.add_argument('--source-version', required=True, type=int)
    p.add_argument('--impact-kind', required=True, choices=sorted(IMPACT_KINDS))
    p.add_argument('--queue', action='store_true')
    args = vars(p.parse_args()); queue = args.pop('queue')
    reader = PublishedClient()
    result = queue_handoff(reader, _archive_module().Client(), **args) if queue else preparation(reader, **args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
