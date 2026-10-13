"""Regression contract for the actual installed read-only native discovery helper."""
import importlib.util
from pathlib import Path
import unittest

HELPER = Path(__file__).resolve().parents[1] / 'skills/company-brain-prompt-routing/scripts/route.py'
spec = importlib.util.spec_from_file_location('native_prompt_route', HELPER)
router = importlib.util.module_from_spec(spec)
spec.loader.exec_module(router)


class NativePromptRouteTests(unittest.TestCase):
    def state(self):
        return dict(objects=[
            dict(kind='skill', id='company-brain-naming', version=3, data={'name': 'Reviewed names'}),
            dict(kind='project', id='example-project', version=2, data={'name': 'Example'}),
            dict(kind='loop', id='reviewed-naming', version=1,
                 data={'name': 'company brain naming', 'description': ' '.join('term'+str(i) for i in range(100))})])

    def test_bare_and_prefixed_exact_mentions_outrank_keyword_hits(self):
        for query in ('company-brain-naming', 'skill:company-brain-naming', '@company-brain-naming',
                      'company-brain-naming '+ ' '.join('term'+str(i) for i in range(100))):
            with self.subTest(query=query):
                cards = router.route(self.state(), query)['candidates']
                self.assertEqual(cards[0]['ref'], 'skill:company-brain-naming')
                self.assertTrue(cards[0]['reason']['exact_reference'])

    def test_prefix_boundaries_and_wrong_kinds_do_not_claim_exact_match(self):
        for query in ('not-company-brain-naming', 'company-brain-naming-extra', 'memory:company-brain-naming'):
            cards = router.route(self.state(), query)['candidates']
            self.assertTrue(all(not c['reason']['exact_reference'] for c in cards))

    def test_explicit_prefix_outranks_bare_keyword_short_id_and_punctuation(self):
        state = {'objects': [dict(kind='skill', id='lighting', version=1, data={'name':'Light'}),
                             dict(kind='skill', id='publish', version=1, data={'name':'publish fps keep'})]}
        for query in ('skill:lighting keep 24 fps; do not publish', 'skill:lighting; publish fps keep'):
            result = router.route(state,query)
            self.assertEqual(result['candidates'][0]['ref'],'skill:lighting')
            self.assertTrue(result['candidates'][0]['reason']['explicit_reference'])
        self.assertEqual(router.route(state,'lighting')['candidates'][0]['ref'],'skill:lighting')
        result = router.route(state,'memory:lighting; skill:publish')
        self.assertEqual(result['candidates'][0]['ref'],'skill:publish')
        lighting = next(c for c in result['candidates'] if c['ref']=='skill:lighting')
        self.assertFalse(lighting['reason']['exact_reference'])

    def test_project_exact_mention_and_output_bounds(self):
        result = router.route(self.state(), 'example-project naming')
        self.assertEqual(result['candidates'][0]['ref'], 'project:example-project')
        self.assertLessEqual(len(result['candidates']), 8)
        self.assertLessEqual(len(result['adjacent']), 6)

    def test_relevant_skills_survive_memory_flood_without_unrelated_forcing(self):
        state=self.state()
        state['objects'].append(dict(kind='skill', id='company-brain-archive-research', version=2,
            data={'name':'Archive research', 'description':'Save requested research and sources'}))
        state['memory_freshness']={}
        for n in range(30):
            ident='memory-'+str(n)
            state['objects'].append(dict(kind='memory', id=ident, version=1,
                data={'name':'rename this properly archive research sources naming'}))
            state['memory_freshness'][ident]={'current':True}
        cards=router.route(state,'rename this properly and archive the research with its sources')['candidates']
        self.assertIn('skill:company-brain-naming', [c['ref'] for c in cards])
        self.assertIn('skill:company-brain-archive-research', [c['ref'] for c in cards])
        self.assertLessEqual(len(cards),8)
        self.assertEqual(router.route(state,'zygomatic extraterrestrial')['candidates'],[])
        state['objects'].append(dict(kind='skill', id='shorts-format-video', version=14,
            data={'name':'Shorts Format Video', 'description':'Compose and audit portrait edits shot by shot'}))
        self.assertFalse(any(c['ref'].startswith('skill:') for c in
            router.route(state,'What is seventeen multiplied by nineteen?')['candidates']))
        state['memory_freshness']={}
        self.assertFalse(any(c['ref'].startswith('memory:') for c in router.route(state,'naming')['candidates']))

    def test_selected_role_resolves_current_skill_versions_and_rejects_archived(self):
        state=self.state()
        state['objects'].append(dict(kind='agent',id='reviewer',version=4,
            data={'skills':['company-brain-naming'], 'model':'configured-only','tools':['retrieve']}))
        role=router.selected_role(state,'reviewer')
        self.assertEqual(role['skills'],[dict(id='company-brain-naming',version=3)])
        self.assertEqual(role['version'],4)
        state['objects'][0]['archived']=True
        with self.assertRaisesRegex(ValueError,'unavailable skill'): router.selected_role(state,'reviewer')
        with self.assertRaisesRegex(ValueError,'unavailable'): router.selected_role(state,'missing')


if __name__ == '__main__': unittest.main()
