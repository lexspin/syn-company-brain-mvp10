"""V9 Pre Alpha interface backed by the one canonical V2 worker.

This gateway forwards once; it never constructs Brain or retries an effect.
The existing backend still validates its session token and owns commands.
"""
import argparse
import http.client
import json
import re
import uuid
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from os_preview import CANONICAL, ROOT, make_handler as preview_handler
from read_models import ReadModels
from connection_view import connections
from operating_view import operating_view
from live_activity import activity_view, event_history
from live_output import read_output
from harness_catalog import read_catalog
from http_input import read_json_request

REQUEST_ID = re.compile(r'^[A-Za-z0-9_-]{8,100}$')
RESPONSE_HEADERS = ('Content-Type', 'X-Command-ID', 'X-Data-As-Of',
                    'X-Data-Age-Seconds', 'X-Data-Stale')
TIMELINE_ASSETS = {
    '/third-party/vis-timeline/8.5.4/vis-timeline-graph2d.min.js': 'application/javascript; charset=utf-8',
    '/third-party/vis-timeline/8.5.4/vis-timeline-graph2d.min.css': 'text/css; charset=utf-8',
}


def decorate(html):
    """Add navigation without altering licensed files or the working controls."""
    # Licensed source stays intact. Disable ambient/focus traffic in this served
    # knowledge-map view: only the separate evidence view represents activity.
    html = html.replace('const AMB_N=8;', 'const AMB_N=0;')
    # Reuse the native static-map refresh; live owns its inspection-safe refresh.
    html = html.replace('async function checkBrain(){',
                        "async function checkBrain(){if(new URLSearchParams(location.search).get('live')==='1')return;", 1)
    html = html.replace("setInterval(()=>{if(document.visibilityState==='visible')checkBrain()},600000);",
                        "setInterval(()=>{if(document.visibilityState==='visible')checkBrain()},30000);", 1)
    html=html.replace('const N=BR.nodes, L=BR.links, byId=', 'window.CompanyBrainLiveMapRedraw=()=>{drawBody(performance.now());window.CompanyBrainLiveMap?.draw(ctx,N,L,view)};const N=BR.nodes, L=BR.links, byId=',1)
    hook='function draw(ts){try{drawBody(ts)}'
    if hook in html:
        html=html.replace(hook,'function draw(ts){try{drawBody(ts);window.CompanyBrainLiveMap?.draw(ctx,N,L,view)}',1)
        html=html.replace('<meta charset="utf-8">',
            '<meta charset="utf-8"><link rel="stylesheet" href="/third-party/vis-timeline/8.5.4/vis-timeline-graph2d.min.css">'
            '<link rel="stylesheet" href="/map-live.css">'
            '<script defer src="/third-party/vis-timeline/8.5.4/vis-timeline-graph2d.min.js"></script>'
            '<script defer src="/map-live.js"></script>',1)

    html = html.replace('function redraw(){try{drawBody(performance.now())}catch(e){}}', 'function redraw(){try{drawBody(performance.now());window.CompanyBrainLiveMap?.draw(ctx,N,L,view)}catch(e){}}')
    html = html.replace('let motion=!reduce;', 'let motion=false;')
    html = html.replace("motion=v==='1'", 'motion=false')
    html = html.replace('motion=!motion;', 'motion=false;')
    html = html.replace('title="Living motion">motion', 'title="Decorative motion disabled; activity appears in Live Neurolinks" disabled>motion off')
    html = html.replace('Company Brain <small>MVP01</small>',
                        'Company Brain <small>V9 · Pre Alpha</small>')
    html = re.sub(r"<title>.*?</title>", "<title>V9 Pre Alpha · Company Brain</title>", html, count=1)
    html = html.replace("document.title=data.name+' Dashboard | Current';",
                        "document.title='V9 Pre Alpha · Company Brain';")
    html = html.replace("'Graph':'Map'", "'Graph':'MAPS'")
    html = html.replace('href="/docs/VALIDATION.md"', 'href="/docs/MVP02-INTERFACE.md"')
    if '<section id="workspace">' in html:
        html = html.replace('document.body.prepend(W);', 'document.body.prepend(W);window.CompanyBrainOperating.mount(token);', 1)
        html = html.replace("'Graph':'MAPS'", "'Graph':'MAPS','Connections':'Connections','Hubs':'Knowledge Hubs'")
        html = html.replace("else if(tab==='Improvements')improvementsView();",
                            "else if(tab==='Hubs')knowledgeHubsView();else if(tab==='Connections')safe(connectionsView);else if(tab==='Improvements')improvementsView();")
        start, end = html.find('function runsView(){'), html.find('async function runDetail(){')
        if start >= 0 and end > start:
            html = html[:start]+(ROOT/'app/results-view.js').read_text(encoding='utf-8')+'\n'+(ROOT/'app/connections-view.js').read_text(encoding='utf-8')+'\n'+html[end:]
        html = html.replace('Why this needs attention', 'Recorded outcome notes')
        html = html.replace('Your changes are saved here. Keep a checkpoint, send it to your connected GitHub repository, or create a recovery copy.',
                            'These controls save and sync the live V2 workspace. Current interface milestone: V9_Pre_Alpha; earlier branches remain preserved.')
        html = html.replace('<title>Company Brain Dashboard | Current</title>',
                            '<title>V9 Pre Alpha · Company Brain</title>')
        html = html.replace('<meta charset="utf-8">',
                            '<meta charset="utf-8"><script src="/mvp02-navigation.js"></script>',1)
    extra = ('<div id="mvp02-navigation" style="max-width:1440px;margin:auto;'
             'padding:12px 30px;font:14px system-ui;color:#b8dabe">'
             '<a href="/" style="color:inherit">Full workspace</a> · '
             '<a href="/executive" style="color:inherit">Executive overview</a> · '
             '<a href="/?area=maps&amp;live=0" style="color:inherit">Maps &amp; Links</a> · '
             '<a href="/?area=maps&amp;live=1" style="color:inherit">Live Activity</a> · '
             '<a href="/harness" style="color:inherit">Harness resources</a> · '
             '<a href="/creative" style="color:inherit">Video Editor</a> · '
             '<a href="/validation" style="color:inherit">Task paths &amp; checks</a>'
             '<span style="float:right">One connected Company Brain</span></div>')
    if '<section id="workspace">' in html:
        controls='<script src="/operating-controls.js"></script><div id="operating-controls"></div>'
        return html.replace('<section id="workspace">', '<section id="workspace">'+extra+controls, 1)
    html = html.replace('<body>', '<body>'+extra, 1)
    if 'id="mvp02-navigation"' not in html:
        # Upstream may attach attributes to body; insert after that opening tag.
        html = re.sub(r'(<body\b[^>]*>)', lambda m: m[0]+extra, html, count=1)
    if 'id="mvp02-navigation"' not in html:
        html = html.replace('<section id="workspace">', extra+'<section id="workspace">', 1)
    return html


def make_handler(source_root=CANONICAL, upstream_port=14699):
    class Handler(preview_handler(source_root)):
        def local(self):
            return self.headers.get('Host') in (
                f'127.0.0.1:{self.server.server_port}',
                f'localhost:{self.server.server_port}')

        def forward(self, method, body=None, request_id=None):
            connection = http.client.HTTPConnection('127.0.0.1', upstream_port, timeout=410)
            headers = {'Host': f'127.0.0.1:{upstream_port}', 'Accept-Encoding': 'identity'}
            if method == 'POST':
                headers.update({'Content-Type': 'application/json',
                                'X-Brain-Token': self.headers.get('X-Brain-Token', ''),
                                'X-Brain-Request-ID': request_id,
                                'Origin': f'http://127.0.0.1:{upstream_port}'})
            try:
                connection.request(method, self.path, body=body, headers=headers)
                response = connection.getresponse()
                content = response.read()
                content_type = response.getheader('Content-Type', 'application/octet-stream')
                if response.status == 200 and 'text/html' in content_type:
                    content = decorate(content.decode('utf-8')).encode('utf-8')
                self.send_response(response.status)
                for name in RESPONSE_HEADERS:
                    value = response.getheader(name)
                    if value is not None: self.send_header(name, value)
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('X-Frame-Options', 'SAMEORIGIN')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            except (OSError, http.client.HTTPException):
                message = ('The result of this request is not yet known. Check Results before trying again.'
                           if method == 'POST' else
                           'Company Brain is unavailable. Start the existing V2 backend; your data is preserved.')
                self.reply(503, {'error': message, 'request_id': request_id,
                                 'state': 'uncertain' if method == 'POST' else 'unavailable'})
            finally:
                connection.close()

        def do_GET(self):
            if not self.local():
                self.reply(403, {'error': 'Local host only.'}); return
            path = urlsplit(self.path).path
            if path in TIMELINE_ASSETS:
                self.reply(200, (ROOT/'app'/path[1:]).read_bytes(), TIMELINE_ASSETS[path])
            elif path.startswith('/third-party/'):
                self.reply(404, {'error': 'Unknown local asset.'})
            elif path == '/live':
                # Preserve old bookmarks while keeping one current live interface.
                self.send_response(302)
                self.send_header('Location', '/?area=maps&live=1')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', '0')
                self.end_headers()
            elif path == '/harness':
                self.reply(200,(ROOT/'app/harness-catalog.html').read_bytes(),'text/html; charset=utf-8')
            elif path == '/harness-catalog.js':
                self.reply(200,(ROOT/'app/harness-catalog.js').read_bytes(),'application/javascript; charset=utf-8')
            elif path == '/api/harness-catalog':
                try:
                    q=parse_qs(urlsplit(self.path).query,keep_blank_values=True,max_num_fields=3)
                    if set(q)-{'query','category','limit'} or any(len(v)!=1 for v in q.values()):
                        raise ValueError('Unknown or repeated catalogue filter')
                    self.reply(200,read_catalog(source_root,query=q.get('query',[''])[0],
                                              category=q.get('category',[''])[0],limit=int(q.get('limit',['8'])[0])))
                except (ValueError,TypeError):
                    self.reply(400,{'error':'Invalid catalogue filters or source metadata. No resource was executed.'})
                except OSError:
                    self.reply(503,{'error':'The pinned catalogue is unavailable. No resource was executed.'})
            elif path in ('/live.js','/live.css','/map-live.js','/map-live.css'):
                self.reply(200,(ROOT/'app'/path[1:]).read_bytes(),'text/css; charset=utf-8' if path.endswith('.css') else 'application/javascript; charset=utf-8')
            elif path == '/api/live-output':
                try:
                    q=parse_qs(urlsplit(self.path).query)
                    self.reply(200,read_output(source_root,q.get('task',[''])[0],int(q.get('index',['-1'])[0])),'text/plain; charset=utf-8')
                except (OSError,ValueError,KeyError,TypeError):
                    self.reply(400,{'error':'This reported output is not available for a local document preview.'})
            elif path == '/api/native-activity-history':
                try:
                    ident=parse_qs(urlsplit(self.path).query).get('task_id',[''])[0]
                    self.reply(200,event_history(source_root,ident))
                except (OSError,ValueError,KeyError,TypeError):
                    self.reply(400,{'error':'Invalid or unavailable activity history.'})
            elif path == '/api/native-activity':
                try:
                    ident=parse_qs(urlsplit(self.path).query).get('task_id',[''])[0]
                    task=next((t for t in activity_view(source_root)['tasks'] if t['id']=='native:'+ident),None)
                    self.reply(200 if task else 404,task or {'error':'No observed task with that identity.'})
                except (OSError, ValueError, KeyError, TypeError):
                    self.reply(503,{'error':'Activity observations unavailable.'})
            elif path == '/api/live-activity':
                try:
                    self.reply(200,activity_view(source_root))
                except (OSError, ValueError, KeyError, TypeError):
                    self.reply(503,{'error':'Activity observations unavailable. No execution is inferred.'})
            elif path == '/validation':
                self.reply(200,(ROOT/'docs/MVP03-VALIDATION.html').read_bytes(),'text/html; charset=utf-8')
            elif path == '/executive':
                html = (ROOT/'app/os.html').read_text(encoding='utf-8')
                html = html.replace('http://127.0.0.1:14699/creative', '/creative')
                html = html.replace('http://127.0.0.1:14699/', '/')
                self.reply(200, html.encode('utf-8'), 'text/html; charset=utf-8')
            elif path in ('/api/os-overview', '/os.js'):
                super().do_GET()
            elif path in ('/executive-widgets.js','/executive-style.css','/executive-operating.js'):
                self.reply(200,(ROOT/'app'/path[1:]).read_bytes(), 'text/css; charset=utf-8' if path.endswith('.css') else 'application/javascript; charset=utf-8')
            elif path == '/mvp02-navigation.js':
                self.reply(200, (ROOT/'app/mvp02-navigation.js').read_bytes(),
                           'application/javascript; charset=utf-8')
            elif path == '/operating-controls.js':
                self.reply(200, (ROOT/'app/operating-controls.js').read_bytes(), 'application/javascript; charset=utf-8')
            elif path == '/api/os-operating':
                try:
                    state=ReadModels(source_root).read('state')
                    self.reply(200, operating_view(source_root,state))
                except (OSError, ValueError, KeyError, TypeError, AttributeError):
                    self.reply(503, {'error':'Operating settings are unavailable. No setting was changed.'})
            elif path == '/api/os-connections':
                try:
                    state=ReadModels(source_root).read('state')
                    self.reply(200, connections(source_root,state))
                except (OSError, ValueError, KeyError, TypeError):
                    self.reply(503, {'error':'The connection catalog could not be read. No connection was changed.'})
            elif path in ('/docs/MVP02-INTERFACE.md','/docs/HERMES-ADAPTATION.md','/docs/MVP07-HARNESS.md',
                          '/docs/HARNESS-CATALOG.md','/docs/NATIVE-ACTIVITY.md','/docs/SKILL-CURATION.md',
                          '/docs/REVIEWER-MCP.md','/docs/MCP-COMPATIBILITY.md','/docs/LEARNING-CANDIDATES.md',
                          '/docs/PROCEDURE-PROMOTION.md','/docs/ROUTED-EXECUTION.md',
                          '/docs/FABLE-METHODS.md','/docs/CHAT-PLUGIN.md','/docs/MVP07-VALIDATION.md',
                          '/docs/V9-PRE-ALPHA.md','/docs/V9-VALIDATION.md','/docs/V9-MEMORY-CONTEXT.md',
                          '/docs/REVIEW-HANDOFF.md','/docs/MVP08-WORKFLOW-SOURCES.md'):
                self.reply(200,(ROOT/path[1:]).read_bytes(),'text/plain; charset=utf-8')
            elif self.path.startswith('/') and not self.path.startswith('//'):
                self.forward('GET')
            else:
                self.reply(400, {'error': 'Invalid local route.'})

        def do_POST(self):
            if not self.local():
                self.reply(403, {'error': 'Local host only.'}); return
            origins = (f'http://127.0.0.1:{self.server.server_port}',
                       f'http://localhost:{self.server.server_port}')
            if self.headers.get('Origin') not in (None, *origins) or not self.headers.get('X-Brain-Token'):
                self.reply(403, {'error': 'Current local session required.'}); return
            if not re.fullmatch(r'/api/[a-z-]+', self.path):
                self.reply(400, {'error': 'Unsupported operation.'}); return
            try:
                request_id = self.headers.get('X-Brain-Request-ID') or uuid.uuid4().hex
                if not REQUEST_ID.fullmatch(request_id): raise ValueError('Invalid request identity.')
                body, _ = read_json_request(self)
            except (ValueError, UnicodeError):
                self.reply(400, {'error': 'Invalid request body or identity.'}); return
            self.forward('POST', body, request_id)
    return Handler


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=14703)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler())
    print(f'V9 Pre Alpha workspace: http://127.0.0.1:{server.server_port}/', flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
