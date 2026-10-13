"""Loopback V2 dashboard: reads published files and appends command requests."""
import argparse
import importlib.util
import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from commands import CommandQueue, CommandWorker, FIELDS, REQUEST_ID, validate
from read_models import ReadModels, Publisher, DOCUMENTS
from http_input import read_json_request
ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT/'vendor/AI-OS-Dashboard-Current-1.0.4'
spec = importlib.util.spec_from_file_location('v2_vendor', VENDOR/'server.py')
vendor = importlib.util.module_from_spec(spec); spec.loader.exec_module(vendor)
TOKEN = secrets.token_urlsafe(32)
READER = None
QUEUE = None

class Handler(vendor.Handler):
    def published(self, name):
        value = READER.read(name)
        self._json(200, value, READER.headers(value))

    def do_GET(self):
        if not self._host_ok():
            self._json(403, {'error':'Local host only.'}); return
        uri = urlsplit(self.path); route = uri.path; query = parse_qs(uri.query)
        first = lambda name, default='': query.get(name, [default])[0]
        try:
            if route == '/creative':
                html=(ROOT/'app/creative.html').read_text(encoding='utf-8').replace('__TOKEN__',TOKEN)
                self._reply(200,html.encode('utf-8'),'text/html; charset=utf-8'); return
            if route == '/creative-timeline.js':
                self._reply(200,(ROOT/'app/creative-timeline.js').read_bytes(),'application/javascript; charset=utf-8'); return
            if route == '/creative.js':
                self._reply(200,(ROOT/'app/creative.js').read_bytes(),'application/javascript; charset=utf-8'); return
            if route == '/api/creative':
                from creative import PRESETS, STYLES, MODELS, key, read_jobs
                connection=ROOT/'runtime/creative/connection.json'
                self._json(200,{'presets':PRESETS,'styles':STYLES,'models':MODELS,'key_present':bool(key()),'jobs':read_jobs(ROOT),'connection':json.loads(connection.read_text()) if connection.exists() else None}); return
            if route.startswith('/creative/assets/'):
                from creative import asset_path
                path=asset_path(ROOT,route.rsplit('/',1)[-1])
                self._reply(200,path.read_bytes(),{'.png':'image/png','.jpg':'image/jpeg','.webp':'image/webp'}[path.suffix],{'X-Content-Type-Options':'nosniff'}); return
            views = {'/api/state':'state', '/api/brain':'brain', '/api/config':'config', '/api/panels':'panels', '/api/git':'git', '/api/routines':'routines'}
            if route in views:
                self.published(views[route]); return
            if route in {'/data/'+name+'.json' for name in views.values()}:
                self.published(route[6:-5]); return
            if route == '/api/branding':
                self._json(200, {'name':'Company Brain'}); return
            if route == '/api/command':
                id = first('id')
                receipt = QUEUE.receipt(id)
                if receipt is None:
                    request = QUEUE.path('requests', id)
                    if not request.exists():
                        self._json(404, {'error':'This request has not been recorded.'}); return
                    receipt = {'id':id, 'state':'running' if QUEUE.path('begun',id).exists() else 'queued', 'ok':False}
                self._json(200, receipt); return
            if route in {'/api/messages','/api/chat-traces','/api/run','/api/history'}:
                view = READER.read('details')
                if route == '/api/messages':
                    session = READER.valid_session(first('session','main'))
                    result = view['messages'].get(session, [])
                elif route == '/api/chat-traces':
                    session = READER.valid_session(first('session','main'))
                    result = view['traces'].get(session, [])
                elif route == '/api/history':
                    result = view['history'].get(READER.valid_record(first('kind'), first('id')), [])
                else:
                    id = first('id')
                    if not REQUEST_ID.fullmatch(id): raise ValueError('Invalid run identity.')
                    if id not in view['runs']: raise ValueError('This run is not in the published records.')
                    result = view['runs'][id]
                self._json(200, result, READER.headers(view, session if route in {'/api/messages','/api/chat-traces'} else None)); return
            if route in {'/api/file','/api/artifact'} or route in DOCUMENTS:
                view = READER.read('files')
                if route in DOCUMENTS:
                    result = view['documents'].get(route)
                elif route == '/api/file':
                    result = view['nodes'].get(first('path'))
                else:
                    id, step = first('run'), first('step','0')
                    if not REQUEST_ID.fullmatch(id) or not step.isdigit() or len(step)>4: raise ValueError('Invalid saved document identity.')
                    result = view['artifacts'].get(id+'/'+str(int(step)))
                if result is None: raise ValueError('Only published project documents can be opened.')
                self._reply(200, result.encode('utf-8'), 'text/plain; charset=utf-8', READER.headers(view)); return
            if route in ('/','/index.html'):
                html = (VENDOR/'index.html').read_text(encoding='utf-8')
                html = html.replace('CLAUDE.md','BRAIN.md').replace('CLAUDE.MD','BRAIN.MD').replace('~/.claude/skills','project skills/')
                html = html.replace('Dashboard template · sample data','Company Brain · published project records').replace("'Dashboard template · '","'Company Brain · '")
                html = html.replace("'Europe/London':'UTC'", "'Europe/London':'Europe/London'")
                overlay = (ROOT/'app/workspace.html').read_text(encoding='utf-8').replace('__TOKEN__', TOKEN)
                html = html.replace('.then(window.__boot)', '.then(br=>window.__boot(window.prepareCompanyBrainGraph ? window.prepareCompanyBrainGraph(br) : br))')
                html = html.replace('</body>', overlay+'</body>') if '</body>' in html else html+overlay
                self._reply(200, html.encode(), 'text/html; charset=utf-8'); return
            if route in vendor.STATIC:
                super().do_GET(); return
            self._json(404, {'error':'This route is not part of the local dashboard.'})
        except (ValueError, KeyError, IndexError) as error:
            self._json(400, {'error':str(error)})
        except FileNotFoundError:
            self._json(503, {'error':'The backend has not published this view yet.'})
        except Exception:
            self._json(500, {'error':'The published view could not be read. Its source files are preserved.'})

    def do_POST(self):
        if not self._host_ok() or self.headers.get('X-Brain-Token') != TOKEN:
            self._json(403, {'error':'Local session required.'}); return
        if self.headers.get('Origin') not in (None, f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'):
            self._json(403, {'error':'Origin denied.'}); return
        try:
            if not self.path.startswith('/api/') or self.path[5:] not in FIELDS: raise ValueError('Unsupported operation.')
            action = self.path[5:]
            _, payload = read_json_request(self)
            validate(action, payload)
            if action == 'search':
                self._json(200, READER.search(payload.get('query',''))); return
            request_id = QUEUE.enqueue(action, payload, request_id=self.headers.get('X-Brain-Request-ID'))
            receipt = QUEUE.wait(request_id, timeout=400)
            if receipt['ok']:
                self._json(200, receipt['result'], {'X-Command-ID':request_id})
            else:
                self._json(receipt['http_status'], {'error':receipt['error'], 'request_id':request_id, 'state':receipt['state']}, {'X-Command-ID':request_id})
        except (ValueError, KeyError, TypeError) as error:
            self._json(400, {'error':str(error)})
        except Exception:
            self._json(503, {'error':'The request could not be recorded. Existing files were retained.'})

def start_backend(root, queue):
    """Start local workers independently of HTTP. No effects live in Handler."""
    from brain import Brain
    from bootstrap import seed
    from routine_engine import RoutineEngine
    from map_graph import build_graph, approved_source_paths
    worker = CommandWorker(None, queue, None)
    worker._acquire_lease()
    publisher = routines = None
    try:
        brain = Brain(root); seed(brain)
        routines = RoutineEngine(root)
        publisher = Publisher(brain, graph_provider=lambda:build_graph(root, brain), source_paths=lambda:approved_source_paths(root), routine_engine=routines)
        worker.brain, worker.publisher, worker.routine_engine = brain, publisher, routines
        publisher.start()
        worker.start()
        routines.start()
        return worker, publisher, routines
    except Exception:
        if routines: routines.close()
        worker.stop()
        if publisher: publisher.stop()
        raise

def main():
    global READER, QUEUE
    parser = argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=14699)
    parser.add_argument('--backend-only',action='store_true',help='Run the local backend without serving a dashboard.')
    args = parser.parse_args()
    READER = ReadModels(ROOT); QUEUE = CommandQueue(ROOT)
    server = None if args.backend_only else vendor.Server(('127.0.0.1',args.port),ROOT/'data',ROOT)
    worker = publisher = routines = None
    try:
        worker, publisher, routines = start_backend(ROOT,QUEUE)
        (ROOT/'runtime/codex-dashboard.pid').write_text(str(os.getpid()),encoding='ascii')
        if server:
            server.RequestHandlerClass = Handler
            print(f'Company Brain: http://127.0.0.1:{server.server_port}/',flush=True)
            server.serve_forever()
        else:
            print('Company Brain local backend running without the dashboard.',flush=True)
            worker.stopped.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if routines:routines.close()
        if worker:worker.stop()
        if publisher:publisher.stop()
        if server:server.server_close()
if __name__=='__main__':main()
