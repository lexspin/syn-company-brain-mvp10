"""Durable local command requests. HTTP enqueues; a backend worker executes.

Requests, begun markers and receipts are retained. A begun command without a
receipt is ambiguous after restart and is never silently repeated. Stable-key
workflow starts are the sole recoverable exception.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path


def stamp():
    return datetime.now(timezone.utc).isoformat()


ID = re.compile(r'[a-z0-9][a-z0-9-]{0,63}\Z')
SESSION = re.compile(r'[A-Za-z0-9_-]{1,80}\Z')
REQUEST_ID = re.compile(r'[a-f0-9]{32}\Z')
KINDS = {'agent', 'skill', 'memory', 'loop', 'stack', 'project'}
FIELDS = {
    'creative-save': ({'id','version','board'}, {'project_id'}),
    'creative-image': ({'image'}, set()),
    'creative-generate': ({'id','version','shot_id','media','paid_authorized'}, set()),
    'creative-poll': ({'job_id'}, set()),
    'creative-preflight': (set(), set()),
    'save': ({'kind', 'id', 'data'}, {'version', 'archived'}),
    'chat': ({'session', 'prompt', 'agent'}, {'project_id'}),
    'start': ({'id', 'key'}, set()),
    'cancel': ({'id'}, set()), 'resume': ({'id'}, set()),
    'accept': ({'id'}, set()), 'retain': ({'id'}, set()),
    'index': (set(), set()), 'search': (set(), {'query'}),
    'git-save': (set(), set()), 'git-push': (set(), set()),
    'backup': (set(), set()),
    'improvement-propose': ({'skill_id', 'feedback'}, {'session'}),
    'improvement-apply': ({'id'}, set()),
    'routine-run': ({'id'}, {'key'}),
    'archive-research': (set(), {'turn_id', 'title', 'content', 'provenance', 'request_key', 'project_id', 'skill_ids'}),
}


def _text(value, name, minimum=1, maximum=12000):
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise ValueError(f'{name} must contain {minimum}–{maximum} characters.')


def validate(action, payload):
    """Validate the allowed transport shape before any queue file is written."""
    if action not in FIELDS or not isinstance(payload, dict):
        raise ValueError('Unsupported operation.')
    required, optional = FIELDS[action]
    if not required <= payload.keys() or payload.keys() - required - optional:
        raise ValueError('Request fields do not match this operation.')
    if len(json.dumps(payload, ensure_ascii=False)) > 190000:
        raise ValueError('Request is too large.')
    for key in ('id', 'skill_id', 'project_id'):
        if key in payload:
            value = payload[key]
            if key == 'project_id' and value == '':
                continue
            pattern = REQUEST_ID if action in {'cancel', 'resume', 'accept', 'retain'} else ID
            if not isinstance(value, str) or not pattern.fullmatch(value):
                raise ValueError('Invalid '+key+'.')
    if action == 'save':
        if payload['kind'] not in KINDS or not isinstance(payload['data'], dict):
            raise ValueError('Invalid record type or data.')
        if type(payload.get('version', 0)) is not int or payload.get('version', 0) < 0:
            raise ValueError('Invalid expected version.')
        if type(payload.get('archived', False)) is not bool:
            raise ValueError('Invalid archive state.')
    if action in {'creative-save','creative-generate'}:
        if type(payload['version']) is not int or payload['version']<0: raise ValueError('Invalid board version.')
    if action=='creative-save' and not isinstance(payload['board'],dict): raise ValueError('Invalid board.')
    if action=='creative-image': _text(payload['image'],'Preview image',1,175000)
    if action=='creative-poll' and (not isinstance(payload['job_id'],str) or not REQUEST_ID.fullmatch(payload['job_id'])): raise ValueError('Invalid creative job.')
    if action=='creative-generate':
        if payload['media'] not in {'still','video'} or type(payload['paid_authorized']) is not bool: raise ValueError('Invalid generation request.')
        _text(payload['shot_id'],'Shot ID',1,50)
    if action == 'chat':
        if not isinstance(payload['session'], str) or not SESSION.fullmatch(payload['session']):
            raise ValueError('Invalid conversation ID.')
        if not isinstance(payload['agent'], str) or not ID.fullmatch(payload['agent']):
            raise ValueError('Invalid team role.')
        _text(payload['prompt'], 'Message')
    if action == 'improvement-propose':
        _text(payload['feedback'], 'Correction', 3, 8000)
        session = payload.get('session', '')
        if not isinstance(session, str) or session and not SESSION.fullmatch(session):
            raise ValueError('Invalid conversation ID.')
    if 'key' in payload:
        _text(payload['key'], 'Request key', 8, 128)
        if not re.fullmatch(r'[A-Za-z0-9_-]+', payload['key']):
            raise ValueError('Invalid request key.')
    if action == 'search':
        _text(payload.get('query', ''), 'Search', 0, 12000)
    if action == 'archive-research':
        turn_fields, source_fields = {'turn_id'}, {'title', 'content', 'provenance', 'request_key'}
        supplied = payload.keys() - {'project_id', 'skill_ids'}
        if supplied == turn_fields:
            if not isinstance(payload['turn_id'], str) or not REQUEST_ID.fullmatch(payload['turn_id']):
                raise ValueError('Invalid completed answer identity.')
        elif supplied == source_fields:
            _text(payload['title'], 'Research title', 1, 180)
            _text(payload['content'], 'Research', 1, 100000)
            if not isinstance(payload['provenance'], dict): raise ValueError('Source provenance must be an object.')
            if not isinstance(payload['request_key'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', payload['request_key']):
                raise ValueError('Invalid archive request key.')
        else: raise ValueError('Choose a completed answer or provide research text with its real source provenance.')
        skills = payload.get('skill_ids', [])
        if not isinstance(skills, list) or len(skills)>30 or any(not isinstance(id, str) or not ID.fullmatch(id) for id in skills):
            raise ValueError('Choose up to 30 registered playbooks.')


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    raw = (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode('utf-8')
    with temporary.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class CommandQueue:
    """The dashboard's only write capability: append a validated request."""
    def __init__(self, root):
        self.root = Path(root).resolve()/'runtime/queue'
        for name in ('requests', 'begun', 'receipts'):
            (self.root/name).mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.changed = threading.Event()

    def path(self, category, request_id):
        if category not in {'requests', 'begun', 'receipts'} or not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
            raise ValueError('Invalid command identity.')
        return self.root/category/(request_id+'.json')

    def enqueue(self, action, payload, request_id=None, requested_by='local-owner-ui'):
        validate(action, payload)
        # A repeated workflow start retains its original transport and run identity.
        if request_id is None and action == 'start':
            request_id = hashlib.sha256(('start:'+payload['key']).encode()).hexdigest()[:32]
        request_id = request_id or uuid.uuid4().hex
        path = self.path('requests', request_id)
        with self.lock:
            if path.exists():
                existing = json.loads(path.read_text(encoding='utf-8'))
                if existing['action'] != action or existing['payload'] != payload:
                    raise ValueError('This request identity already belongs to different work.')
                return request_id
            request = {'id': request_id, 'action': action, 'payload': payload,
                       'requested_by': requested_by, 'requested_at': stamp(),
                       'machine': 'local', 'schema_version': 1}
            atomic_json(path, request)
            self.changed.set()
        return request_id

    def receipt(self, request_id):
        path = self.path('receipts', request_id)
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None

    def wait(self, request_id, timeout=400):
        deadline = time.monotonic()+min(400, max(0, timeout))
        while True:
            receipt = self.receipt(request_id)
            if receipt is not None:
                return receipt
            left = deadline-time.monotonic()
            if left <= 0:
                return {'id': request_id, 'ok': False, 'http_status': 503,
                        'state': 'pending', 'error': 'The request is still pending. Check the saved work before submitting it again.'}
            self.changed.wait(min(left, .25))
            self.changed.clear()


class CommandWorker:
    """Separate backend owner of all effects; safe to run without an HTTP server."""
    def __init__(self, brain, queue, publisher, routine_engine=None):
        self.brain, self.queue, self.publisher = brain, queue, publisher
        self.routine_engine = routine_engine
        self.stopped = threading.Event()
        self.thread = None
        self.lease = None

    def _acquire_lease(self):
        self.lease = (self.queue.root/'worker.lock').open('a+b')
        self.lease.seek(0)
        if self.lease.read(1) == b'':
            self.lease.write(b'0'); self.lease.flush()
        self.lease.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lease.close(); self.lease = None
            raise RuntimeError('Another local command worker already owns this workspace.')

    def start(self):
        if self.lease is None: self._acquire_lease()
        self.recover()
        self.thread = threading.Thread(target=self.run, name='company-brain-commands', daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped.set(); self.queue.changed.set()
        if self.thread:
            self.thread.join(timeout=2)
        # Keep the process lock while an in-flight call is still running.
        if self.lease and not (self.thread and self.thread.is_alive()):
            self.lease.close(); self.lease = None

    def _finish(self, request, result=None, error=None, state='completed', http_status=200):
        receipt = {'id': request['id'], 'action': request['action'],
                   'requested_at': request['requested_at'], 'finished_at': stamp(),
                   'ok': error is None, 'state': state, 'http_status': http_status}
        receipt['result' if error is None else 'error'] = result if error is None else error
        atomic_json(self.queue.path('receipts', request['id']), receipt)
        self.queue.changed.set()
        return receipt

    def _read_request(self, path):
        """A corrupt request must not block unrelated work or choose another ID."""
        try:
            request = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(request, dict) or request.get('id') != path.stem or not isinstance(request.get('requested_at'), str):
                raise ValueError('Invalid saved request identity or timestamp.')
            validate(request['action'], request['payload'])
            return request
        except (ValueError, KeyError, TypeError, OSError):
            self._finish({'id':path.stem, 'action':'invalid-request', 'requested_at':None},
                         error='The saved request is invalid. Its original file has been retained for review.',
                         state='failed', http_status=400)
            return None

    def recover(self):
        for path in sorted((self.queue.root/'begun').glob('*.json')):
            request_id = path.stem
            if not REQUEST_ID.fullmatch(request_id) or self.queue.receipt(request_id):
                continue
            request_path = self.queue.path('requests', request_id)
            if not request_path.exists():
                continue
            request = self._read_request(request_path)
            if request is None: continue
            if request.get('action') == 'start':
                # Brain.start deduplicates by the same durable receipt key.
                self.process(request, recovering=True)
            else:
                self._finish(request, error='The service stopped after this command began. Its outcome may already exist; inspect the saved work before making a new request. It was not repeated.',
                             state='interrupted', http_status=409)

    def dispatch(self, action, p, request_id):
        b = self.brain
        if action.startswith('creative-'):
            from creative import dispatch
            return dispatch(b,action,p,request_id)
        if action == 'save':
            return b.save(p['kind'], p['id'], p['data'], p.get('version', 0), p.get('archived', False))
        if action == 'chat':
            result = b.chat(p['session'], p['prompt'], p['agent'], project_id=p.get('project_id', ''))
            # Chat has released its active worker lock. Retention failure cannot
            # repeat or turn an already completed model answer into a failed chat.
            try:
                from answer_memory import retain_answer
                result = result | retain_answer(b, result)
            except Exception as error:
                result = result | {'retention_warning':'The answer completed, but automatic retention was not confirmed: '+str(error)}
            return result
        if action == 'start': return b.start(p['id'], p['key'])
        if action in {'cancel', 'resume', 'accept', 'retain'}: return getattr(b, action)(p['id'])
        if action == 'index': b.export(); return {'records': len(b.list())}
        if action == 'search': return b.retrieve(p.get('query', ''))
        if action == 'git-save': return b.git('commit')
        if action == 'git-push': return b.git('push')
        if action == 'backup':
            with self.queue.lock:
                if self.routine_engine is not None:
                    with self.routine_engine.exclusive() as acquired:
                        if not acquired: raise ValueError('A local routine is running. Create the backup after it finishes.')
                        return b.backup()
                return b.backup()
        if action == 'improvement-propose':
            from improvements import propose
            return propose(b, p['skill_id'], p['feedback'], p.get('session', ''))
        if action == 'improvement-apply':
            from improvements import apply
            return apply(b, p['id'])
        if action == 'routine-run':
            if self.routine_engine is None: raise ValueError('Local routines are not configured.')
            return self.routine_engine.request_run(p['id'], key=p.get('key') or request_id)
        if action == 'archive-research':
            from archive_research import capture, capture_source
            links = {'project_id': p.get('project_id', ''), 'skill_ids': p.get('skill_ids')}
            if 'turn_id' in p: return capture(b, p['turn_id'], **links)
            return capture_source(b, p['title'], p['content'], p['provenance'], p['request_key'], **links)
        raise ValueError('Unsupported operation.')

    def process(self, request, recovering=False):
        request_id = request['id']
        if self.queue.receipt(request_id):
            return
        try:
            validate(request['action'], request['payload'])
            self.queue.path('requests', request_id)
            if not recovering:
                begun = self.queue.path('begun', request_id)
                if begun.exists(): return
                atomic_json(begun, {'id': request_id, 'begun_at': stamp(), 'action': request['action']})
            result = self.dispatch(request['action'], request['payload'], request_id)
        except (ValueError, KeyError, TypeError) as error:
            self._finish(request, error=str(error), state='failed', http_status=400)
        except Exception as error:
            self._finish(request, error=str(error) if isinstance(error, (RuntimeError, TimeoutError, InterruptedError)) else 'The backend could not complete this request. Inspect its retained command receipt.', state='failed', http_status=503)
        else:
            # Publication is derived work. A publication failure must not repeat a
            # successful model call, save, acceptance or push.
            if request['action'] in {'save', 'creative-save', 'retain', 'index', 'improvement-propose', 'improvement-apply', 'archive-research'} or request['action']=='chat' and isinstance(result,dict) and result.get('memory_saved'):
                try:
                    from check_map import rebuild, check
                    with self.routine_engine.exclusive() if self.routine_engine is not None else nullcontext(True) as acquired:
                        if not acquired: raise ValueError('Another local routine is updating the map.')
                        rebuild(self.brain.root)
                        report = check(self.brain.root)
                        if not report.get('ok'): raise ValueError('; '.join(report.get('errors', [])))
                except Exception as error:
                    if isinstance(result, dict): result = result | {'publication_warning':'Your changes were saved, but the navigation map needs review: '+str(error)}
            try:
                if request['action']=='chat' and isinstance(result,dict) and result.get('mode') in {'l1_reuse','l1_lookup'} and result.get('model_calls')==0 and not result.get('memory_saved'):
                    try: self.publisher.publish_chat(request['payload']['session'])
                    except Exception: self.publisher.publish()
                else:
                    self.publisher.publish(refresh_git=request['action'] in {'git-save', 'git-push'})
            except Exception as error:
                atomic_json(self.queue.root/'publication-error.json', {'asof': stamp(), 'error': str(error), 'command_id': request_id})
            self._finish(request, result=result)

    def run_once(self):
        for path in sorted((self.queue.root/'requests').glob('*.json'), key=lambda p: p.stat().st_mtime_ns):
            if self.stopped.is_set(): break
            if not REQUEST_ID.fullmatch(path.stem) or self.queue.receipt(path.stem): continue
            request = self._read_request(path)
            if request is not None: self.process(request)

    def run(self):
        while not self.stopped.is_set():
            try:
                self.run_once()
            except Exception as error:
                atomic_json(self.queue.root/'worker-error.json', {'asof': stamp(), 'error': str(error)})
            self.queue.changed.wait(.25)
            self.queue.changed.clear()
