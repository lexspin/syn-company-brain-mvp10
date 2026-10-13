"""Bounded read-only activity projection. Never constructs a Brain or reads chats."""
from __future__ import annotations

import json
import re
import sqlite3
import types
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit

MAX_TASKS = 512
MAX_RECORDS = 12000
MAX_NODES = 24
MAX_EDGES = 32
MAX_OUTPUTS = 16
MAX_HISTORY = 100
RUN_LEASE_SECONDS = 300
IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}\Z")
KINDS = {'agent', 'skill', 'memory', 'loop', 'stack', 'project'}
STATUSES = {'queued', 'running', 'completed', 'failed', 'cancelled', 'interrupted', 'cancelling', 'unknown'}


def _id(value):
    return value if isinstance(value, str) and IDENT.fullmatch(value) else ''


def _label(value, fallback):
    return ' '.join(value.split())[:160] if isinstance(value, str) and value.strip() else fallback


def _failure(value):
    return ' '.join(value.split())[:600] if isinstance(value, str) and value.strip() else None


def _status_note(status):
    return {
        'failed': 'Recorded failure; inspect its evidence for the cause and any follow-up.',
        'unknown': 'Current execution is unconfirmed because the observation is stale, unavailable or unrecognized.',
        'queued': 'Recorded request is waiting; execution has not been observed.',
        'running': 'Running according to recent attributable activity evidence.',
        'completed': 'Recorded completion; this does not establish owner acceptance or resolution of earlier failures.',
        'cancelled': 'Recorded cancellation.',
        'interrupted': 'Recorded interruption; resumption has not been observed.',
        'cancelling': 'Cancellation was requested; its completion has not been observed.',
    }.get(status, 'Execution status is unconfirmed.')


def _dict(value):
    return value if isinstance(value, dict) else {}


def _list(value):
    return value if isinstance(value, list) else []


def _date(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def _old(value, now, seconds):
    date = _date(value)
    return date is None or (now - date).total_seconds() > seconds or (date - now).total_seconds() > 60


def _read(root, name, limit):
    path = root / 'data' / (name + '.json')
    if not path.resolve().is_relative_to(root):
        raise ValueError('Publication escaped source root')
    with path.open('rb') as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Publication exceeds read bound')
    value = json.loads(raw)
    if not isinstance(value, dict) or not isinstance(value.get('_view'), dict):
        raise ValueError('Missing publication metadata')
    return value


def _status(value, updated, now, stale):
    state = value if value in STATUSES else 'unknown'
    if state in {'running', 'cancelling'} and (stale or _old(updated, now, RUN_LEASE_SECONDS)):
        return 'unknown'
    return state


def _record_url(ref):
    if not isinstance(ref, str) or ':' not in ref:
        return ''
    kind, ident = ref.split(':', 1)
    if kind not in KINDS or not _id(ident):
        return ''
    return '/api/file?' + urlencode({'path': 'record/' + ref})


def _reads(items, records=None):
    """Only explicit public source pointers; never source contents or prompts."""
    result = []
    for item in _list(items)[:32]:
        item = _dict(item)
        ref = item.get('reference')
        if not isinstance(ref, str) or not ref or len(ref) > 1000 or any(ord(c) < 32 for c in ref):
            continue
        try:
            parsed = urlsplit(ref)
            unsafe = parsed.scheme.lower() in {'javascript', 'data', 'vbscript'} or parsed.username or parsed.password
        except ValueError:
            continue
        if unsafe:
            continue
        url = _record_url(ref) if records and ref in records else ''
        if parsed.scheme in {'https', 'http'} and parsed.netloc:
            url = ref
        result.append(dict(label=_label(item.get('label'), 'Inspected source'), reference=ref,
                           version=_label(item.get('version'), ''), url=url))
    return result


def _output(item, records=None):
    """Project explicit pointers and metadata only; never classify by extension."""
    item = _dict(item)
    ref = item.get('reference')
    if not isinstance(ref, str) or not ref or len(ref) > 1000 or any(ord(c) < 32 for c in ref):
        return None
    try:
        parsed = urlsplit(ref)
        if parsed.scheme.lower() in {'javascript', 'data', 'vbscript'} or parsed.username or parsed.password:
            return None
    except ValueError:
        return None
    url = _record_url(ref) if records and ref in records else ''
    if parsed.scheme.lower() in {'https', 'http'} and parsed.netloc:
        url = ref
    result = dict(label=_label(item.get('label'), 'Recorded output'), reference=ref, url=url)
    for field, values in [('kind', {'file', 'document', 'code', 'skill', 'agent', 'connection', 'trigger'}),
                          ('action', {'created', 'updated', 'read'})]:
        if isinstance(item.get(field), str) and item[field] in values:
            result[field] = item[field]
    for field, limit in [('version', 160), ('summary', 300)]:
        value = item.get(field)
        if isinstance(value, str) and value.strip() and len(value) <= limit and not any(ord(c) < 32 for c in value):
            result[field] = value
    start, end = item.get('start_line'), item.get('end_line')
    if type(start) is int and 1 <= start <= 1000000:
        if end is None or type(end) is int and start <= end <= 1000000:
            result['start_line'] = start
            if end is not None:
                result['end_line'] = end
    return result


class _Task:
    def __init__(self, ident, label, status, updated, evidence, records, coverage):
        self.value = dict(id=ident, label=label, status=status, updated=updated if _date(updated) else None,
                          agent_id=None, project_id=None, nodes=[], edges=[], outputs=[], evidence_url=evidence)
        self.value.update(observed_at=self.value['updated'], source=ident.split(':', 1)[0], evidence_id=ident)
        self.value.update(failure_reason=None, status_note=_status_note(status))
        self.records, self.coverage = records, coverage
        self.node(ident, label, 'task')

    def node(self, ident, label, kind):
        nodes = self.value['nodes']
        if not any(n['id'] == ident for n in nodes) and len(nodes) < MAX_NODES:
            nodes.append(dict(id=ident, label=label, kind=kind, usage='observed' if kind == 'task' else 'context', active=False))

    def ref(self, ref):
        if not _id(ref) or (':' in ref and not ref.split(':', 1)[1]):
            return False
        row = self.records.get(ref)
        if row is None:
            self.coverage.add('Some explicit references are unresolved; their activity and links are not inferred.')
            return False
        self.node(ref, _label(row.get('display_name') or _dict(row.get('data')).get('name'), ref), row['kind'])
        return any(n['id'] == ref for n in self.value['nodes'])

    def link(self, source, target, label, animate=False):
        known = {n['id'] for n in self.value['nodes']}
        edge = dict(source=source, target=target, label=label, evidence_id=self.value['evidence_id'], animate=animate)
        if source in known and target in known and edge not in self.value['edges'] and len(self.value['edges']) < MAX_EDGES:
            self.value['edges'].append(edge)
            return edge
        return None

    def owner(self, kind, ident, relation):
        if not _id(ident):
            return
        ref = kind + ':' + ident
        if self.ref(ref):
            self.value[kind + '_id'] = ident
            if kind == 'agent':
                for node in self.value['nodes']:
                    if node['id'] == ref:
                        node['usage'] = 'observed'
            self.link(self.value['id'], ref, relation)


def _native_reader(root):
    """Load only the explicitly implemented metadata reader, with no pycache writes."""
    path = root / 'app/native_activity.py'
    if not path.is_file():
        return None
    if not path.resolve().is_relative_to(root) or path.stat().st_size > 256 * 1024:
        raise ValueError('Invalid native activity reader')
    module = types.ModuleType('_company_brain_native_activity_reader')
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def _native_rows(root):
    module = _native_reader(root)
    return module.read_activity(root) if module is not None else None


def event_history(source_root, task_id):
    """Return at most 100 authentic native events in their recorded commit order.

    This is history, never effect replay or an inferred execution graph. IDs are
    raw reporter task IDs. Summary/provenance are explicit public event metadata;
    no private message, prompt, raw receipt or arbitrary event payload is returned.
    """
    if not _id(task_id):
        raise ValueError('Invalid native task identity.')
    root = Path(source_root).resolve()
    if (root / 'V2/app').is_dir():
        root = (root / 'V2').resolve()
    result = dict(task_id=task_id, events=[], truncated=False, coverage=[])
    try:
        module = _native_reader(root)
        if module is None:
            result['coverage'].append('Explicit native event history reader is unavailable.')
            return result
        history = module.read_events(root, task_id, limit=MAX_HISTORY)
        events = _list(_dict(history).get('events'))
        result['truncated'] = bool(_dict(history).get('truncated')) or len(events) > MAX_HISTORY
        for raw in events[-MAX_HISTORY:]:
            raw = _dict(raw)
            if not _id(raw.get('event_id')) or not _date(raw.get('at')) or raw.get('type') not in {
                    'started', 'heartbeat', 'step', 'output', 'completed', 'failed'}:
                result['coverage'].append('Malformed event omitted; history coverage is incomplete.')
                continue
            event = dict(event_id=raw['event_id'], type=raw['type'], at=raw['at'], edges=[], outputs=[],
                         area_refs=[ref for ref in _list(raw.get('area_refs'))[:32] if _id(ref)],
                         reads=_reads(raw.get('reads')),
                         summary=_failure(raw.get('summary')) or '',
                         provenance=(_failure(raw.get('provenance')) or '')[:300])
            for edge in _list(raw.get('edges'))[:64]:
                edge = _dict(edge)
                if _id(edge.get('source')) and _id(edge.get('target')):
                    event['edges'].append(dict(source=edge['source'], target=edge['target'],
                        relation=_label(edge.get('relation'), 'explicit event'),
                        observation=edge.get('observation', 'observed') if edge.get('observation', 'observed') in {'observed', 'planned', 'dependency'} else 'unverified',
                        provenance=(_failure(edge.get('provenance')) or '')[:300]))
            for output in _list(raw.get('outputs'))[:MAX_OUTPUTS]:
                projected = _output(output)
                if projected is not None:
                    event['outputs'].append(projected)
            result['events'].append(event)
        result['coverage'] = sorted(set(result['coverage']))
    except (OSError, ValueError, TypeError, AttributeError, RuntimeError, sqlite3.Error):
        result['coverage'].append('Explicit native event history is unavailable or invalid; no execution is inferred.')
    return result


def activity_view(source_root):
    """Return safe task metadata from canonical publications and explicit native events.

    ``source_root`` may be V2 or its parent workspace. Publication mismatch makes
    backend running claims unknown. Native leases remain independently enforced.
    No queues, database writers, session logs, message bodies or prompt fields are
    used; only whitelisted metadata leaves this function.
    """
    root = Path(source_root).resolve()
    if (root / 'V2/app').is_dir():
        root = (root / 'V2').resolve()
    now = datetime.now(timezone.utc)
    coverage = {'Static registry relationships are context, not execution evidence.',
                'Native chats without explicit activity events are not covered; no host session logs are scraped.'}
    views, freshness = {}, {}
    for name, bound in [('state', 8 * 1024 * 1024), ('details', 24 * 1024 * 1024)]:
        try:
            views[name] = _read(root, name, bound)
            meta = views[name]['_view']
            threshold = meta.get('stale_after_seconds', 30)
            threshold = min(120, max(1, threshold)) if isinstance(threshold, (int, float)) else 30
            freshness[name] = _old(meta.get('asof'), now, threshold)
        except (OSError, ValueError, UnicodeError, TypeError):
            views[name], freshness[name] = {}, True
            coverage.add(name.capitalize() + ' publication unavailable, invalid or over its size bound.')
    state, details = views['state'], views['details']
    if state.get('root') and (not isinstance(state['root'], str) or Path(state['root']).resolve() != root):
        state, details = {}, {}
        freshness = {'state': True, 'details': True}
        coverage.add('Publication workspace identity mismatch; backend activity omitted.')
    asofs = [v.get('_view', {}).get('asof') for v in (state, details)]
    if asofs[0] != asofs[1]:
        freshness = {'state': True, 'details': True}
        coverage.add('Publication timestamps differ; backend running states are unknown during refresh.')
    records = {}
    objects = _list(state.get('objects'))
    if len(objects) > MAX_RECORDS:
        coverage.add('Record scan capped at 12000.')
    for row in objects[:MAX_RECORDS]:
        if isinstance(row, dict) and row.get('kind') in KINDS and _id(row.get('id')) and not row.get('archived'):
            records[row['kind'] + ':' + row['id']] = row
    tasks = []
    for ref, row in records.items():
        data = _dict(row.get('data'))
        if row['kind'] != 'memory' or data.get('type') != 'native-work-request':
            continue
        updated = row.get('updated')
        task = _Task('request:' + row['id'], _label(data.get('name'), 'Native workflow request'),
                     _status(data.get('request_state'), data.get('claimed_at') or updated, now, freshness['state']),
                     updated, _record_url(ref), records, coverage)
        task.value['evidence_id'] = ref + '@' + str(row.get('version', 'unknown'))
        if task.value['status'] == 'failed':
            reason = _failure(data.get('failure_reason'))
            task.value['failure_reason'] = reason
            if reason:
                task.value['status_note'] = reason
        task.ref(ref)
        loop = 'loop:' + _id(data.get('loop_id'))
        if task.ref(loop):
            task.link(task.value['id'], loop, 'requested workflow')
        # refs are linked context; they never create execution edges.
        for linked in _list(data.get('refs'))[:MAX_NODES]:
            task.ref(linked)
        result = 'memory:' + _id(data.get('result_ref'))
        if task.ref(result):
            task.link(task.value['id'], result, 'recorded result')
            task.value['outputs'].append(dict(label='Recorded result', url=_record_url(result)))
        # claimant is a native chat identity, not a registry agent.
        tasks.append(task.value)
    runs = _dict(details.get('runs'))
    if len(runs) > MAX_RECORDS:
        coverage.add('Run scan capped at 12000.')
    for ident, run in list(runs.items())[:MAX_RECORDS]:
        if not _id(ident) or not isinstance(run, dict):
            continue
        snapshot = _dict(run.get('snapshot'))
        loop = _dict(snapshot.get('loop'))
        task = _Task('run:' + ident, _label(_dict(loop.get('data')).get('name'), 'Backend workflow run'),
                     _status(run.get('state'), run.get('updated'), now, freshness['details']), run.get('updated'),
                     '/api/run?' + urlencode({'id': ident}), records, coverage)
        task.value['evidence_id'] = 'run:' + ident + '@' + str(run.get('updated') or 'unknown')
        ref = 'loop:' + _id(run.get('loop_id'))
        if task.ref(ref):
            task.link(task.value['id'], ref, 'recorded workflow run')
        steps = _list(_dict(loop.get('data')).get('steps'))
        for attempt in _list(run.get('attempts'))[:MAX_RECORDS]:
            attempt = _dict(attempt)
            index = attempt.get('step')
            if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(steps):
                continue
            step = _dict(steps[index])
            # Only an actual recorded attempt establishes this step's use.
            task.owner('agent', step.get('agent'), 'recorded step attempt')
            skill = 'skill:' + _id(step.get('skill'))
            if task.ref(skill):
                for node in task.value['nodes']:
                    if node['id'] == skill:
                        node['usage'] = 'observed'
                task.link(task.value['id'], skill, 'recorded step skill')
        for index, output in enumerate(_list(run.get('outputs'))[:MAX_OUTPUTS]):
            if isinstance(output, dict) and isinstance(output.get('path'), str) and output.get('path'):
                task.value['outputs'].append(dict(label='Saved output ' + str(index + 1),
                    url='/api/artifact?' + urlencode({'run': ident, 'step': index})))
        tasks.append(task.value)
    trace_count = 0
    for session, traces in _dict(details.get('traces')).items():
        if not _id(session):
            continue
        for trace in _list(traces):
            trace_count += 1
            if trace_count > MAX_RECORDS:
                break
            if not isinstance(trace, dict) or not _id(trace.get('id')):
                continue
            ident = trace['id']
            meta = _dict(_dict(details.get('_chat_views')).get(session))
            stale = freshness['details'] if not meta else _old(meta.get('asof'), now, 30)
            task = _Task('trace:' + ident, 'Backend chat turn',
                         _status(trace.get('state'), trace.get('updated'), now, stale), trace.get('updated'),
                         '/api/chat-traces?' + urlencode({'session': session}), records, coverage)
            task.value['evidence_id'] = 'trace:' + ident + '@' + str(trace.get('updated') or 'unknown')
            # Actual execution receipts are required; selection alone is a plan.
            if _list(trace.get('execution')) or _list(trace.get('attempts')):
                task.owner('agent', trace.get('selected_agent'), 'recorded chat attempt')
            contract = _dict(trace.get('contract'))
            task.owner('project', contract.get('project_id'), 'bound project')
            tasks.append(task.value)
        if trace_count > MAX_RECORDS:
            coverage.add('Trace scan capped at 12000.')
            break
    try:
        native = _native_rows(root)
        if native is None:
            coverage.add('Explicit native event reader is unavailable.')
        else:
            coverage.add('Explicit native activity events are covered; expired leases are unknown.')
            for row in _list(native)[:MAX_TASKS]:
                if not isinstance(row, dict) or not _id(row.get('task_id')):
                    continue
                ident = row['task_id']
                status = row.get('status')
                expiry = _date(row.get('lease_expires_at'))
                if status == 'stale' or (status == 'running' and (expiry is None or expiry <= now)):
                    status = 'unknown'
                task = _Task('native:' + ident, _label(row.get('title'), 'Native chat task'),
                             status if status in STATUSES else 'unknown', row.get('updated_at'),
                             '/api/native-activity?' + urlencode({'task_id': ident}), records, coverage)
                task.value['summary'] = _label(row.get('public_summary'), '')[:600]
                task.value['event_summary'] = _label(row.get('last_event_public_summary'), '')[:600]
                task.value['evidence_id'] = _id(row.get('last_event_id')) or ('native:' + ident + '@unknown')
                task.value['last_event_type'] = _label(row.get('last_event_type'), 'unknown')
                task.value['parent_task_id'] = 'native:' + row['parent_task_id'] if _id(row.get('parent_task_id')) and row['parent_task_id'] != ident else None
                task.value['model'] = _label(row.get('model'), '')
                task.value['reasoning_effort'] = _label(row.get('reasoning_effort'), '')
                task.value['reads'] = _reads(row.get('reads'), records)
                for ref in _list(row.get('area_refs'))[:MAX_NODES]:
                    task.ref(ref)
                task.owner('agent', row.get('agent_id'), 'explicit agent attribution')
                task.owner('project', row.get('project_id'), 'explicit project attribution')
                for edge in _list(row.get('edges'))[:MAX_EDGES]:
                    edge = _dict(edge)
                    if edge.get('provenance') and task.ref(edge.get('source')) and task.ref(edge.get('target')):
                        latest = _list(row.get('last_event_edges'))
                        observation = edge.get('observation', 'observed')
                        animate = (observation == 'observed' and status == 'running' and edge in latest and
                                   row.get('last_event_type') in {'started', 'step', 'output'})
                        for node in task.value['nodes']:
                            if observation == 'observed' and node['id'] in {edge['source'], edge['target']}:
                                node['usage'] = 'observed'
                                node['active'] = node.get('active', False) or animate
                        projected = task.link(edge['source'], edge['target'], _label(edge.get('relation'), 'explicit event'), animate)
                        if projected is not None:
                            projected['evidence_id'] = _id(row.get('edges_event_id')) or (task.value['evidence_id'] if edge in latest else None)
                            projected['observation'] = observation if observation in {'observed', 'planned', 'dependency'} else 'unverified'
                for output in _list(row.get('outputs'))[:MAX_OUTPUTS]:
                    projected = _output(output, records)
                    if projected is not None:
                        task.value['outputs'].append(projected)
                tasks.append(task.value)
    except (OSError, ValueError, TypeError, AttributeError, RuntimeError, sqlite3.Error):
        coverage.add('Explicit native event reader failed; native activity is unknown.')
    if len(tasks) > MAX_TASKS:
        coverage.add('Activity task list capped at 512; running and queued tasks are prioritized.')
    tasks.sort(key=lambda t: (t['status'] in {'running', 'cancelling', 'queued'}, t['updated'] or '', t['id']), reverse=True)
    valid_dates = [date for date in asofs if _date(date)]
    return dict(asof=min(valid_dates, key=_date) if valid_dates else None,
                stale=any(freshness.values()), tasks=tasks[:MAX_TASKS], coverage=sorted(coverage))
