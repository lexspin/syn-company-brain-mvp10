import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from history_cloud_intake import import_cloud
from history_intake import import_history
from history_recall import search,verify,final_output

class CloudHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'runtime')
        self.root=Path(self.temp.name);self.home=self.root/'codex';(self.home/'sessions').mkdir(parents=True)
        (self.root/'store/cloud-history').mkdir(parents=True)
        self.user={'type':'userMessage','id':'cloud-user-one','content':[{'type':'text','text':'LinkedIn original voice should keep the precise source argument.'}]}
        self.answer={'type':'agentMessage','id':'cloud-answer-one','text':'Visible answer excerpt','truncated':True}
        correction={'type':'userMessage','id':'cloud-user-two','content':[{'type':'text','text':'Correct the LinkedIn ending, preserve my opening.'}]}
        page={'thread':{'id':'cloud-thread-one','title':'LinkedIn writing','createdAt':1000},'page':{'order':'newest_first','hasMore':False,'nextCursor':None},
              'turns':[{'id':'turn-two','startedAt':3000,'items':[correction]},{'id':'turn-one','startedAt':2000,'items':[self.user,self.answer]}]}
        self.wrapper={'thread_id':'cloud-thread-one','title':'LinkedIn writing','captured_at':'2026-10-10T20:00:00Z','results':[{'status':'fulfilled','value':{'content':[{'type':'text','text':json.dumps(page)}]}}]}
        self.path=self.root/'store/cloud-history/cloud-thread-one.json';self.path.write_text(json.dumps(self.wrapper),encoding='utf-8')
    def tearDown(self):self.temp.cleanup()
    def test_partial_cloud_prompts_are_searchable_with_original_snapshot_and_correction_links(self):
        result=import_cloud(self.root,self.home)
        self.assertEqual(result['human_messages'],2);self.assertFalse(result['complete_account_export']);self.assertEqual(result['scan']['truncated_assistant_items'],1)
        recalled=search(self.root,'precise source argument',domain='linkedin-blog');self.assertTrue(recalled);self.assertTrue(verify(self.root,recalled))
        first=recalled[0];self.assertTrue(first['source_partial']);self.assertEqual(first['source_message_id'],'cloud-user-one')
        self.assertEqual((self.root/first['source_snapshot_path']).read_bytes(),self.path.read_bytes())
        correction=search(self.root,'Correct ending',domain='linkedin-blog')[0]
        answer=final_output(self.root,correction['previous_output_id'])
        self.assertEqual(answer['text'],'Visible answer excerpt');self.assertTrue(answer['truncated']);self.assertEqual(answer['output_kind'],'visible-assistant-snapshot')
    def test_repeat_intake_does_not_duplicate_or_rewrite_messages(self):
        import_cloud(self.root,self.home);paths=list((self.root/'store/history/messages').glob('*.json'));before={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in paths}
        result=import_cloud(self.root,self.home);self.assertEqual(result['scan'].get('new_messages',0),0)
        self.assertEqual(before,{p:(p.read_bytes(),p.stat().st_mtime_ns) for p in paths})
    def test_later_local_intake_preserves_cloud_recall_and_reports_separate_counts(self):
        import_cloud(self.root,self.home)
        events=[{'type':'session_meta','payload':{'id':'local-thread-one','thread_source':'user','source':'vscode'}},{'type':'response_item','timestamp':'2026-10-10T19:00:00Z','payload':{'type':'message','id':'local-user-one','role':'user','content':[{'type':'input_text','text':'Local thesis evidence'}]}}]
        (self.home/'sessions/local.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
        coverage=import_history(self.root,self.home)
        self.assertEqual(coverage['retained_local_messages'],1);self.assertEqual(coverage['retained_cloud_messages'],2);self.assertEqual(coverage['retained_messages'],3)
        self.assertTrue(verify(self.root,search(self.root,'precise source argument',domain='linkedin-blog')))
    def test_changed_cloud_snapshot_is_rejected(self):
        import_cloud(self.root,self.home);records=search(self.root,'LinkedIn');path=self.root/records[0]['source_snapshot_path'];path.write_text('{}')
        with self.assertRaisesRegex(ValueError,'snapshot changed'):verify(self.root,records)

if __name__=='__main__':unittest.main()
