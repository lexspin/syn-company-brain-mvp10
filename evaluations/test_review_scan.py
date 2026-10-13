from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from review_scan import changes,acknowledge
class ReviewScanTests(unittest.TestCase):
 def test_new_modified_and_deleted(self):
  self.assertEqual({x['key']:x['change'] for x in changes({'a':2,'b':3},{'a':1,'c':4})},{'a':'modified','b':'new','c':'deleted'})
 def test_unverified_is_not_checkpointed(self):
  self.assertEqual(acknowledge({'reviews':[{'key':'a','current':2,'status':'unverified','evidence':'No provider access'}]},{'a':2},{'a':1}),{'a':1})
 def test_stale_review_rejected(self):
  with self.assertRaises(ValueError):acknowledge({'reviews':[{'key':'a','current':1,'status':'verified','evidence':'Test'}]},{'a':2},{})
 def test_only_evidenced_versions_advance(self):
  self.assertEqual(acknowledge({'reviews':[{'key':'a','current':2,'status':'verified','evidence':'Receipt path'}]},{'a':2,'b':3},{}),{'a':2})
