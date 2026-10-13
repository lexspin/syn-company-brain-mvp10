"""Hostile requests target only an ephemeral synthetic server and queue."""
import http.client
import json
import unittest
from unittest.mock import patch
import test_dashboard_views as fixture

class AdversarialHTTPTests(unittest.TestCase):
    setUp=fixture.DashboardViewTests.setUp
    tearDown=fixture.DashboardViewTests.tearDown

    def send(self,body,extra=()):
        connection=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=3)
        connection.putrequest('POST','/api/save')
        connection.putheader('X-Brain-Token',fixture.server.TOKEN)
        connection.putheader('Content-Length',str(len(body)))
        for key,value in extra:connection.putheader(key,value)
        connection.endheaders(body)
        response=connection.getresponse();status=response.status;response.read();connection.close();return status

    def test_ambiguous_or_nonstandard_json_is_rejected_before_queue(self):
        bodies=[b'{"kind":"memory","id":"test","data":{"name":"one","name":"two"}}',
                b'{"kind":"memory","id":"test","data":{"name":"test","value":NaN}}',
                b'{"kind":"memory","id":"test","data":{"name":"test","value":1e999}}',
                b'{"kind":"memory","id":"test","data":{"name":"test","value":-1e999}}']
        with patch.object(fixture.server.QUEUE,'wait',return_value={'ok':True,'result':{}}):
            for body in bodies:
                with self.subTest(body=body):self.assertEqual(self.send(body),400)
        self.assertFalse(list((fixture.server.QUEUE.root/'requests').glob('*.json')))

    def test_transfer_encoding_rejected_on_canonical_endpoint(self):
        body=json.dumps({'kind':'memory','id':'test','data':{'name':'test'}}).encode()
        with patch.object(fixture.server.QUEUE,'wait',return_value={'ok':True,'result':{}}):
            self.assertEqual(self.send(body,[('Transfer-Encoding','chunked')]),400)
        self.assertFalse(list((fixture.server.QUEUE.root/'requests').glob('*.json')))

    def test_fixture_does_not_own_production_or_provider(self):
        self.assertNotEqual(self.root.resolve(),fixture.ROOT.resolve())
        self.assertNotIn(self.http.server_port,(14699,14703))
        self.assertTrue(fixture.server.QUEUE.root.resolve().is_relative_to(self.root.resolve()))
        self.assertFalse(hasattr(self.http,'brain'))

if __name__=='__main__':unittest.main()
