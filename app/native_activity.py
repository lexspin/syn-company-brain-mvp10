"""Explicit public native-chat telemetry; independent of Company Brain state."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sqlite3
import sys
import time

TYPES = {'started', 'heartbeat', 'step', 'output', 'completed', 'failed'}
TERMINAL = {'completed', 'failed'}
MAX_INPUT_BYTES = 65536
MAX_RECORD_BYTES = 98304
OUTPUT_KINDS = {'file', 'document', 'code', 'skill', 'agent', 'connection', 'trigger'}
OUTPUT_ACTIONS = {'created', 'updated', 'read'}


def _root(root):
    root = Path(root).resolve()
    return root / 'V2' if (root / 'V2' / 'app').is_dir() else root


def _time(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError('time must include timezone')
    return value.astimezone(timezone.utc)


def _iso(value):
    return value.isoformat(timespec='microseconds').replace('+00:00', 'Z')


def _text(value, name, limit, required=False):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(f'{name} must be a single-line string of at most {limit} characters')
    if required and not value.strip():
        raise ValueError(f'{name} is required')
    return value


def _id(value, name):
    value = _text(value, name, 160, True)
    if not re.fullmatch(r'[A-Za-z0-9_.:/-]+', value):
        raise ValueError(f'{name} contains invalid identifier characters')
    return value


def validate_event(event):
    if not isinstance(event, dict):
        raise ValueError('event must be an object')
    if any(not isinstance(key, str) for key in event):
        raise ValueError('event keys must be strings')
    allowed = {'event_id', 'task_id', 'chat_id', 'type', 'title', 'summary', 'provenance',
               'area_refs', 'edges', 'outputs', 'reads', 'lease_seconds', 'agent_id', 'project_id',
               'parent_task_id', 'model', 'reasoning_effort'}
    if set(event) - allowed:
        raise ValueError('unknown event fields: ' + ', '.join(sorted(set(event) - allowed)))
    result = {k: _id(event.get(k), k) for k in ('event_id', 'task_id', 'chat_id')}
    if not isinstance(event.get('type'), str) or event['type'] not in TYPES:
        raise ValueError('invalid lifecycle type')
    result['type'] = event['type']
    for name in ('parent_task_id', 'model', 'reasoning_effort'):
        if name in event:
            if event['type'] != 'started':
                raise ValueError(f'{name} is immutable start metadata')
            result[name] = _id(event[name], name)
    if result.get('parent_task_id') == result['task_id']:
        raise ValueError('task cannot parent itself')
    for name, limit in [('title', 160), ('summary', 600), ('provenance', 300)]:
        if name in event or event['type'] == 'started' and name in {'title', 'provenance'}:
            result[name] = _text(event.get(name), name, limit, name in {'title', 'provenance'})
    for name in ('agent_id', 'project_id'):
        if name in event:
            result[name] = _id(event[name], name)
    lease = event.get('lease_seconds', 90)
    if isinstance(lease, bool) or not isinstance(lease, int) or not 10 <= lease <= 300:
        raise ValueError('lease_seconds must be an integer from 10 to 300')
    result['lease_seconds'] = lease
    for name, maximum in [('area_refs', 32), ('edges', 64), ('outputs', 16), ('reads', 32)]:
        if name not in event:
            continue
        items = event[name]
        if not isinstance(items, list) or len(items) > maximum:
            raise ValueError(f'{name} must be a list of at most {maximum} entries')
        clean = []
        for item in items:
            if name == 'area_refs':
                clean.append(_id(item, name))
            else:
                fields = {'source': 160, 'target': 160, 'relation': 80, 'provenance': 300} if name == 'edges' else {'label': 160, 'reference': 1000}
                optional = {'observation'} if name == 'edges' else {'version'} if name == 'reads' else {'kind', 'action', 'version', 'summary', 'start_line', 'end_line'}
                if not isinstance(item, dict) or not set(fields) <= set(item) or set(item) - set(fields) - optional:
                    raise ValueError(f'invalid {name} entry')
                entry = {k: _text(item[k], k, n, True) for k, n in fields.items()}
                if name == 'edges':
                    _id(entry['source'], 'source'); _id(entry['target'], 'target')
                    if 'observation' in item:
                        if item['observation'] not in ('observed', 'planned', 'dependency'):
                            raise ValueError('invalid edge observation')
                        entry['observation'] = item['observation']
                if name == 'reads' and 'version' in item:
                    entry['version'] = _text(item['version'], 'version', 160, True)
                if name == 'outputs':
                    for field, values in [('kind', OUTPUT_KINDS), ('action', OUTPUT_ACTIONS)]:
                        if field in item:
                            if not isinstance(item[field], str) or item[field] not in values:
                                raise ValueError('invalid output ' + field)
                            entry[field] = item[field]
                    for field, limit in [('version', 160), ('summary', 300)]:
                        if field in item:
                            entry[field] = _text(item[field], field, limit, True)
                    for field in ('start_line', 'end_line'):
                        if field in item:
                            if type(item[field]) is not int or not 1 <= item[field] <= 1000000:
                                raise ValueError('invalid output line number')
                            entry[field] = item[field]
                    if 'end_line' in item and ('start_line' not in item or item['end_line'] < item['start_line']):
                        raise ValueError('invalid output line range')
                # References are inert labels; neither this reporter nor reader serves files.
                clean.append(entry)
        result[name] = clean
    if len(json.dumps(result).encode('utf-8')) > MAX_INPUT_BYTES:
        raise ValueError('event too large')
    return result


def _connect(root, create=False):
    path = _root(root) / 'runtime' / 'native-activity.sqlite'
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=15, isolation_level=None)
        try:
            connection.execute('PRAGMA busy_timeout=15000')
            # Simultaneous first writers can race the WAL transition: SQLite's
            # busy handler does not cover every journal-mode lock upgrade.
            deadline = time.monotonic() + 15
            while True:
                try:
                    connection.execute('PRAGMA journal_mode=WAL')
                    break
                except sqlite3.OperationalError as error:
                    if 'locked' not in str(error).lower() or time.monotonic() >= deadline:
                        raise
                    time.sleep(0.02)
            connection.execute('CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, received_at TEXT NOT NULL)')
            connection.execute('CREATE TABLE IF NOT EXISTS tasks (task_id TEXT PRIMARY KEY, record TEXT NOT NULL)')
            return connection
        except BaseException:
            connection.close()
            raise
    if not path.exists():
        return None
    return sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=15)


def emit_activity(root, event, now=None):
    """Commit one explicitly reported event atomically. Retries require identical payloads."""
    event = validate_event(event)
    stamp = _time(now)
    payload = json.dumps(event, sort_keys=True, separators=(',', ':'))
    connection = _connect(root, create=True)
    try:
        connection.execute('BEGIN IMMEDIATE')
        previous = connection.execute('SELECT payload FROM events WHERE event_id=?', (event['event_id'],)).fetchone()
        if previous:
            if previous[0] != payload:
                raise ValueError('event_id already used with different payload')
            connection.rollback()
            return {'accepted': False, 'duplicate': True, 'task_id': event['task_id'], 'event_id': event['event_id']}
        existing = connection.execute('SELECT record FROM tasks WHERE task_id=?', (event['task_id'],)).fetchone()
        record = json.loads(existing[0]) if existing else None
        if record:
            if record['chat_id'] != event['chat_id']:
                raise ValueError('task_id belongs to a different chat_id')
            if record['status'] in TERMINAL:
                raise ValueError('terminal task cannot reopen; use a new task_id')
            if event['type'] == 'started':
                raise ValueError('task already started')
            if stamp < _time(record['updated_at']):
                raise ValueError('event time precedes last event')
        elif event['type'] != 'started':
            raise ValueError('task must begin with started')
        else:
            parent_id = event.get('parent_task_id')
            seen = {event['task_id']}
            while parent_id:
                if parent_id in seen:
                    raise ValueError('parent task cycle')
                seen.add(parent_id)
                parent = connection.execute('SELECT record FROM tasks WHERE task_id=?', (parent_id,)).fetchone()
                if not parent:
                    raise ValueError('unknown parent task')
                parent_id = json.loads(parent[0]).get('parent_task_id')
            record = {'task_id': event['task_id'], 'chat_id': event['chat_id'], 'started_at': _iso(stamp),
                      'title': '', 'summary': '', 'provenance': '', 'area_refs': [], 'edges': [], 'outputs': [],
                      'agent_id': '', 'project_id': '', 'reads': [],
                      'parent_task_id': event.get('parent_task_id', ''),
                      'model': event.get('model', ''), 'reasoning_effort': event.get('reasoning_effort', '')}
        for field in ('title', 'summary', 'provenance', 'area_refs', 'edges', 'agent_id', 'project_id'):
            if field in event:
                record[field] = event[field]
        if 'edges' in event:
            record['edges_event_id'] = event['event_id']
        if 'outputs' in event:
            combined = record['outputs'] + event['outputs']
            record['outputs'] = list({json.dumps(x, sort_keys=True): x for x in combined}.values())[-16:]
        if 'reads' in event:
            combined = record.get('reads', []) + event['reads']
            record['reads'] = list({json.dumps(x, sort_keys=True): x for x in combined}.values())[-32:]
        record.update(status=event['type'] if event['type'] in TERMINAL else 'running', lifecycle=event['type'],
                      last_event_type=event['type'], last_event_edges=event.get('edges', []),
                      last_event_reads=event.get('reads', []),
                      last_event_public_summary=event.get('summary', ''),
                      updated_at=_iso(stamp), lease_seconds=event['lease_seconds'],
                      lease_expires_at=_iso(stamp + timedelta(seconds=event['lease_seconds'])), last_event_id=event['event_id'])
        serialized = json.dumps(record)
        if len(serialized.encode('utf-8')) > MAX_RECORD_BYTES:
            raise ValueError('accumulated task record too large')
        connection.execute('INSERT INTO events VALUES (?,?,?)', (event['event_id'], payload, _iso(stamp)))
        connection.execute('INSERT OR REPLACE INTO tasks VALUES (?,?)', (event['task_id'], serialized))
        connection.commit()
        return {'accepted': True, 'duplicate': False, 'task_id': event['task_id'], 'event_id': event['event_id']}
    finally:
        connection.close()


def _limit(value, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f'limit must be an integer from 1 to {maximum}')
    return value


def read_activity(root, now=None, limit=512):
    """Read records without creating/writing a store; derive stale from expired leases."""
    stamp = _time(now)
    limit = _limit(limit, 2048)
    connection = _connect(root)
    if connection is None:
        return []
    try:
        records = [json.loads(row[0]) for row in connection.execute('''
            SELECT record FROM tasks
            WHERE length(CAST(record AS BLOB)) <= ?
            ORDER BY (json_extract(record, '$.status') = 'running'
                      AND json_extract(record, '$.lease_expires_at') > ?) DESC,
                     json_extract(record, '$.updated_at') DESC, task_id DESC
            LIMIT ?''', (MAX_RECORD_BYTES, _iso(stamp), limit))]
    finally:
        connection.close()
    for record in records:
        # Older records have no reliable event-specific edge capture; never
        # promote their retained task relationships to a fresh event pulse.
        record.setdefault('last_event_type', record.get('lifecycle', ''))
        record.setdefault('last_event_edges', [])
        record.setdefault('edges_event_id', '')
        for field in ('parent_task_id', 'model', 'reasoning_effort'):
            record.setdefault(field, '')
        record.setdefault('reads', [])
        record.setdefault('last_event_reads', [])
        record['public_summary'] = record.get('summary', '')
        if record['status'] == 'running' and stamp >= _time(record['lease_expires_at']):
            record['status'] = 'stale'
    return records


def read_events(root, task_id, limit=100):
    """Latest bounded history in commit order; public fields only, no effect replay."""
    task_id = _id(task_id, 'task_id')
    limit = _limit(limit, 500)
    connection = _connect(root)
    if connection is None:
        return {'events': [], 'truncated': False}
    try:
        rows = connection.execute('''
            SELECT event_id, payload, received_at FROM events
            WHERE json_extract(payload, '$.task_id') = ?
              AND length(CAST(payload AS BLOB)) <= ?
            ORDER BY rowid DESC LIMIT ?''', (task_id, MAX_INPUT_BYTES, limit + 1)).fetchall()
    finally:
        connection.close()
    events = []
    for event_id, payload, at in reversed(rows[:limit]):
        event = json.loads(payload)
        events.append({'event_id': event_id, 'type': event['type'], 'at': at,
                       'task_id': event['task_id'], 'chat_id': event['chat_id'],
                       'reads': event.get('reads', []),
                       'area_refs': event.get('area_refs', []),
                       **{key: event[key] for key in ('parent_task_id', 'model', 'reasoning_effort') if key in event},
                       'edges': event.get('edges', []), 'outputs': event.get('outputs', []),
                       'summary': event.get('summary', ''), 'provenance': event.get('provenance', '')})
    return {'events': events, 'truncated': len(rows) > limit}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    sub = parser.add_subparsers(dest='command', required=True)
    emit = sub.add_parser('emit'); emit.add_argument('--json-file', type=Path, required=True)
    sub.add_parser('read')
    history = sub.add_parser('history')
    history.add_argument('--task-id', required=True)
    history.add_argument('--limit', type=int, default=100)
    args = parser.parse_args(argv)
    try:
        if args.command == 'emit':
            with args.json_file.open('rb') as stream:
                raw = stream.read(MAX_INPUT_BYTES + 1)
            if len(raw) > MAX_INPUT_BYTES:
                raise ValueError('JSON input too large')
            result = emit_activity(args.root, json.loads(raw.decode('utf-8-sig')))
        elif args.command == 'history':
            result = read_events(args.root, args.task_id, args.limit)
        else:
            result = read_activity(args.root)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, OSError, sqlite3.Error) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
