import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('prompt_route',Path(__file__).resolve().parents[1]/'skills/company-brain-prompt-routing/scripts/route.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def row(kind,id,name,refs=(),archived=False):
    return dict(kind=kind,id=id,version=1,archived=archived,data=dict(name=name,refs=list(refs)))

class PromptRoutingTests(unittest.TestCase):
    def test_exact_reference_beats_keywords_and_preserves_input(self):
        query='skill:lighting keep 24 fps; do not publish'
        state={'objects':[row('skill','lighting','Light'),row('skill','publish','publish fps keep') ]}
        self.assertEqual(m.route(state,query)['candidates'][0]['ref'],'skill:lighting')
        self.assertEqual(query,'skill:lighting keep 24 fps; do not publish')
    def test_one_hop_no_archived_or_stale_memory(self):
        state={'objects':[row('skill','shot','Shot',['skill:light','memory:old','skill:gone']),row('skill','light','Light',['skill:deep']),row('skill','deep','Deep'),row('memory','old','Old'),row('skill','gone','Gone',archived=True)]}
        self.assertEqual([x['ref'] for x in m.route(state,'shot')['adjacent']],['skill:light'])
    def test_no_substring_or_forced_match(self):
        self.assertEqual(m.route({'objects':[row('skill','exa','Exa')]},'example')['candidates'],[])
    def test_alias_and_bounded_candidates(self):
        rows=[row('skill',str(i),'Camera') for i in range(20)]
        rows[0]['data']['aliases']=['dolly']
        self.assertEqual(m.route({'objects':rows},'dolly')['candidates'][0]['ref'],'skill:0')
        self.assertEqual(len(m.route({'objects':rows},'camera')['candidates']),8)
    def test_missing_project_rejected(self):
        with self.assertRaises(ValueError):m.route({'objects':[]},'hello','unknown')

if __name__=='__main__':unittest.main()
