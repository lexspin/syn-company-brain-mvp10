import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
from brain import Brain
from commands import atomic_json
from read_models import Publisher, ReadModels


class ReadModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'runtime')
        self.root = Path(self.temp.name)
        self.brain = Brain(self.root)
        self.brain.save('memory','policy',{'name':'Reporting policy','content':'Use whole pounds.','source':'Owner decision','status':'accepted'})
        (self.root/'BRAIN.md').write_text('# Project map\n',encoding='utf-8')
        self.publisher = Publisher(self.brain)
        self.reader = ReadModels(self.root)

    def tearDown(self):
        self.publisher.stop()
        self.temp.cleanup()

    def publish(self):
        with patch.object(self.brain, 'git', return_value={'branch':'main','remote_url':''}):
            self.publisher.publish()

    def test_reader_works_without_database_or_backend(self):
        self.publish()
        with patch.object(self.brain, 'connect', side_effect=AssertionError('Dashboard must not access database')):
            state = self.reader.read('state')
            self.assertEqual(state['objects'][0]['id'], 'policy')
            self.assertIn('record/memory:policy', self.reader.read('files')['nodes'])
            self.assertIn('memory:policy', self.reader.read('details')['history'])

    def test_unpublished_change_remains_outside_dashboard_until_publish(self):
        self.publish()
        record = self.brain.get('memory','policy')
        self.brain.save('memory','policy',record['data']|{'content':'Use pennies.'},1)
        self.assertEqual(self.reader.read('state')['objects'][0]['version'], 1)
        self.publish()
        self.assertEqual(self.reader.read('state')['objects'][0]['version'], 2)

    def test_old_values_are_visible_and_marked_stale(self):
        self.publish()
        path = self.root/'data/state.json'; value = json.loads(path.read_text())
        value['_view']['asof'] = (datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat()
        atomic_json(path, value)
        state = self.reader.read('state')
        self.assertTrue(state['_view']['stale'])
        self.assertEqual(state['objects'][0]['id'], 'policy')

    def test_search_uses_current_accepted_projection_only(self):
        self.brain.save('memory','draft',{'name':'Reporting draft','content':'Use dollars.','source':'Proposal','status':'candidate'})
        self.publish()
        self.assertEqual([r['id'] for r in self.reader.search('reporting policy')], ['policy'])
        self.assertEqual(self.reader.search('What did we do in the chat?'), [])
        self.assertEqual(self.reader.search('memory:policy@v1')[0]['id'], 'policy')

    def test_no_fake_routine_heartbeat(self):
        self.publish()
        panels = self.reader.read('panels')
        self.assertIsNone(panels['system']['runner_last_tick'])
        self.assertEqual(panels['runs']['routines'], [])

    def test_invalid_view_and_record_paths_are_rejected(self):
        with self.assertRaises(ValueError): self.reader.read('../runtime/brain')
        with self.assertRaises(ValueError): self.reader.valid_record('memory','../../secret')
        with self.assertRaises(ValueError): self.reader.valid_session('../secret')

    def test_private_file_is_not_served_merely_because_it_exists(self):
        (self.root/'private.txt').write_text('not indexed',encoding='utf-8')
        self.publish()
        self.assertNotIn('private.txt', self.reader.read('files')['nodes'])

    def test_exact_approved_record_json_can_be_opened(self):
        path = self.root/'records/memory/policy/v0001.json'
        graph = self.brain.graph()
        graph['nodes'].append({'id':'file:policy','path':str(path),'record_id':'memory:policy'})
        self.publisher.graph_provider = lambda:graph
        self.publisher.source_paths = lambda:[path]
        self.publish()
        self.assertEqual(json.loads(self.reader.read('files')['nodes'][str(path)])['version'], 1)
        self.assertEqual(self.reader.read('state')['record_paths'][str(path)], 'memory:policy')

    def test_routine_briefs_are_a_published_conversation(self):
        engine = Mock()
        engine.status.return_value = {'routines':[], 'recent':[], 'last_tick':None}
        engine.messages.return_value = [{'role':'assistant','text':'Saved briefing','created':datetime.now(timezone.utc).isoformat()}]
        self.publisher.routine_engine = engine
        self.publish()
        self.assertEqual(self.reader.read('details')['messages']['briefs'][0]['text'], 'Saved briefing')
        self.assertTrue(any(s['session']=='briefs' for s in self.reader.read('state')['sessions']))

    def test_map_open_matches_exact_published_text(self):
        approved=self.root/'approved.py';approved.write_text('print("auditable")',encoding='utf-8')
        other=self.root/'unlisted.py';other.write_text('private implementation',encoding='utf-8')
        graph=self.brain.graph()
        graph['nodes'] += [{'id':'approved','path':str(approved)}, {'id':'unlisted','path':str(other)}, {'id':'directory','path':str(self.root)}]
        self.publisher.graph_provider=lambda:graph
        self.publisher.source_paths=lambda:[approved]
        self.publish()
        nodes={n['id']:n for n in self.reader.read('brain')['nodes']}
        self.assertTrue(nodes['approved']['source_available'])
        self.assertFalse(nodes['unlisted']['source_available'])
        self.assertFalse(nodes['directory']['source_available'])
        self.assertNotIn(str(other),self.reader.read('files')['nodes'])

    def test_routine_briefs_preserve_owner_conversation_and_real_tick(self):
        now = datetime.now(timezone.utc).isoformat()
        with self.brain.connect() as c:
            c.execute('INSERT INTO messages(session,role,text,created) VALUES (?,?,?,?)', ('briefs','user','Please expand this.',now))
        engine = Mock()
        engine.status.return_value = {'routines':[], 'recent':[], 'asof':now}
        engine.messages.return_value = [{'role':'assistant','text':'Saved briefing','created':now}]
        self.publisher.routine_engine = engine
        self.publish()
        self.assertEqual(len(self.reader.read('details')['messages']['briefs']), 2)
        self.assertEqual(self.reader.read('panels')['system']['runner_last_tick'], now)

    def test_fast_chat_publishes_current_conversation_without_refreshing_other_views(self):
        self.publish()
        old=(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat()
        for name in ('state','details'):
            path=self.root/'data'/(name+'.json');value=json.loads(path.read_text(encoding='utf-8'))
            value['_view']['asof']=old;atomic_json(path,value)
        untouched={path.name:path.read_bytes() for path in (self.root/'data').glob('*.json') if path.stem not in ('state','details')}
        original=self.reader.read('details')
        with patch('codex_runtime.run',side_effect=AssertionError('L1 must not call a model')):
            result=self.brain.chat('quick','memory:policy','auto')
        providers=[Mock(side_effect=AssertionError('Fast chat must not rebuild source views')) for _ in range(3)]
        self.publisher.graph_provider,self.publisher.source_paths,self.publisher.panels_provider=providers
        with patch.object(self.brain,'status',side_effect=AssertionError('Full state was not requested')),patch.object(self.brain,'git',side_effect=AssertionError('Git was not requested')):
            fresh=self.publisher.publish_chat('quick')
        details=self.reader.read('details');state=self.reader.read('state')
        self.assertEqual(details['messages']['quick'][-1]['text'],result['text'])
        self.assertEqual(details['traces']['quick'][0]['id'],result['turn_id'])
        self.assertEqual(details['traces']['quick'][0]['discovery'][0]['mode'],'l1_lookup')
        self.assertEqual(details['history'],original['history']);self.assertEqual(details['runs'],original['runs'])
        for view in (state,details):
            self.assertEqual(view['_view']['asof'],old);self.assertTrue(view['_view']['stale'])
            self.assertEqual(view['_chat_views']['quick']['asof'],fresh)
        self.assertEqual(self.reader.headers(details,'quick')['X-Data-Stale'],'false')
        self.assertEqual(self.reader.headers(details)['X-Data-Stale'],'true')
        self.assertTrue(any(row['session']=='quick' for row in state['sessions']))
        self.assertFalse(state['worker_busy'])
        for path,content in untouched.items():self.assertEqual((self.root/'data'/path).read_bytes(),content)
        for provider in providers:provider.assert_not_called()

    def test_fast_chat_requires_existing_full_views(self):
        with self.assertRaises(FileNotFoundError):self.publisher.publish_chat('quick')
        self.assertFalse((self.root/'data/details.json').exists())


if __name__ == '__main__': unittest.main()
