"""Bounded change outbox owned by the existing command worker, never a timer.

Only IDs, versions and hashes enter this journal. Native execution remains a
claimed workflow request. Observing a change is not permission to rewrite it.
"""
import argparse
import hashlib
import json
from pathlib import Path

LOOP = 'connected-change-review'
LIMIT = 24
FOLDERS = {'app', 'evaluations', 'company', 'routines', 'docs'}
SUFFIXES = {'.py', '.js', '.html', '.css', '.json', '.md', '.toml', '.yaml', '.yml', '.ps1'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def file_path(root, key):
    if not isinstance(key, str) or not key.startswith('file:'):
        raise ValueError('Expected a scoped file identity.')
    rel = Path(key[5:])
    if rel.is_absolute() or '..' in rel.parts or not rel.parts:
        raise ValueError('Invalid change source path.')
    if (len(rel.parts) > 1 and rel.parts[0] not in FOLDERS) or rel.suffix.lower() not in SUFFIXES:
        raise ValueError('File is outside the change scanner scope.')
    path = (Path(root)/rel).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError('Change source leaves the workspace.')
    return path


def file_binding(root, key):
    path = file_path(root, key)
    return {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} if path.is_file() else {'deleted': True}


def record_binding(record):
    return {'version': record['version'], 'sha256': digest({'data': record['data'], 'archived': bool(record['archived'])})}


def records(brain):
    return {r['kind']+':'+r['id']: record_binding(r) for r in brain.list(archived=True)
            if r['data'].get('type') != 'native-work-request'}


def files(root):
    result = {}
    for folder in sorted(FOLDERS):
        for path in (root/folder).rglob('*'):
            if path.is_file() and path.suffix.lower() in SUFFIXES and not any(p in {'__pycache__', 'node_modules', '.git'} for p in path.parts):
                key = 'file:'+path.relative_to(root).as_posix()
                result[key] = file_binding(root, key)
    for path in root.iterdir():
        if path.is_file() and path.suffix.lower() in SUFFIXES:
            key = 'file:'+path.name; result[key] = file_binding(root, key)
    return result


def validate_sources(brain, sources):
    if not isinstance(sources, dict) or not 1 <= len(sources) <= LIMIT:
        raise ValueError('Change request needs bounded source bindings.')
    for key, expected in sources.items():
        if key.startswith('file:'):
            current = file_binding(brain.root, key)
        else:
            try:
                kind, ident = key.split(':', 1)
                current = record_binding(brain.get(kind, ident))
            except (ValueError, KeyError):
                current = {'deleted': True}
        if current != expected:
            raise ValueError('Change source is stale: '+key+'. Retain the attempt and request a fresh review.')


class ChangeEvents:
    def __init__(self, brain):
        self.brain = brain
        self.folder = brain.root/'runtime/change-events'
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder/'state.json'
        if self.path.exists():
            self.state = json.loads(self.path.read_text(encoding='utf-8'))
        else:
            self.state = {'schema': 1, 'baseline': records(brain)|files(brain.root), 'pending': {}, 'active': None,
                          'inflight': None, 'note': 'Initial observation only; prior contents were baselined, not queued as new changes.'}
            self.write()

    def write(self):
        from commands import atomic_json
        atomic_json(self.path, self.state)

    def maintenance(self, payload):
        origin = payload.get('maintenance')
        if origin is None: return False
        if not isinstance(origin, dict) or set(origin) != {'request_id', 'claimant'}:
            raise ValueError('Maintenance origin requires request_id and claimant.')
        r = self.brain.get('memory', origin['request_id'])
        d = r['data']
        if r['archived'] or d.get('type') != 'native-work-request' or d.get('loop_id') != LOOP or d.get('request_state') != 'running' or d.get('claimant') != origin['claimant']:
            raise ValueError('Maintenance origin is not a current owned running change review.')
        return True

    def begin(self, request):
        if self.state.get('inflight'):
            self.after()
        suppress = self.maintenance(request['payload']) or request['action'] in {'archive-research', 'learning-candidate', 'index'}
        self.state['inflight'] = {'id': request['id'], 'suppress': suppress}
        self.write()

    def observe(self, current, file_scope=False, suppress=False):
        baseline = self.state['baseline']
        previous = {k: v for k, v in baseline.items() if k.startswith('file:') == file_scope}
        for key in sorted(previous.keys() | current.keys()):
            old, new = previous.get(key), current.get(key, {'deleted': True})
            # An unchanged save/version does not create another semantic event.
            old_content = {k: v for k, v in (old or {}).items() if k != 'version'}
            new_content = {k: v for k, v in new.items() if k != 'version'}
            if old_content != new_content and not suppress:
                self.state['pending'][key] = new
            baseline[key] = new
        self.write()

    def after(self):
        inflight = self.state.get('inflight') or {}
        self.observe(records(self.brain), suppress=bool(inflight.get('suppress')))
        self.state['inflight'] = None
        self.write()
        return self.flush()

    def recover(self):
        # Observe effects of an interrupted command; never execute that command.
        self.after()

    def scan(self, payload):
        acknowledged = {}
        for row in payload.get('acknowledge', []):
            if not self.maintenance(payload): raise ValueError('File acknowledgement needs an owned maintenance request.')
            if not isinstance(row, dict) or set(row) != {'key', 'sha256'}:
                raise ValueError('Acknowledge exact file key and sha256 only.')
            current = file_binding(self.brain.root, row['key'])
            if current != {'sha256': row['sha256']}:
                raise ValueError('Maintenance file changed before acknowledgement.')
            acknowledged[row['key']] = current
        self.state['baseline'].update(acknowledged)
        self.write()
        # A maintenance label never suppresses unrelated concurrent file edits.
        self.observe(files(self.brain.root), file_scope=True)
        if payload.get('retry'): self.retry(payload['retry'])
        return self.status()

    def batch(self, ident):
        return json.loads((self.folder/(ident+'.json')).read_text(encoding='utf-8'))

    def retry(self, ident):
        if not isinstance(ident, str) or not ident.startswith('change-') or len(ident) != 39 or any(c not in '0123456789abcdef' for c in ident[7:]):
            raise ValueError('Invalid change batch identity.')
        batch = self.batch(ident)
        request = self.brain.get('memory', ident)
        if request['data'].get('request_state') != 'failed':
            raise ValueError('Only an explicitly failed request can be retried; reconcile running or uncertain work.')
        if batch.get('retry'):
            self.ensure_request(batch['retry'])
            return
        active = self.state.get('active')
        if active and active != ident:
            self.ensure_request(active)
            if self.brain.get('memory', active)['data']['request_state'] in {'queued', 'running'}:
                raise ValueError('Reconcile the active change request before issuing a retry.')
        sources = {}
        for key in batch['sources']:
            if key.startswith('file:'): sources[key] = file_binding(self.brain.root, key)
            else:
                kind, rid = key.split(':', 1)
                sources[key] = record_binding(self.brain.get(kind, rid))
        retry_id = 'change-'+digest({'retry_of': ident, 'sources': sources})[:32]
        if batch.get('attempt', 1) >= 2: raise ValueError('Retry allowance exhausted; retain the failure for review.')
        self.create_batch(sources, retry_id, retry_of=ident, attempt=2)
        batch['retry'] = retry_id
        from commands import atomic_json
        atomic_json(self.folder/(ident+'.json'), batch)

    def create_batch(self, sources, ident, retry_of=None, attempt=1):
        from commands import atomic_json, stamp
        loop = self.brain.get('loop', LOOP)
        if loop['archived']: raise ValueError('Connected change review is archived.')
        batch = {'id': ident, 'sources': sources, 'loop_version': loop['version'], 'created': stamp(), 'retry_of': retry_of, 'attempt': attempt}
        target = self.folder/(ident+'.json')
        if not target.exists(): atomic_json(target, batch)
        self.state['active'] = ident
        for key, value in sources.items():
            if self.state['pending'].get(key) == value: self.state['pending'].pop(key)
        self.write()  # Persist ownership/manifest before creating the versioned request.
        self.ensure_request(ident)

    def ensure_request(self, ident):
        batch = self.batch(ident)
        try:
            existing = self.brain.get('memory', ident)
        except (KeyError, ValueError): pass
        else:
            if existing['data'].get('change_event_id') != ident or existing['data'].get('change_sources') != batch['sources']:
                raise ValueError('Change request identity conflicts with its retained manifest.')
            return
        # A crash may leave only the manifest. Bind the current workflow before
        # the first request exists; never alter an already queued request.
        loop = self.brain.get('loop', LOOP)
        if loop['version'] != batch['loop_version']:
            from commands import atomic_json
            batch['previous_loop_version'] = batch['loop_version']
            batch['loop_version'] = loop['version']
            atomic_json(self.folder/(ident+'.json'), batch)
        data = {'name': 'Review connected changes', 'type': 'native-work-request', 'status': 'candidate',
                'content': 'Automatically observed changes. Inspect impact, retain useful outcomes and repair proven links; propose semantic updates. Original sources are not rewritten automatically.',
                'source': 'Canonical command worker change outbox; bounded identity/version/hash observations.',
                'loop_id': LOOP, 'loop_version': batch['loop_version'], 'refs': ['loop:'+LOOP],
                'request_state': 'queued', 'requested_at': batch['created'],
                'request_input': 'Review observed sources and their actual consumers. Bind the following exact observations; do not replay originating actions: '+json.dumps(batch['sources'], sort_keys=True),
                'change_sources': batch['sources'], 'change_event_id': ident}
        self.brain.save('memory', ident, data)

    def flush(self):
        active = self.state.get('active')
        if active:
            self.ensure_request(active)
            r = self.brain.get('memory', active)
            if r['data']['request_state'] in {'queued', 'running'}: return self.status()
            self.state['active'] = None; self.write()
        if self.state['pending']:
            try: loop = self.brain.get('loop', LOOP)
            except (ValueError, KeyError): return self.status('Register the connected-change workflow before dispatch.')
            if loop['archived']: return self.status('Connected-change workflow is archived.')
            sources = dict(list(sorted(self.state['pending'].items()))[:LIMIT])
            ident = 'change-'+digest({'sources': sources, 'loop_version': loop['version']})[:32]
            # One identity per exact observation, even after process recovery.
            self.create_batch(sources, ident)
        return self.status()

    def status(self, warning=None):
        return {'active_request': self.state.get('active'), 'pending_sources': len(self.state['pending']),
                'baseline_sources': len(self.state['baseline']), 'warning': warning,
                'scope': 'Observed local changes only. Existing native dispatcher executes claimed reviews; no timer or provider call.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['scan'])
    parser.add_argument('--retry')
    parser.add_argument('--maintenance-request'); parser.add_argument('--claimant')
    parser.add_argument('--acknowledge', type=Path, help='JSON list of exact file key/sha256 pairs produced by this maintenance request')
    args = parser.parse_args()
    import importlib.util
    helper = Path.home()/'.codex/skills/company-brain-archive-research/scripts/archive_research.py'
    spec = importlib.util.spec_from_file_location('change_http', helper)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    client = module.Client().connect()
    payload = {}
    if args.retry: payload['retry'] = args.retry
    if args.maintenance_request: payload['maintenance'] = {'request_id': args.maintenance_request, 'claimant': args.claimant}
    if args.acknowledge: payload['acknowledge'] = json.loads(args.acknowledge.read_text(encoding='utf-8-sig'))
    # Scan is safe to repeat with a fresh transport ID; observed bindings deduplicate.
    import uuid
    rid = uuid.uuid4().hex
    try: client._read('/api/change-scan', payload, rid)
    except Exception:
        print(json.dumps({'request_id': rid, 'receipt': client.receipt(rid)})); raise
    receipt = client.receipt(rid)
    print(json.dumps(receipt, indent=2))
    if not receipt.get('ok') or receipt.get('state') != 'completed':
        raise SystemExit('Scan not confirmed complete; inspect retained receipt '+rid)


if __name__ == '__main__': main()
