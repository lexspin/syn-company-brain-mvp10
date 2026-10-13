import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from brain import Brain
from file_ledger import Store

class FileLedgerTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'runtime')
  self.root=Path(self.temp.name);self.b=Brain(self.root)
 def tearDown(self):self.temp.cleanup()
 def dump(self,path):
  c=sqlite3.connect(path)
  try:return list(c.iterdump())
  finally:c.close()
 def test_replay_reconstructs_exact_schema_and_operational_state(self):
  self.b.save('memory','source',{'name':'Source','content':'Original','source':'Owner','status':'accepted'})
  with self.b.connect() as c:
   c.execute('INSERT INTO messages(session,role,text,created) VALUES(?,?,?,?)',('conversation','user','hello Ω','now'))
   c.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?)',('run','loop','failed',1,'{}','[]','error','now','now'))
   c.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?,?)',('attempt','run',0,'failed','diagnostic','now','now'))
   c.execute('INSERT INTO receipts VALUES(?,?)',('request','run'))
   c.execute('INSERT INTO chat_turns VALUES(?,?,?,?,?,?,?,?,?,?,?)',('turn','conversation','auto','worker','failed','request','{}','[]','error','now','now'))
   c.execute('INSERT INTO chat_attempts VALUES(?,?,?,?,?,?,?,?,?,?)',('call','turn','plan','planner','failed','request','','error','now','now'))
   c.execute('CREATE TABLE blobs (id INTEGER PRIMARY KEY,value BLOB)')
   c.cursor().execute('INSERT INTO blobs VALUES(:id,:value)',{'id':1,'value':b'\x00\xff'})
   c.execute('UPDATE messages SET text=? WHERE session=?',('corrected','conversation'))
  recovery=self.root/'recovered.sqlite';self.b.store.rebuild(recovery)
  self.assertEqual(self.dump(self.b.db),self.dump(recovery))
 def test_existing_projection_bootstraps_once(self):
  root=self.root/'legacy';(root/'runtime').mkdir(parents=True)
  c=sqlite3.connect(root/'runtime/brain.sqlite')
  c.execute('CREATE TABLE legacy (id INTEGER PRIMARY KEY, note TEXT)');c.execute('INSERT INTO legacy VALUES(1,?)',('Preserve this original',));c.commit();c.close()
  brain=Brain(root);brain.store.read()
  self.assertEqual(sum(e['kind']=='baseline' for e in brain.store.entries),1)
  with brain.connect() as c:self.assertEqual(c.execute('SELECT note FROM legacy').fetchone()[0],'Preserve this original')
  destination=root/'rebuild.sqlite';brain.store.rebuild(destination)
  self.assertEqual(self.dump(brain.db),self.dump(destination))
 def test_file_durability_precedes_projection_commit(self):
  def fail_after_append(connection):
   self.b.store.append(connection.operations)
   raise RuntimeError('Simulated failure after durable file write')
  with patch.object(self.b.store,'finish',side_effect=fail_after_append):
   with self.assertRaises(RuntimeError):
    with self.b.connect() as c:c.execute('INSERT INTO messages(session,role,text,created) VALUES(?,?,?,?)',('crash','user','durable','now'))
  c=sqlite3.connect(self.b.db)
  self.assertEqual(c.execute("SELECT count(*) FROM messages WHERE session='crash'").fetchone()[0],0);c.close()
  with self.b.connect() as c:self.assertEqual(c.execute("SELECT text FROM messages WHERE session='crash'").fetchone()[0],'durable')
  with self.b.connect() as c:self.assertEqual(c.execute("SELECT count(*) FROM messages WHERE session='crash'").fetchone()[0],1)
 def test_failed_append_rolls_back_projection(self):
  before=self.b.store.path.read_bytes()
  with patch.object(self.b.store,'append',side_effect=OSError('disk full')):
   with self.assertRaises(OSError):
    with self.b.connect() as c:c.execute('INSERT INTO messages(session,role,text,created) VALUES(?,?,?,?)',('failed','user','not saved','now'))
  self.assertEqual(before,self.b.store.path.read_bytes())
  with self.b.connect() as c:self.assertEqual(c.execute("SELECT count(*) FROM messages WHERE session='failed'").fetchone()[0],0)
 def test_torn_tail_is_preserved_and_recovery_is_chained(self):
  before=self.b.store.path.read_bytes();tail=b'{"seq":'
  with self.b.store.path.open('ab') as handle:handle.write(tail)
  with self.b.connect() as c:c.execute('SELECT 1')
  after=self.b.store.path.read_bytes();self.assertTrue(after.startswith(before+tail))
  reader=Store(self.root,self.b.db);reader.read()
  self.assertEqual(reader.entries[-1]['kind'],'tail-recovery');self.assertEqual(reader.tail,b'')
  reader.rebuild(self.root/'tail-recovery.sqlite')
  self.assertEqual(self.dump(self.b.db),self.dump(self.root/'tail-recovery.sqlite'))
 def test_hash_tampering_stops_recovery(self):
  path=self.b.store.path;path.write_bytes(path.read_bytes().replace(b'baseline',b'baselinx',1))
  with self.assertRaisesRegex(ValueError,'hash mismatch'):
   with self.b.connect():pass
 def test_complete_final_entry_without_newline_remains_replayable(self):
  path=self.b.store.path;path.write_bytes(path.read_bytes().rstrip(b'\n'))
  prefix=path.read_bytes()
  with self.b.connect() as c:c.execute('INSERT INTO messages(session,role,text,created) VALUES(?,?,?,?)',('newline','user','saved','now'))
  self.assertTrue(path.read_bytes().startswith(prefix+b'\n'))
  reader=Store(self.root,self.b.db);reader.read();reader.rebuild(self.root/'newline.sqlite')
  self.assertEqual(self.dump(self.b.db),self.dump(self.root/'newline.sqlite'))
 def test_read_transactions_do_not_append(self):
  before=self.b.store.path.read_bytes()
  with self.b.connect() as c:c.execute('SELECT count(*) FROM objects').fetchone()
  self.assertEqual(before,self.b.store.path.read_bytes())
 def test_manual_commit_is_rejected(self):
  with self.assertRaisesRegex(ValueError,'source file'):
   with self.b.connect() as c:c.commit()
 def test_immutable_export_is_not_overwritten(self):
  self.b.save('memory','source',{'name':'Source','content':'Original','source':'Owner','status':'accepted'})
  path=self.root/'records/memory/source/v0001.json';path.write_text('external alteration',encoding='utf-8')
  with self.assertRaisesRegex(ValueError,'Immutable'):self.b.export()
  self.assertEqual(path.read_text(),'external alteration')

if __name__=='__main__':unittest.main()
