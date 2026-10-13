"""MVP02 read-only preview. Never starts a Brain writer or routine engine."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from read_models import ReadModels
from os_control import overview

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT.parent/'V2'


def make_handler(source_root):
    reader = ReadModels(source_root)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, value, mime='application/json; charset=utf-8'):
            body = value if isinstance(value, bytes) else json.dumps(value).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers(); self.wfile.write(body)

        def do_GET(self):
            if self.headers.get('Host') not in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'):
                self.reply(403, {'error':'Local host only.'}); return
            path = urlsplit(self.path).path
            if path in ('/', '/os'):
                self.reply(200,(ROOT/'app/os.html').read_bytes(),'text/html; charset=utf-8')
            elif path == '/os.js':
                self.reply(200,(ROOT/'app/os.js').read_bytes(),'application/javascript; charset=utf-8')
            elif path in ('/executive-widgets.js','/executive-style.css'):
                self.reply(200,(ROOT/'app'/path[1:]).read_bytes(),'text/css; charset=utf-8' if path.endswith('.css') else 'application/javascript; charset=utf-8')
            elif path in ('/api/os-overview','/api/state'):
                try:
                    state = reader.read('state')
                    if Path(state.get('root','')).resolve() != Path(source_root).resolve():
                        raise ValueError('Source workspace identity does not match.')
                    self.reply(200, overview(state) if path == '/api/os-overview' else state)
                except (OSError, ValueError, KeyError, TypeError):
                    self.reply(503, {'error':'The existing Brain publication is unavailable or invalid. No work was started.'})
            else:
                self.reply(404, {'error':'Unknown preview page.'})

        def do_POST(self):
            self.reply(405, {'error':'Read-only preview. Work through native Codex or the existing dashboard.'})
    return Handler


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=14702)
    parser.add_argument('--source-root',type=Path,default=CANONICAL)
    args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),make_handler(args.source_root.resolve()))
    print(f'MVP02 read-only view: http://127.0.0.1:{server.server_port}/',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
