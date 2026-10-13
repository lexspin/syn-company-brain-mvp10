"""Exact generated signpost limits, preserving every source and strict bounds."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
from check_map import rebuild, check, MAX_ITEMS


class MapLimitsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'runtime')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'docs').mkdir()
        # This signpost fixture declares source files, not registered projects.
        projects=patch('check_map.project_folders',return_value=[])
        projects.start();self.addCleanup(projects.stop)

    def entries(self, count, separate=False):
        rows=[]
        for number in range(count):
            path=self.root/'docs'/f'source-{number:03d}.md'
            path.write_text('Original '+str(number), encoding='utf-8')
            rows.append({'path':path.as_posix(),'area':f'area-{number:03d}' if separate else 'sources','section':'Memory','label':f'Source {number:03d}','authority':'original_source'})
        return rows

    def test_exact_67_entries_stay_below_80_with_direct_source_links(self):
        self.assertEqual(MAX_ITEMS, 67)
        rows=self.entries(67)
        with patch('check_map.catalog', return_value=rows):
            rebuild(self.root);report=check(self.root)
        self.assertTrue(report['ok'],report)
        self.assertEqual(report['areas'],1)
        page=self.root/'memory-map/areas/sources.md'
        lines=page.read_text(encoding='utf-8').splitlines()
        self.assertLess(len(lines),80)
        self.assertEqual(sum(line.startswith('- [') for line in lines),67)
        self.assertEqual(report['documents'],67)
        self.assertEqual(report['unmapped_documents'],[])
        for row in rows:self.assertIn(row['path'],page.read_text(encoding='utf-8'))

    def test_68th_source_splits_without_loss_or_third_hop(self):
        rows=self.entries(68)
        with patch('check_map.catalog',return_value=rows):
            rebuild(self.root);report=check(self.root)
        self.assertTrue(report['ok'],report)
        self.assertEqual(report['areas'],2)
        self.assertEqual(report['documents'],68)
        pages=list((self.root/'memory-map/areas').glob('*.md'))
        self.assertEqual(sorted(sum(line.startswith('- [') for line in p.read_text(encoding='utf-8').splitlines()) for p in pages),[1,67])
        self.assertTrue(all(len(p.read_text(encoding='utf-8').splitlines())<80 for p in pages))

    def test_master_59_passes_and_60_still_fails_without_lost_sources(self):
        rows=self.entries(59,separate=True)
        with patch('check_map.catalog',return_value=rows):
            rebuild(self.root);report=check(self.root)
        self.assertTrue(report['ok'],report)
        rows=self.entries(60,separate=True)
        with patch('check_map.catalog',return_value=rows):
            rebuild(self.root);report=check(self.root)
        self.assertFalse(report['ok'])
        self.assertEqual(report['errors'],['Master has 60 lines; it must be under 60.'])
        self.assertEqual(report['documents'],60)
        self.assertEqual(report['unmapped_documents'],[])


if __name__=='__main__':unittest.main()
