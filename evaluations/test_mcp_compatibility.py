"""Real stdio wire checks against synthetic loopback data; no live Brain writer."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from memory_mcp import PROTOCOLS, TOOL_NAMES


def request(identity, method, **params):
    value = {'jsonrpc': '2.0', 'method': method, 'params': params}
    if identity is not None:
        value['id'] = identity
    return value


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.state = {'_view': {'asof': datetime.now(timezone.utc).isoformat()},
                      'objects': [{'kind': 'memory', 'id': name, 'version': version,
                                   'data': {'name': name, 'content': 'Evidence Ω'},
                                   'archived': False}
                                  for name, version in [('allowed', 1), ('unrelated', 1), ('changed', 2)]],
                      'memory_freshness': {name: {'current': True}
                                           for name in ('allowed', 'unrelated', 'changed')}}
        self.before = copy.deepcopy(self.state)
        self.calls = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.calls.append(('GET', self.path))
                if self.path != '/api/state':
                    self.send_error(404)
                    return
                data = json.dumps(owner.state).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                owner.calls.append(('POST', self.path))
                self.send_error(405)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.assertEqual(self.state, self.before)
        self.assertTrue(all(call == ('GET', '/api/state') for call in self.calls))

    def wire(self, requests):
        return {item['id']: item for item in self.raw_wire(''.join(json.dumps(item) + '\n' for item in requests))}

    def raw_wire(self, wire_input):
        scope = [{'kind': 'memory', 'id': name, 'version': 1} for name in ('allowed', 'changed')]
        result = subprocess.run(
            [sys.executable, '-B', str(ROOT / 'app/memory_mcp.py'), '--base',
             'http://127.0.0.1:' + str(self.server.server_port), '--scope-json', json.dumps(scope)],
            input=wire_input,
            capture_output=True, text=True, encoding='utf-8', timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertTrue(all(item['jsonrpc'] == '2.0' for item in responses))
        return responses

    def test_parse_invalid_request_and_notification_boundaries(self):
        for raw, code in [('{private-marker\n', -32700), ('42\n', -32600),
                          ('[]\n', -32600), ('{"jsonrpc":"2.0"}\n', -32600)]:
            with self.subTest(raw=raw):
                replies = self.raw_wire(raw)
                self.assertEqual(len(replies), 1)
                self.assertIsNone(replies[0]['id'])
                self.assertEqual(replies[0]['error']['code'], code)
                self.assertNotIn('private-marker', json.dumps(replies))
        self.assertEqual(self.raw_wire(json.dumps(request(None, 'notifications/initialized')) + '\n'), [])
        private = 'C:/private-marker/private-record.json'
        invalid = {'jsonrpc': '2.0', 'id': 27, 'method': 'ping', 'params': private}
        replies = self.raw_wire(json.dumps(invalid) + '\n')
        self.assertEqual(replies[0]['error']['code'], -32602)
        self.assertNotIn(private, json.dumps(replies))
        self.assertNotIn('private-marker', json.dumps(replies))
        replies = self.raw_wire('{"jsonrpc":"2.0","id":null,"method":"ping"}\n')
        self.assertEqual(replies, [{'jsonrpc': '2.0', 'id': None, 'result': {}}])

    def handshake(self, version='2025-11-25'):
        return [request(1, 'initialize', protocolVersion=version, capabilities={},
                        clientInfo={'name': 'isolated-compatibility-test', 'version': '1'}),
                request(None, 'notifications/initialized')]

    def test_every_advertised_dialect_negotiates_lists_and_reads(self):
        for version in sorted(PROTOCOLS):
            with self.subTest(version=version):
                replies = self.wire(self.handshake(version) + [request(2, 'tools/list'),
                    request(3, 'tools/call', name='get_knowledge', arguments={'id': 'allowed'})])
                self.assertEqual(set(replies), {1, 2, 3})
                self.assertEqual(replies[1]['result']['protocolVersion'], version)
                tools = replies[2]['result']['tools']
                self.assertEqual([tool['name'] for tool in tools], TOOL_NAMES)
                self.assertTrue(all(tool['annotations']['readOnlyHint'] for tool in tools))
                self.assertFalse(replies[3]['result']['isError'])
                self.assertEqual(replies[3]['result']['structuredContent']['record']['data']['content'], 'Evidence Ω')

    def test_unknown_version_returns_supported_fallback(self):
        replies = self.wire(self.handshake('2099-01-01'))
        self.assertEqual(replies[1]['result']['protocolVersion'], '2025-11-25')
        self.assertIn(replies[1]['result']['protocolVersion'], PROTOCOLS)

    def test_reads_require_initialize_and_initialized_notification(self):
        replies = self.wire([request(8, 'tools/list'), self.handshake()[0],
                             request(9, 'tools/list')])
        self.assertIn('error', replies[8])
        self.assertIn('error', replies[9])
        self.assertEqual(self.calls, [])

    def test_exact_scope_and_error_layers(self):
        replies = self.wire(self.handshake() + [
            request(2, 'tools/call', name='get_knowledge', arguments={'id': 'unrelated'}),
            request(3, 'tools/call', name='get_knowledge', arguments={'id': 'changed'}),
            request(4, 'tools/call', name='save', arguments={}),
            request(5, 'tools/call', name='get_knowledge', arguments={'id': 'allowed', 'write': True}),
            request(6, 'resources/list'),
            request(7, 'tools/call', name='review_learning_candidates', arguments={'project_id': 'lab'}),
            request(8, 'tools/call', name='search_knowledge', arguments={'query': 'Evidence'})])
        for identity in (2, 3, 4, 5, 7):
            self.assertTrue(replies[identity]['result']['isError'])
        self.assertEqual(replies[6]['error']['code'], -32601)
        self.assertEqual([row['id'] for row in replies[8]['result']['structuredContent']['records']], ['allowed'])


if __name__ == '__main__':
    unittest.main()
