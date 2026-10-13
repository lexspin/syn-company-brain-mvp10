import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('routing_benchmark', Path(__file__).with_name('routing_benchmark.py'))
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class RoutingBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.state = {'objects':[{'kind':'skill','id':'naming','version':2,'data':{}},
                                 {'kind':'memory','id':'old','version':1,'data':{}}]}
        self.case = {'id':'normal','query':'rename','expected_refs':['skill:naming']}

    def response(self, cards, adjacent=None):
        return lambda state, query: {'candidates':cards,'adjacent':adjacent or []}

    def test_inclusion_and_version_pass_without_mutation(self):
        import copy
        original = copy.deepcopy(self.state)
        result = benchmark.evaluate(self.state,[self.case],self.response([{'ref':'skill:naming','version':2}]))
        self.assertEqual(result['passed_count'],1)
        self.assertEqual(self.state,original)

    def test_missing_expectation_not_weakened_by_adjacent_match(self):
        result = benchmark.evaluate(self.state,[self.case],self.response([], [{'ref':'skill:naming','version':2}]))
        self.assertEqual(result['cases'][0]['missing_refs'],['skill:naming'])
        self.assertEqual(result['failed_count'],1)

    def test_stale_memory_old_version_and_archived_rejected(self):
        for card in ({'ref':'memory:old','version':1},{'ref':'skill:naming','version':1}):
            result = benchmark.evaluate(self.state,[self.case],self.response([card]))
            self.assertEqual(result['cases'][0]['invalid_or_stale_refs'],[card['ref']])
        self.state['objects'][0]['archived']=True
        result = benchmark.evaluate(self.state,[self.case],self.response([{'ref':'skill:naming','version':2}]))
        self.assertEqual(result['cases'][0]['unavailable_expectations'],['skill:naming'])

    def test_negative_and_context_bounds_are_measured(self):
        case={'id':'negative','query':'pasta','expected_refs':[],'expect_no_skills':True}
        result=benchmark.evaluate(self.state,[case],self.response([{'ref':'skill:naming','version':2}]*9))
        self.assertFalse(result['cases'][0]['bounded'])
        self.assertTrue(result['cases'][0]['unexpected_skills'])
        self.assertEqual(result['failed_count'],1)

    def test_duplicate_cases_rejected(self):
        with self.assertRaisesRegex(ValueError,'unique'):
            benchmark.evaluate(self.state,[self.case,self.case],self.response([]))


if __name__ == '__main__': unittest.main()
