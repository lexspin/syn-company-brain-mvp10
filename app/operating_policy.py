"""Admission policy, independent of model effort and observed worker activity.

Only the canonical command worker writes policy records. Readers never create a
Brain or migrate live state. Legacy workspaces retain Active until a policy has
existed; broken policy fails closed thereafter.
"""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

POLICY_ID = 'operating-policy'
STATES = {'off': 0, 'idle': 1, 'active': 2}
DEFAULT_IDLE = {'max_batch': 2, 'cooldown_seconds': 300}


def validate_policy(data):
    if not isinstance(data, dict) or data.get('schema_version') != 1:
        raise ValueError('Operating policy requires schema version 1.')
    if not isinstance(data.get('requested_state'), str) or data['requested_state'] not in STATES:
        raise ValueError('Choose off, idle or active.')
    idle = data.get('idle', DEFAULT_IDLE)
    if not isinstance(idle, dict) or set(idle) != set(DEFAULT_IDLE):
        raise ValueError('Idle policy requires max_batch and cooldown_seconds.')
    if type(idle['max_batch']) is not int or not 1 <= idle['max_batch'] <= 4:
        raise ValueError('Idle batch must contain 1–4 routines.')
    if type(idle['cooldown_seconds']) is not int or not 60 <= idle['cooldown_seconds'] <= 86400:
        raise ValueError('Routine cooldown must be 60–86400 seconds.')
    return data


def interpret(record, *, previously_configured=False):
    if record is None:
        return {'requested_state': None, 'effective_state': 'off' if previously_configured else 'active',
                'version': 0, 'source': 'missing-configured-policy' if previously_configured else 'legacy-active',
                'idle': dict(DEFAULT_IDLE)}
    if not isinstance(record, dict): record = {'data': {}}
    try:
        if record.get('archived'): raise ValueError('Operating policy is archived.')
        data = validate_policy(record['data'])
        return {'requested_state': data['requested_state'], 'effective_state': data['requested_state'],
                'version': record['version'], 'source': 'configured', 'idle': dict(data.get('idle', DEFAULT_IDLE))}
    except (ValueError, KeyError, TypeError) as error:
        return {'requested_state': None, 'effective_state': 'off', 'version': record.get('version', 0),
                'source': 'invalid-policy', 'error': str(error), 'idle': dict(DEFAULT_IDLE)}


def policy_for_brain(brain):
    try: record = brain.get('stack', POLICY_ID)
    except ValueError as error:
        if str(error) != 'Record does not exist.': raise
        record = None
    historical = (Path(brain.root)/'records/stack'/POLICY_ID).exists()
    return interpret(record, previously_configured=historical)


def policy_for_root(root):
    """Read committed projection, not lagging publication, without a writer."""
    root = Path(root)
    historical = (root/'records/stack'/POLICY_ID).exists()
    database = root/'runtime/brain.sqlite'
    try:
        if database.exists():
            with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro', uri=True, timeout=2)) as connection:
                row = connection.execute("SELECT data,version,archived FROM objects WHERE kind='stack' AND id=?", (POLICY_ID,)).fetchone()
            record = {'data': json.loads(row[0]), 'version': row[1], 'archived': row[2]} if row else None
        else:
            path = root/'data/state.json'
            state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
            state = state.get('data', state)
            record = next((r for r in state.get('objects', []) if r.get('kind') == 'stack' and r.get('id') == POLICY_ID), None)
        return interpret(record, previously_configured=historical)
    except (OSError, sqlite3.Error, ValueError, TypeError, AttributeError) as error:
        return interpret({'data': {}, 'version': 0}) | {'error': 'Policy read failed: '+str(error)}


def effective_state(policy, agent=None):
    state = policy['effective_state']
    if agent is not None:
        override = agent.get('data', agent).get('operating_state', 'active')
        if not isinstance(override, str) or override not in STATES: return 'off'
        state = min((state, override), key=STATES.get)
    return state


def require_allowed(policy, work_kind='task', agent=None):
    if work_kind not in {'task', 'routine', 'scheduled'}: raise ValueError('Unknown work lane.')
    state = effective_state(policy, agent)
    if work_kind == 'scheduled':
        # A role cap cannot turn company Active into permission for passive work.
        if policy['effective_state'] != 'idle' or state != 'idle':
            raise ValueError('Operating state '+policy['effective_state']+' blocks new scheduled work (requires company and effective Idle).')
        return state
    if state == 'off' or state == 'idle' and work_kind != 'routine':
        raise ValueError('Operating state '+state+' blocks new '+work_kind+' work.')
    return state


def assert_work_allowed(brain, work_kind='task', agent=None):
    return require_allowed(policy_for_brain(brain), work_kind, agent)


def admit_command(brain, action, payload):
    # State control, read-only inspection and reconciliation of begun effects
    # remain reachable even Off. A completion is not a fresh execution request.
    if action in {'operating-state', 'cancel', 'search', 'creative-poll', 'creative-preflight',
                  'save', 'archive-research', 'learning-candidate', 'retain', 'accept'}:
        if action == 'save' and payload.get('kind') == 'stack' and payload.get('id') == POLICY_ID:
            validate_policy(payload['data'])
        return
    routine = action in {'routine-run', 'change-scan', 'index', 'backup'} or (
        action in {'save', 'archive-research'} and bool(payload.get('maintenance')))
    agent = brain.get('agent', payload['agent']) if action == 'chat' and payload['agent'] not in {'auto', 'coordinator'} else None
    assert_work_allowed(brain, 'routine' if routine else 'task', agent)


def set_requested_state(brain, state, version, agent_id=None):
    if not isinstance(state, str) or state not in STATES: raise ValueError('Choose off, idle or active.')
    if type(version) is not int or version < 0: raise ValueError('Invalid expected version.')
    if agent_id:
        agent = brain.get('agent', agent_id)
        return brain.save('agent', agent_id, agent['data'] | {'operating_state': state}, version, bool(agent['archived']))
    try: previous = brain.get('stack', POLICY_ID)['data']
    except ValueError as error:
        if str(error) != 'Record does not exist.': raise
        previous = {'name': 'Operating policy', 'schema_version': 1, 'idle': dict(DEFAULT_IDLE), 'refs': []}
    data = previous | {'requested_state': state}
    validate_policy(data)
    return brain.save('stack', POLICY_ID, data, version, False)


def read_agent(root, agent_id):
    root = Path(root)
    database = root/'runtime/brain.sqlite'
    if database.exists():
        with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro', uri=True, timeout=2)) as connection:
            row = connection.execute("SELECT data,archived FROM objects WHERE kind='agent' AND id=?", (agent_id,)).fetchone()
        if not row or row[1]: raise ValueError('Agent is missing or archived.')
        return json.loads(row[0])
    state = json.loads((root/'data/state.json').read_text(encoding='utf-8'))
    state = state.get('data', state)
    agent = next((r for r in state.get('objects', []) if r.get('kind') == 'agent' and r.get('id') == agent_id and not r.get('archived')), None)
    if not agent: raise ValueError('Agent is missing or archived.')
    return agent['data']


def main():
    import argparse
    from datetime import datetime, timezone, timedelta
    parser = argparse.ArgumentParser(description='Read-only native-chat admission check; does not claim or execute work.')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--lane', choices=('routine', 'task', 'scheduled'), required=True)
    parser.add_argument('--agent')
    parser.add_argument('--due-at', help='UTC/offset ISO occurrence due time, when available.')
    parser.add_argument('--last-run', help='UTC/offset ISO last admitted occurrence, when available.')
    parser.add_argument('--unchanged-evidence', action='store_true', help='Skip a review whose bound evidence is unchanged.')
    args = parser.parse_args()
    policy = policy_for_root(args.root)
    try:
        agent = read_agent(args.root, args.agent) if args.agent else None
        state = require_allowed(policy, args.lane, agent)
        current = datetime.now(timezone.utc)
        def timestamp(raw):
            parsed = datetime.fromisoformat(raw)
            if parsed.tzinfo is None: raise ValueError('Eligibility timestamps require a UTC offset.')
            return parsed
        if args.due_at and timestamp(args.due_at) > current:
            raise ValueError('The requested occurrence is not due yet.')
        if args.last_run and timestamp(args.last_run) > current-timedelta(seconds=policy['idle']['cooldown_seconds']):
            raise ValueError('Routine cooldown has not elapsed.')
        if args.unchanged_evidence:
            raise ValueError('Evidence is unchanged; reuse the previous checked result.')
        decision = {'allowed': True, 'effective_state': state, 'lane': args.lane, 'policy': policy,
                    'scope': 'Admission only; authority, due timing, unchanged evidence and occurrence ownership must still be checked.'}
    except (ValueError, OSError, sqlite3.Error, TypeError) as error:
        decision = {'allowed': False, 'effective_state': policy['effective_state'], 'lane': args.lane, 'policy': policy, 'reason': str(error)}
    print(json.dumps(decision, ensure_ascii=False))
    return 0 if decision['allowed'] else 3


if __name__ == '__main__':
    raise SystemExit(main())
