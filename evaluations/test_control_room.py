import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from live_activity import _reads

class SourceProjectionTests(unittest.TestCase):
    def test_bad_source_does_not_erase_valid_sibling(self):
        rows=_reads([{'label':'broken','reference':'https://['},{'label':'valid','reference':'https://example.com/source'}])
        self.assertEqual([r['label'] for r in rows],['valid'])
    def test_unsafe_sources_omitted(self):
        self.assertEqual(_reads([{'reference':'javascript:alert(1)'},{'reference':'https://user:secret@example.com'}]),[])

if __name__=='__main__':unittest.main()
