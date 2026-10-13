import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from brain import Brain,digest
from archive_research import capture,capture_source

class ArchiveResearchTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'runtime')
  self.b=Brain(self.temp.name)
  self.b.save('skill','writer',{'name':'Writer','instructions':'Cite sources.'})
  self.b.save('skill','reviewer',{'name':'Reviewer','instructions':'Review sources.'})
  self.b.save('agent','researcher',{'name':'Researcher','instructions':'Research','skills':['writer'],'tools':['draft']})
  self.b.save('memory','source',{'name':'Source','content':'Evidence text.','source':'Owner document','status':'accepted'})
  self.b.save('project','work',{'name':'Work','path':self.temp.name,'scope':'Current project','refs':[]})
  self.turn='a'*32;self.answer='Research answer with evidence [source@1].\nKeep this exact text.'
  dependencies=[{'kind':kind,'id':id,'version':1} for kind,id in [('agent','researcher'),('skill','writer'),('memory','source'),('project','work')]]
  with self.b.connect() as c:
   c.execute('INSERT INTO chat_turns VALUES(?,?,?,?,?,?,?,?,?,?,?)',(self.turn,'session','auto','researcher','completed','Research this question','{}',json.dumps(dependencies),'','created','completed'))
   c.execute('INSERT INTO chat_attempts VALUES(?,?,?,?,?,?,?,?,?,?)',('answer-attempt',self.turn,'answer','researcher','completed','source prompt',self.answer,'','created','completed'))
 def tearDown(self):self.temp.cleanup()
 def test_chat_archive_preserves_exact_output_provenance_and_reciprocal_links(self):
  result=capture(self.b,self.turn)
  self.assertEqual(result['data']['content'],self.answer)
  self.assertEqual(result['data']['capture']['captured_answer_sha256'],digest(self.answer))
  self.assertEqual(result['data']['source_versions'],{'source':1})
  self.assertIn('not been independently verified',result['data']['evidence_type'])
  self.assertIn('memory:'+result['id'],self.b.get('project','work')['data']['refs'])
  self.assertIn('memory:'+result['id'],self.b.get('skill','writer')['data']['refs'])
  self.assertEqual(self.b.get('memory','source')['version'],1)
  again=capture(self.b,self.turn)
  self.assertEqual(again['capture_status'],'existing');self.assertEqual(again['version'],1)
  self.assertEqual(again['updated_links'],[])
 def test_new_links_version_existing_capture_without_duplicate(self):
  first=capture(self.b,self.turn);again=capture(self.b,self.turn,skill_ids=['reviewer'])
  self.assertEqual(first['id'],again['id']);self.assertEqual(again['version'],2)
  self.assertEqual(again['capture_status'],'linked');self.assertIn('skill:reviewer',again['data']['refs'])
  self.assertIn('memory:'+again['id'],self.b.get('skill','reviewer')['data']['refs'])
  self.assertEqual(len([r for r in self.b.list('memory') if r['data'].get('type')=='research-capture']),1)
 def test_stale_chat_is_archived_as_history_but_excluded_from_current_retrieval(self):
  source=self.b.get('memory','source');self.b.save('memory','source',source['data']|{'content':'Corrected evidence'},1)
  result=capture(self.b,self.turn)
  self.assertFalse(result['source_current'])
  self.assertNotIn(result['id'],[r['id'] for r in self.b.retrieve('Research answer')])
 def test_unfinished_chat_cannot_be_captured(self):
  with self.b.connect() as c:c.execute("UPDATE chat_turns SET state='failed' WHERE id=?",(self.turn,))
  with self.assertRaisesRegex(ValueError,'completed'):capture(self.b,self.turn)
 def test_direct_capture_deduplicates_and_refuses_changed_request_content(self):
  args={'title':'Research outside V2','content':'Caller supplied research','provenance':{'chat_id':'codex-current-chat','source_urls':['https://example.org/paper']},'request_key':'archive-source-001','project_id':'work','skill_ids':['writer']}
  first=capture_source(self.b,**args);second=capture_source(self.b,**args)
  self.assertEqual(first['id'],second['id']);self.assertEqual(second['version'],1)
  self.assertEqual(first['data']['capture']['provenance'],args['provenance'])
  with self.assertRaisesRegex(ValueError,'different research'):capture_source(self.b,**(args|{'content':'A different result'}))
 def test_unknown_links_rejected_before_capture_write(self):
  with self.assertRaises(ValueError):capture(self.b,self.turn,skill_ids=['unknown'])
  self.assertFalse(any(r['data'].get('type')=='research-capture' for r in self.b.list('memory')))
 def test_invalid_source_provenance_is_not_saved(self):
  for provenance in ({},{'source_urls':['https://user:secret@example.org/paper']},{'source_file':'relative/file.md'},{'chat_id':'chat','source_sha256':'not-a-hash'}):
   with self.subTest(provenance=provenance):
    with self.assertRaises(ValueError):capture_source(self.b,'Title','Content',provenance,'archive-source-001')
 def test_archived_capture_is_not_silently_restored(self):
  result=capture(self.b,self.turn);self.b.save('memory',result['id'],result['data'],result['version'],True)
  with self.assertRaisesRegex(ValueError,'archived'):capture(self.b,self.turn)
 def test_retry_completes_partial_backlinks_without_duplicate_capture(self):
  original=self.b.save
  def fail_skill(kind,*args,**kwargs):
   if kind=='skill':raise RuntimeError('Temporary write failure')
   return original(kind,*args,**kwargs)
  with patch.object(self.b,'save',side_effect=fail_skill):
   with self.assertRaisesRegex(ValueError,'Research was saved as'):capture(self.b,self.turn)
  result=capture(self.b,self.turn)
  self.assertEqual(result['version'],1);self.assertEqual(result['capture_status'],'existing')
  self.assertIn('memory:'+result['id'],self.b.get('skill','writer')['data']['refs'])

if __name__=='__main__':unittest.main()
