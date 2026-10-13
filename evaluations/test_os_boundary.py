import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from git_service import check_os_paths
class OSBoundaryTests(unittest.TestCase):
    def test_os_sources_and_link_records_allowed(self):
        check_os_paths(['app/server.py','docs/ARCHITECTURE.md','records/memory/source/v0001.json','skills/director/SKILL.md'])
    def test_product_files_cannot_enter_os_checkpoint(self):
        for path in ['docs/client-paper.PDF','company/movie.mp4','app/scene.blend','records/report.docx']:
            with self.subTest(path=path),self.assertRaisesRegex(ValueError,'AI OS repository only'):
                check_os_paths([path])
