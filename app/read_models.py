"""Backend-published file views, and a dashboard reader with no database access.

These files are disposable projections. Records, conversations, receipts and
artifacts remain owned by the backend even when the dashboard is not running.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from commands import atomic_json, stamp, ID, SESSION, REQUEST_ID
from presentation import display_records

NAMES = {'state', 'brain', 'config', 'panels', 'details', 'files', 'git', 'routines'}
DOCUMENTS = {'/README.md', '/docs/VALIDATION.md', '/docs/ARCHITECTURE.md'}
MAX_TEXT = 256*1024


def metadata(asof, stale_after=30):
    age = max(0, (datetime.now(timezone.utc)-datetime.fromisoformat(asof)).total_seconds())
    return {'asof': asof, 'age_seconds': round(age, 1), 'stale': age > stale_after,
            'stale_after_seconds': stale_after, 'source': 'backend-published files'}


class ReadModels:
    """Read existing projections only. Construction performs no writes."""
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.data = self.root/'data'

    def read(self, name):
        if name not in NAMES:
            raise ValueError('Unknown published view.')
        path = self.data/(name+'.json')
        if not path.resolve().is_relative_to(self.root):
            raise ValueError('Published view path is outside this workspace.')
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict) or not isinstance(value.get('_view'), dict):
            raise ValueError('Published view is missing its source timestamp.')
        value['_view'] = metadata(value['_view']['asof'], value['_view'].get('stale_after_seconds', 30))
        return value

    def headers(self, view, session=None):
        current = view['_view']
        if session is not None and session in view.get('_chat_views', {}):
            chat = view['_chat_views'][session]
            current = metadata(chat['asof'], chat.get('stale_after_seconds', 30))
        return {'X-Data-As-Of': current['asof'],
                'X-Data-Stale': str(current['stale']).lower()}

    @staticmethod
    def valid_session(session):
        if not isinstance(session, str) or not SESSION.fullmatch(session):
            raise ValueError('Invalid conversation ID.')
        return session

    @staticmethod
    def valid_record(kind, id):
        if kind not in {'agent', 'skill', 'memory', 'loop', 'stack', 'project'} or not isinstance(id, str) or not ID.fullmatch(id):
            raise ValueError('Invalid record identity.')
        return kind+':'+id

    def search(self, query, limit=8):
        if not isinstance(query, str) or len(query) > 12000:
            raise ValueError('Search must be at most 12000 characters.')
        state = self.read('state')
        tokens = set(re.findall(r'\w+', query.lower()))-{'a','an','and','are','as','at','be','by','for','from','i','in','is','it','me','my','of','on','or','that','the','this','to','was','we','with','you'}
        scored = []
        for row in state['objects']:
            if row['kind'] != 'memory' or not state['memory_freshness'].get(row['id'], {}).get('current'):
                continue
            text = ' '.join(str(row['data'].get(k, '')) for k in ('name','content','source')).lower()
            score = len(tokens & set(re.findall(r'\w+', text)))
            escaped = re.escape(row['id'])
            explicit = 2 if re.search(r'(?:memory:|\[)'+escaped+r'(?![a-z0-9-])', query.lower()) else int(bool(re.search(r'(?<![a-z0-9-])'+escaped+r'(?![a-z0-9-])', query.lower())))
            if explicit or score:
                scored.append((explicit, score, row))
        return [r for _, _, r in sorted(scored, key=lambda p: (-p[0], -p[1], p[2]['id']))[:limit]]


class Publisher:
    """The backend owns publication; never call this from a dashboard handler."""
    def __init__(self, brain, graph_provider=None, panels_provider=None,
                 source_roots=None, source_paths=None, routine_engine=None, interval=5):
        self.brain = brain
        self.root = Path(brain.root).resolve()
        self.data = self.root/'data'
        self.graph_provider, self.panels_provider = graph_provider, panels_provider
        self.routine_engine = routine_engine
        self.source_roots = [Path(p).resolve() for p in (source_roots or [self.root])]
        self.source_paths = source_paths
        self.approved_paths = set()
        self.interval = interval
        self.lock = threading.RLock()
        self.stopped = threading.Event()
        self.thread = None
        self.git_cache, self.git_checked = None, 0

    def _view(self, value, asof, stale_after=30):
        return value | {'_view': {'asof': asof, 'stale_after_seconds': stale_after,
                                 'source': 'backend-published files'}}

    def _text(self, raw_path):
        path = Path(raw_path)
        if not path.is_absolute(): path = self.root/path
        path = path.resolve()
        if path not in self.approved_paths and not any(path.is_relative_to(root) for root in self.source_roots):
            return None
        supported = path.suffix.lower() in {'.md', '.txt'} or (path.suffix.lower() in {'.json','.py','.html','.js','.ps1'} and path in self.approved_paths)
        if not supported or not path.is_file() or path.stat().st_size > MAX_TEXT:
            return None
        try: return path.read_text(encoding='utf-8')
        except (UnicodeError, OSError): return None

    def _git(self, force=False):
        if force or self.git_cache is None or time.monotonic()-self.git_checked > 60:
            try: self.git_cache = self.brain.git()
            except Exception as error: self.git_cache = {'error': str(error), 'remote_url': '', 'branch': ''}
            self.git_cache = self._view(self.git_cache, stamp(), 120)
            self.git_checked = time.monotonic()
        return self.git_cache

    def publish_chat(self, session):
        """Refresh one deterministic chat without rebuilding unchanged source views.

        Full-view timestamps remain unchanged: a fresh conversation is not proof
        that records, graph, histories or files were refreshed. Missing/corrupt
        views raise so the command worker can fall back to full publication.
        """
        ReadModels.valid_session(session)
        with self.lock:
            reader = ReadModels(self.root)
            state, details = reader.read('state'), reader.read('details')
            if not isinstance(state.get('sessions'), list) or not all(isinstance(details.get(k), dict) for k in ('messages', 'traces', 'runs', 'history')):
                raise ValueError('Published chat views need a full refresh.')
            with self.brain.connect() as connection:
                messages = [dict(row) for row in connection.execute('SELECT role,text,created FROM messages WHERE session=? ORDER BY id', (session,))]
            traces = self.brain.chat_turns(session)
            if session == 'briefs' and self.routine_engine is not None:
                messages = sorted(messages + self.routine_engine.messages(), key=lambda row: row['created'])
            asof = stamp()
            details['messages'][session], details['traces'][session] = messages, traces
            chat_view = {'asof': asof, 'stale_after_seconds': 30, 'source': 'backend-published files'}
            details.setdefault('_chat_views', {})[session] = chat_view
            state.setdefault('_chat_views', {})[session] = chat_view
            state['sessions'] = [row for row in state['sessions'] if row['session'] != session]
            if messages:
                state['sessions'].append({'session': session, 'updated': max(row['created'] for row in messages)})
            state['worker_busy'] = self.brain.active.locked()
            atomic_json(self.data/'details.json', details)
            atomic_json(self.data/'state.json', state)
            return asof

    def publish(self, refresh_git=False):
        with self.lock:
            b, asof = self.brain, stamp()
            self.approved_paths = {Path(p).resolve() for p in (self.source_paths() if callable(self.source_paths) else self.source_paths or [])}
            state = b.status()
            state['objects'] = display_records(state['objects'])
            graph = self.graph_provider() if self.graph_provider else b.graph()
            state['record_paths'] = {node['path']: node['record_id'] for node in graph['nodes'] if node.get('path') and node.get('record_id')}
            details = {'messages': {}, 'traces': {}, 'runs': {}, 'history': {}}
            with b.connect() as connection:
                messages = [dict(r) for r in connection.execute('SELECT session,role,text,created FROM messages ORDER BY id')]
                histories = [dict(r) for r in connection.execute('SELECT * FROM versions ORDER BY kind,id,version DESC')]
                run_ids = [r[0] for r in connection.execute('SELECT id FROM runs ORDER BY created DESC')]
            for message in messages:
                session = message.pop('session')
                details['messages'].setdefault(session, []).append(message)
            for row in histories:
                details['history'].setdefault(row['kind']+':'+row['id'], []).append(row)
            for session in details['messages']:
                details['traces'][session] = b.chat_turns(session)
            for id in run_ids:
                details['runs'][id] = b.run(id)

            routines = {'routines': [], 'recent': [], 'asof': None, 'available': False}
            if self.routine_engine is not None:
                routines = self.routine_engine.status()
                briefs = self.routine_engine.messages()
                if briefs:
                    combined = sorted(details['messages'].get('briefs', []) + briefs, key=lambda message: message['created'])
                    details['messages']['briefs'] = combined
                    details['traces'].setdefault('briefs', [])
                    state['sessions'] = [s for s in state['sessions'] if s['session'] != 'briefs'] + [{'session': 'briefs', 'updated': combined[-1]['created']}]

            files = {'documents': {}, 'nodes': {}, 'artifacts': {}}
            for route in DOCUMENTS:
                path = self.root/route.lstrip('/')
                text = self._text(path)
                if text is not None: files['documents'][route] = text
            brain_text = self._text(self.root/'BRAIN.md')
            if brain_text is not None: files['nodes']['BRAIN.md'] = brain_text
            for record in state['objects']:
                files['nodes']['record/'+record['kind']+':'+record['id']] = json.dumps(record, ensure_ascii=False, indent=2)
            for id, run in details['runs'].items():
                files['nodes']['run/'+id] = json.dumps(run, ensure_ascii=False, indent=2)
                for index, output in enumerate(run['outputs']):
                    path = (self.root/output['path']).resolve()
                    if path.is_relative_to(self.root/'deliverables'):
                        text = self._text(path)
                        if text is not None: files['artifacts'][id+'/'+str(index)] = text
            for node in graph['nodes']:
                raw = node.get('path')
                if isinstance(raw, str) and raw and raw not in files['nodes']:
                    text = self._text(raw)
                    if text is not None: files['nodes'][raw] = text
                node['source_available'] = bool(raw and raw in files['nodes'])

            today = asof[:10]
            config = {'gate_start': today, 'gate_end': today, 'review': today,
                      'target': 'Reviewed work and reusable knowledge', 'clocks': [['London', 'Europe/London']],
                      'focus': {'primary': 'Company Brain', 'start': today, 'updated': today,
                                'duration': 'Local', 'summary': 'Your team, knowledge and work.',
                                'secondary': 'Review prepared work.', 'next': 'Use the workspace navigation.',
                                'waiting': 'Cloud execution is not configured.', 'note': 'Files remain owned by the local backend.',
                                'completed': [], 'views': 'Published project records', 'progress_label': 'Saved records',
                                'progress_detail': 'Source-linked knowledge', 'prep_heading': 'Work', 'wait_heading': 'Connections'}}
            panels = {'data_mode': 'local',
                      'snapshot': {'rendered': asof, 'plans': {'days': []},
                                   'pulse': {'week_from': today, 'quotas': {}, 'counters': {'records': len(state['objects']), 'runs': len(state['runs'])},
                                             'last_row': {'date': today, 'note': 'Published local records.'}},
                                   'actions': {'overdue': [], 'count_overdue': 0, 'lanes': {}}, 'mail': {'status': 'not-connected'}},
                      'runs': {'routines': routines.get('routines', routines.get('rows', [])), 'feed': routines.get('recent', []), 'today': {}, 'yesterday': {}},
                      'system': {'runner_last_tick': routines.get('last_tick', routines.get('asof')), 'brain_generated': graph.get('generated'), 'head': 'local'}}
            if self.panels_provider: panels = self.panels_provider()
            for name, value in {'state': state, 'brain': graph, 'config': config, 'panels': panels,
                                'details': details, 'files': files, 'routines': routines}.items():
                atomic_json(self.data/(name+'.json'), self._view(value, asof))
            atomic_json(self.data/'git.json', self._git(refresh_git))
            return asof

    def start(self):
        self.publish()
        self.thread = threading.Thread(target=self.run, name='company-brain-publication', daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped.set()
        if self.thread: self.thread.join(timeout=2)

    def run(self):
        while not self.stopped.wait(self.interval):
            try: self.publish()
            except Exception as error:
                # Keep the last successful view visible with its original time.
                atomic_json(self.root/'runtime/publication-error.json', {'asof': stamp(), 'error': str(error)})
