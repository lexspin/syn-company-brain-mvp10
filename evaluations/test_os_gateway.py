"""Exercise the real gateway against an isolated upstream HTTP server."""
import http.client
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
from os_gateway import make_handler, decorate
from connection_view import connections


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.fixture = tempfile.TemporaryDirectory()
        self.source_root = Path(self.fixture.name)
        self.catalog_path = self.source_root/'company/catalogs/hermes-public-skills.json'
        self.catalog_path.parent.mkdir(parents=True)
        commit = 'a'*40; repository = 'NousResearch/hermes-agent'; skills = []
        for name, category in [('source-research', 'research'), ('workflow-review', 'productivity')]:
            path = f'skills/{category}/{name}/SKILL.md'
            skills.append({'path': path, 'name': name, 'description': name+' procedure', 'category': category,
                'distribution': 'skills', 'size_bytes': 100, 'sha256': 'b'*64, 'git_blob_sha1': 'c'*40,
                'source_url': f'https://github.com/{repository}/blob/{commit}/{path}',
                'raw_url': f'https://raw.githubusercontent.com/{repository}/{commit}/{path}',
                'retrieval_status': 'retrieved-hash-verified', 'git_blob_hash_verified': True,
                'dependency_trust': {'status': 'not-installed-not-executed', 'signals': []},
                'brain_fit': {'classification': 'method-adaptation-candidate', 'validation_status': 'not-evaluated'},
                'support_files': []})
        self.catalog_path.write_text(json.dumps({'schema_version': 1, 'repository': repository, 'commit': commit,
            'created_at': datetime.now(timezone.utc).isoformat(), 'tree_response_sha256': 'd'*64,
            'tree_api_url': f'https://api.github.com/repos/{repository}/git/trees/{commit}?recursive=1',
            'summary': {'tree_truncated': False, 'skill_md_entries': 2, 'retrieved_hash_verified': 2, 'retrieval_failed': 0},
            'skills': skills}), encoding='utf-8')
        self.calls = []
        calls = self.calls
        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self):
                calls.append(('GET', self.path))
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(b'<html><body class="ready">Company Brain <small>MVP01</small><nav>Map Projects Skills</nav></body></html>')
            def do_POST(self):
                body=self.rfile.read(int(self.headers['Content-Length']))
                calls.append(('POST',self.path,dict(self.headers),json.loads(body)))
                if self.path == '/api/disconnect':
                    self.close_connection=True; return
                self.send_response(200 if self.headers.get('X-Brain-Token') == 'valid' else 403)
                self.send_header('Content-Type','application/json')
                self.send_header('X-Command-ID',self.headers['X-Brain-Request-ID'])
                self.end_headers();self.wfile.write(b'{"saved":true}')
        self.upstream=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
        self.gateway=ThreadingHTTPServer(('127.0.0.1',0),make_handler(source_root=self.source_root,upstream_port=self.upstream.server_port))
        self.threads=[]
        for server in (self.upstream,self.gateway):
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();self.threads.append(thread)

    def tearDown(self):
        for server in (self.gateway,self.upstream):server.shutdown();server.server_close()
        for thread in self.threads:thread.join()
        self.fixture.cleanup()

    def request(self,method,path,body=None,headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.gateway.server_port,timeout=3)
        connection.request(method,path,body=body,headers=headers or {})
        response=connection.getresponse(); result=(response.status,dict(response.getheaders()),response.read().decode())
        connection.close();return result

    def test_full_interface_not_replaced_by_summary(self):
        status,headers,body=self.request('GET','/')
        self.assertEqual(status,200);self.assertIn('Map Projects Skills',body)
        self.assertIn('V9 · Pre Alpha',body);self.assertIn('href="/executive"',body)
        self.assertEqual(headers['Cache-Control'],'no-store')

    def test_vendor_runtime_title_uses_current_release(self):
        source = "<title>Old</title><script>document.title=data.name+' Dashboard | Current';</script>"
        body = decorate(source)
        self.assertIn("document.title='V9 Pre Alpha · Company Brain';", body)
        self.assertNotIn("data.name+' Dashboard | Current'", body)

    def test_static_refresh_reuses_native_timer_and_live_defers_to_inspection(self):
        source = "async function checkBrain(){fetch('/api/brain')}" + "setInterval(()=>{if(document.visibilityState==='visible')checkBrain()},600000);"
        body = decorate(source)
        self.assertIn("get('live')==='1')return;", body)
        self.assertIn("checkBrain()},30000);", body)
        self.assertEqual(body.count('setInterval('), 1)
        self.assertIn("fetch('/api/brain')", body)

    def test_maps_and_live_have_separate_links_and_legacy_bookmark_redirects(self):
        body = decorate('<html><body>Existing map</body></html>')
        self.assertIn('href="/?area=maps&amp;live=0"', body)
        self.assertIn('Maps &amp; Links', body)
        self.assertIn('href="/?area=maps&amp;live=1"', body)
        status, headers, body = self.request('GET', '/live?unused=legacy')
        self.assertEqual(status, 302)
        self.assertEqual(headers['Location'], '/?area=maps&live=1')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(body, '')
        self.assertEqual(self.calls, [])

    def test_pinned_timeline_assets_load_before_map_without_remote_scripts(self):
        source = '<meta charset="utf-8"><script>function draw(ts){try{drawBody(ts)}</script>'
        body = decorate(source)
        vendor = '/third-party/vis-timeline/8.5.4/vis-timeline-graph2d.min.js'
        self.assertLess(body.index(vendor), body.index('/map-live.js'))
        self.assertNotIn('https://', body)
        for path, mime in [(vendor, 'javascript'), (vendor.replace('.js', '.css'), 'text/css')]:
            status, headers, data = self.request('GET', path)
            self.assertEqual(status, 200)
            self.assertIn(mime, headers['Content-Type'])
            self.assertGreater(len(data), 10000)
        for path in ['/third-party/../os_gateway.py', '/third-party/vis-timeline/8.5.4/PROVENANCE.json']:
            self.assertEqual(self.request('GET', path)[0], 404)
        self.assertEqual(self.calls, [])

    def test_current_release_documentation_is_served_without_upstream(self):
        for path in ('/docs/V9-PRE-ALPHA.md', '/docs/V9-VALIDATION.md', '/docs/REVIEW-HANDOFF.md'):
            status, headers, body = self.request('GET', path)
            self.assertEqual(status, 200)
            self.assertIn('text/plain', headers['Content-Type'])
            self.assertTrue(body.startswith('# '))
        self.assertEqual(self.calls, [])

    def test_command_preserves_identity_body_and_backend_authority(self):
        identity='gateway-test-123456'
        status,headers,_=self.request('POST','/api/save','{"version":4}',{
            'Origin':f'http://127.0.0.1:{self.gateway.server_port}',
            'X-Brain-Token':'valid','X-Brain-Request-ID':identity})
        self.assertEqual(status,200);self.assertEqual(headers['X-Command-ID'],identity)
        self.assertEqual(len(self.calls),1);self.assertEqual(self.calls[0][3],{'version':4})
        self.assertEqual(self.calls[0][2]['Origin'],f'http://127.0.0.1:{self.upstream.server_port}')
        self.assertEqual(self.request('POST','/api/save','{}',{'X-Brain-Token':'invalid'})[0],403)

    def test_foreign_origin_host_missing_token_and_oversize_are_denied(self):
        for headers in ({'Origin':'https://evil.example','X-Brain-Token':'valid'},
                        {'Host':'evil.example','X-Brain-Token':'valid'},{}):
            self.assertEqual(self.request('POST','/api/save','{}',headers)[0],403)
        self.assertEqual(self.request('GET','/',headers={'Host':'evil.example'})[0],403)
        rejected, headers, body = self.request('POST','/api/save','x'*200001,{'X-Brain-Token':'valid'})
        self.assertEqual(rejected, 400)
        self.assertEqual(int(headers['Content-Length']), len(body.encode('utf-8')))
        self.assertIn('Invalid request body', body)
        self.assertEqual(self.calls,[])

    def test_uncertain_effect_returns_identity_without_retry(self):
        status,_,body=self.request('POST','/api/disconnect','{}',{'X-Brain-Token':'valid'})
        data=json.loads(body);self.assertEqual(status,503);self.assertEqual(data['state'],'uncertain')
        self.assertEqual(len(self.calls),1)
        self.assertEqual(data['request_id'],self.calls[0][2]['X-Brain-Request-ID'])

    def test_invalid_route_json_and_request_id_do_not_reach_backend(self):
        for path,body,headers in [('/api/save?other=1','{}',{}),('/api/save','not-json',{}),
                                  ('/api/save','{}',{'X-Brain-Request-ID':'bad'})]:
            self.assertEqual(self.request('POST',path,body,{'X-Brain-Token':'valid',**headers})[0],400)
        self.assertEqual(self.calls,[])

    def test_decoration_preserves_body_attributes_and_vendor_content(self):
        source='<html><body class="map"><canvas id="graph"></canvas></body></html>'
        html=decorate(source)
        self.assertIn('<canvas id="graph"></canvas>',html)
        self.assertIn('<body class="map">',html)
        self.assertEqual(html.count('id="mvp02-navigation"'),1)

    def test_implicit_body_upstream_receives_navigation(self):
        html=decorate('<meta charset="utf-8"><section id="workspace">Working tabs</section>')
        self.assertIn('id="mvp02-navigation"',html)
        self.assertIn('/mvp02-navigation.js',html)
        self.assertIn('Working tabs',html)

    def test_connection_catalog_does_not_invent_usage_or_area_assignments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'docs').mkdir()
            (root/'docs/CONNECTION-CATALOG.json').write_text(json.dumps({'observed_at':'2026-10-10','connections':[
                {'id':'exa','tool_names':['mcp__exa__search'],'status':'available-in-codex-host','probe':None}]}))
            state={'objects':[{'kind':'skill','id':'research','data':{'name':'Research','instructions':'Use mcp__exa__search'}},
                              {'kind':'project','id':'example','data':{'name':'An example containing exa'}},
                              {'kind':'skill','id':'old','archived':True,'data':{'connection_ids':['exa']}}]}
            view=connections(root,state)
            self.assertFalse(view['live_health_checked'])
            row=view['connections'][0];self.assertIsNone(row['probe'])
            self.assertEqual([r['id'] for r in row['related']],['research'])
            self.assertEqual(row['related'][0]['relationship'],'Tool reference in instructions')

    def test_catalogue_http_filters_read_local_fixture_without_upstream_or_writes(self):
        before = {str(p.relative_to(self.source_root)): p.read_bytes() for p in self.source_root.rglob('*') if p.is_file()}
        for query, name in [('/api/harness-catalog?query=source-research&category=research&limit=1', 'source-research'),
                            ('/api/harness-catalog?category=productivity&limit=32', 'workflow-review')]:
            status, headers, body = self.request('GET', query)
            self.assertEqual(status, 200); self.assertEqual(headers['Cache-Control'], 'no-store')
            result = json.loads(body); self.assertEqual(result['skills_total'], 2)
            self.assertEqual(result['skills'][0]['name'], name); self.assertEqual(result['matches_total'], 1)
            self.assertEqual(result['skills'][0]['adoption_status'], 'catalogued-not-installed-not-executed')
        status, _, body = self.request('GET', '/api/harness-catalog?category=unknown')
        self.assertEqual(status, 200); self.assertEqual(json.loads(body)['skills'], [])
        self.assertEqual(self.calls, [])
        self.assertEqual(before, {str(p.relative_to(self.source_root)): p.read_bytes() for p in self.source_root.rglob('*') if p.is_file()})

    def test_catalogue_unknown_duplicate_and_invalid_filters_never_reach_upstream(self):
        routes = ['/api/harness-catalog?unknown=x', '/api/harness-catalog?query=a&query=b',
                  '/api/harness-catalog?limit=1&limit=2', '/api/harness-catalog?query=&category=&limit=1&query=x',
                  '/api/harness-catalog?limit=0', '/api/harness-catalog?limit=33',
                  '/api/harness-catalog?limit=nan', '/api/harness-catalog?limit=',
                  '/api/harness-catalog?query='+'x'*1001, '/api/harness-catalog?category='+'x'*81]
        for route in routes:
            with self.subTest(route=route[:100]):
                status, _, body = self.request('GET', route)
                self.assertEqual(status, 400); self.assertIn('No resource was executed', json.loads(body)['error'])
        self.assertEqual(self.request('GET','/api/harness-catalog',headers={'Host':'evil.example'})[0],403)
        self.assertEqual(self.calls, [])

    def test_catalogue_absent_and_corrupt_metadata_fail_without_forwarding(self):
        self.catalog_path.write_text('{bad}', encoding='utf-8')
        self.assertEqual(self.request('GET','/api/harness-catalog')[0],400)
        self.catalog_path.unlink()
        status, _, body = self.request('GET','/api/harness-catalog')
        self.assertEqual(status,503); self.assertIn('unavailable',json.loads(body)['error'])
        self.assertEqual(self.calls, [])

    def test_catalogue_static_page_and_script_are_local_read_only_routes(self):
        status, headers, html = self.request('GET','/harness')
        self.assertEqual(status,200); self.assertIn('text/html',headers['Content-Type'])
        self.assertIn('Local adaptations',html); self.assertIn('Pinned upstream resources',html)
        self.assertIn('not been installed, executed or evaluated',html)
        status, headers, script = self.request('GET','/harness-catalog.js')
        self.assertEqual(status,200); self.assertIn('javascript',headers['Content-Type'])
        self.assertIn('/api/harness-catalog?',script); self.assertEqual(self.calls, [])


if __name__=='__main__':unittest.main()
