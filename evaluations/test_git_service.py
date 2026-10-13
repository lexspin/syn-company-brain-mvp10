import subprocess
import threading
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from git_service import run

class GitTests(unittest.TestCase):
 def test_checkpoint_push_and_exclusion(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'runtime') as folder:
   root=Path(folder)/'work';root.mkdir();remote=Path(folder)/'remote.git'
   def git(*args):
    return subprocess.run(['git','-C',str(root),*args],capture_output=True,text=True,check=True).stdout.strip()
   git('init','-b','main');git('config','user.name','Validation');git('config','user.email','validation@example.invalid')
   subprocess.run(['git','init','--bare',str(remote)],capture_output=True,check=True)
   git('remote','add','origin',str(remote))
   (root/'README.md').write_text('Verified checkpoint')
   (root/'vendor').mkdir();(root/'vendor/private.txt').write_text('Do not export licensed source')
   (root/'runtime').mkdir();(root/'runtime/private.txt').write_text('Do not export private runtime')
   brain=SimpleNamespace(root=root,export=lambda:None,lock=threading.RLock())
   result=run(brain,'push')
   self.assertTrue(result['push_verified']);self.assertEqual(result['ahead'],0)
   self.assertEqual(result['behind'],0)
   self.assertEqual(git('rev-parse','HEAD'),git('rev-parse','origin/main'))
   self.assertEqual(git('ls-files'),'README.md')
   git('add','vendor/private.txt')
   with self.assertRaisesRegex(ValueError,'Unrelated files'):run(brain,'commit')

if __name__=='__main__':unittest.main()
