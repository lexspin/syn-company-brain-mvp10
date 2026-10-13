import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from presentation import display_records,record_display_name,human_name


class PresentationTests(unittest.TestCase):
    def record(self,name,content='',path=''):
        return {'kind':'memory','id':'source','version':3,'data':{'name':name,'content':content,'source_path':path}}

    def test_director_title_comes_from_saved_heading_without_mutation(self):
        record=self.record('ART_DIRECTOR','# Art Director Mandate\n\nOwn visual delivery.')
        before=copy.deepcopy(record)
        result=display_records([record])[0]
        self.assertEqual(result['display_name'],'Art Director — responsibilities')
        self.assertEqual(record,before)
        self.assertEqual(result['data'],before['data'])
        self.assertEqual(result['version'],3)

    def test_role_briefs_include_source_owner(self):
        self.assertEqual(record_display_name(self.record('ROLE_BRIEF','# Fefe Role Brief')),'Fefe — role and responsibilities')
        self.assertEqual(record_display_name(self.record('ROLE_BRIEF','# Role Brief','E:/Team/Video Editor/ROLE_BRIEF.md')),'Video Editor — role and responsibilities')
        self.assertEqual(record_display_name(self.record('ROLE_BRIEF','','E:/Team/Art Director/ROLE_BRIEF.md')),'Art Director — role and responsibilities')

    def test_role_briefs_describe_the_saved_work_lane(self):
        art=self.record('ROLE_BRIEF','# Fefe Role Brief\n\nLane: graphics, environment art, and playable-area presentation')
        programming=self.record('ROLE_BRIEF','# Programming Role Brief\n\nLane: AI/backend, Godot systems, tests, instrumentation, and reliability')
        self.assertEqual(record_display_name(art),'Fefe — graphics and environment art')
        self.assertEqual(record_display_name(programming),'Programming — AI, backend and Godot systems')

    def test_segments_reuse_first_saved_source_heading_and_keep_part(self):
        rows=[self.record('PRODUCTION_WORKFORCE — part 1','# Durable Company Execution Workforce','E:/SOURCE.md'),self.record('PRODUCTION_WORKFORCE — part 2','Later text\n# An unrelated subtopic','E:/SOURCE.md')]
        names=[r['display_name'] for r in display_records(rows)]
        self.assertEqual(names,['Durable Company Execution Workforce — part 1','Durable Company Execution Workforce — part 2'])

    def test_domain_abbreviations_are_expanded_but_original_video_titles_stay(self):
        self.assertEqual(human_name('Ml Method Selection'),'Machine learning — choose a method')
        self.assertEqual(human_name('Ue Mcp Animation'),'Unreal Engine — animation workflow')
        self.assertEqual(record_display_name(self.record('ue-mcp-animation — part 2')),'Unreal Engine — animation workflow — part 2')
        title='The Four Types of Memory Every AI Agent Needs'
        self.assertEqual(record_display_name(self.record(title)),title)


if __name__=='__main__':unittest.main()
