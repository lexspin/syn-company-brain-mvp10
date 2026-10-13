"""Offline discovery benchmark. Reports misses; never changes or promotes procedures."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import time


def evaluate(state, cases, route):
    if not isinstance(cases, list) or not 1 <= len(cases) <= 100:
        raise ValueError('Expected 1–100 cases')
    rows = {r['kind']+':'+r['id']: r for r in state['objects']}
    ids = set()
    results = []
    for case in cases:
        ident = case['id']
        if ident in ids or not isinstance(ident, str) or not ident:
            raise ValueError('Case IDs must be unique nonempty strings')
        ids.add(ident)
        expected = case['expected_refs']
        if not isinstance(expected, list) or any(not isinstance(x, str) for x in expected):
            raise ValueError('Expected refs must be strings')
        unavailable = [ref for ref in expected if ref not in rows or rows[ref].get('archived')]
        start = time.perf_counter()
        response = route(state, case['query'])
        elapsed = (time.perf_counter()-start)*1000
        cards = response['candidates']
        adjacent = response['adjacent']
        refs = [c['ref'] for c in cards]
        invalid = []
        for card in cards + adjacent:
            row = rows.get(card['ref'])
            if (row is None or row.get('archived') or row['version'] != card['version']
                    or row['kind'] == 'memory' and not state.get('memory_freshness', {}).get(row['id'], {}).get('current')):
                invalid.append(card['ref'])
        missing = sorted(set(expected)-set(refs))
        forced = [r for r in refs if r.startswith('skill:')] if case.get('expect_no_skills') else []
        bounded = len(cards) <= 8 and len(adjacent) <= 6
        results.append(dict(id=ident, query=case['query'], expected_refs=expected,
                            returned_refs=refs, returned_versions={c['ref']:c['version'] for c in cards},
                            missing_refs=missing, unavailable_expectations=unavailable,
                            invalid_or_stale_refs=invalid, unexpected_skills=forced,
                            bounded=bounded, latency_ms=round(elapsed, 3),
                            passed=not (missing or unavailable or invalid or forced) and bounded))
    return dict(schema_version=1, case_count=len(results), passed_count=sum(r['passed'] for r in results),
                failed_count=sum(not r['passed'] for r in results), cases=results,
                boundary='Model-free discovery only; latency excludes state loading/network/model execution. No promotion or production gain established.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, default=Path('C:/Users/USER/OneDrive/SYN Company Brain/V2/data/state.json'))
    parser.add_argument('--helper', type=Path, default=Path('C:/Users/USER/.codex/skills/company-brain-prompt-routing/scripts/route.py'))
    parser.add_argument('--cases', type=Path, default=Path(__file__).with_name('routing_benchmark_cases.json'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Import only the explicitly selected local helper; do not fetch or execute external skills.
    spec = importlib.util.spec_from_file_location('brain_benchmark_router', args.helper)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    state_bytes = args.state.read_bytes()
    fixture_bytes = args.cases.read_bytes()
    state = json.loads(state_bytes)
    result = evaluate(state, json.loads(fixture_bytes)['cases'], helper.route)
    result['sources'] = {name: {'path':str(path.resolve()), 'sha256':hashlib.sha256(content).hexdigest()}
                         for name,path,content in [('state',args.state,state_bytes),('helper',args.helper,args.helper.read_bytes()),('fixtures',args.cases,fixture_bytes)]}
    result['publication'] = state.get('_view', {})
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('case_count','passed_count','failed_count')}))
    return 0 if result['failed_count'] == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
