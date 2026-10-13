"""HTTP boundary checks without models or the live workspace."""
import http.client
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'app'))
from commands import CommandQueue, atomic_json, stamp
from read_models import ReadModels

spec = importlib.util.spec_from_file_location('dashboard_view_test_server', ROOT/'app/server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class DashboardViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'runtime')
        self.root = Path(self.temp.name)
        server.READER = ReadModels(self.root)
        server.QUEUE = CommandQueue(self.root)
        atomic_json(self.root/'data/state.json', {'objects':[], 'memory_freshness':{}, '_view':{'asof':stamp()}})
        atomic_json(self.root/'data/files.json', {'documents':{'/README.md':'# Saved guide'},'nodes':{'BRAIN.md':'# Saved map'},'artifacts':{},'_view':{'asof':stamp()}})
        self.http = server.vendor.Server(('127.0.0.1', 0), self.root/'data', self.root)
        self.http.RequestHandlerClass = server.Handler
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, method, route, payload=None, token=True):
        connection = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=3)
        headers = {'Content-Type':'application/json'}
        if token: headers['X-Brain-Token'] = server.TOKEN
        connection.request(method, route, body=json.dumps(payload) if payload is not None else None, headers=headers)
        response = connection.getresponse()
        raw = response.read().decode()
        data = json.loads(raw) if 'json' in response.getheader('Content-Type','') else raw
        result = response.status, dict(response.headers), data
        connection.close()
        return result

    def test_get_is_served_from_saved_files_without_backend(self):
        code, headers, value = self.request('GET','/api/state')
        self.assertEqual(code, 200)
        self.assertEqual(value['objects'], [])
        self.assertIn('X-Data-As-Of', headers)
        self.assertFalse(list((server.QUEUE.root/'requests').glob('*.json')))

    def test_post_records_request_and_reads_receipt(self):
        payload = {'kind':'memory','id':'report','data':{'name':'Report'}}
        with patch.object(server.QUEUE, 'wait', return_value={'ok':True,'result':{'id':'report','version':1}}):
            code, headers, value = self.request('POST','/api/save',payload)
        self.assertEqual(code, 200)
        self.assertEqual(value['version'], 1)
        id = headers['X-Command-ID']
        saved = json.loads(server.QUEUE.path('requests', id).read_text())
        self.assertEqual(saved['payload'], payload)
        self.assertEqual(self.request('GET','/api/command?id='+id)[2]['state'], 'queued')
        self.assertEqual(server.READER.read('state')['objects'], [])

    def test_mutation_requires_token_and_rejects_arbitrary_actions(self):
        self.assertEqual(self.request('POST','/api/backup',{},token=False)[0], 403)
        self.assertEqual(self.request('POST','/api/shell',{'command':'anything'})[0], 400)
        self.assertFalse(list((server.QUEUE.root/'requests').glob('*.json')))

    def test_document_lookup_is_allowlisted_projection_only(self):
        self.assertEqual(self.request('GET','/api/file?path=BRAIN.md')[2], '# Saved map')
        self.assertEqual(self.request('GET','/README.md')[2], '# Saved guide')
        self.assertEqual(self.request('GET','/api/file?path=../../private.txt')[0], 400)
        self.assertEqual(self.request('GET','/runtime/brain.sqlite3')[0], 404)

    def test_archive_source_accepts_valid_transport_and_command_query_validates_id(self):
        payload = {'title':'Research','content':'Source excerpt','provenance':{'chat_id':'codex-chat'},'request_key':'capture-key-1'}
        with patch.object(server.QUEUE, 'wait', return_value={'ok':True,'result':{'id':'research-1'}}):
            self.assertEqual(self.request('POST','/api/archive-research',payload)[0], 200)
        self.assertEqual(self.request('GET','/api/command?id=../private')[0], 400)
        self.assertEqual(self.request('GET','/api/command?id='+'d'*32)[0], 404)

    def test_chat_headers_use_session_timestamp_without_claiming_full_view_fresh(self):
        old=(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat();fresh=stamp()
        atomic_json(self.root/'data/details.json',{'messages':{'quick':[{'role':'assistant','text':'Current answer'}]},'traces':{'quick':[{'id':'turn'}]},'runs':{},'history':{},'_view':{'asof':old},'_chat_views':{'quick':{'asof':fresh}}})
        for route in ('/api/messages?session=quick','/api/chat-traces?session=quick'):
            code,headers,value=self.request('GET',route)
            self.assertEqual(code,200);self.assertEqual(headers['X-Data-As-Of'],fresh);self.assertEqual(headers['X-Data-Stale'],'false')
        self.assertTrue(server.READER.read('details')['_view']['stale'])
        self.assertEqual(self.request('GET','/api/history?kind=memory&id=policy')[1]['X-Data-As-Of'],old)


if __name__ == '__main__': unittest.main()
