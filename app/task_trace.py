"""Check declared task exchanges against observed receipts, without running tools.

This is evidence validation, not a distributed executor or semantic fact checker.
"""
import hashlib
from pathlib import Path


def verify(plan, events):
    trace = plan['trace_id']
    steps = plan['steps']
    ids = [s['id'] for s in steps]
    if not trace or not ids or len(ids) != len(set(ids)):
        raise ValueError('A trace and unique planned steps are required')
    byid = {s['id']: s for s in steps}
    visited, active, ordered = set(), set(), []
    def visit(key):
        if key not in byid or key in active:
            raise ValueError('Missing or cyclic dependency')
        if key in visited:
            return
        active.add(key)
        for dep in byid[key]['depends_on']:
            visit(dep)
        active.remove(key)
        visited.add(key)
        ordered.append(key)
    for step in steps:
        if not step.get('owner') or not step.get('acceptance'):
            raise ValueError('Every task needs an owner and acceptance')
        visit(step['id'])
    issues, rows, finished = [], [], set()
    grouped = {key: [] for key in ids}
    for index, event in enumerate(events):
        if event.get('trace_id') != trace or event.get('step_id') not in grouped:
            issues.append('Unmatched trace or task event')
            continue
        grouped[event['step_id']].append((index, event))
    operations = set()
    for key in ordered:
        step = byid[key]; local = []; events_for_step = grouped[key]
        kinds = [e.get('kind') for _, e in events_for_step]
        if kinds != ['request', 'response', 'validation']:
            local.append('Missing, repeated or out-of-order request, response or validation')
        else:
            (start, request), (_, response), (_, check) = events_for_step
            operation = request.get('operation_id')
            if operation in operations:
                local.append('Operation identity reused by another task')
            operations.add(operation)
            if not operation or any(e.get('operation_id') != operation for e in (response, check)):
                local.append('Response or check does not match the request')
            if request.get('source_version') != step.get('source_version'):
                local.append('Source version changed or was not bound')
            if not step.get('source_version'):
                local.append('No current source version')
            for dep in step['depends_on']:
                evidence = grouped[dep]
                if not evidence or evidence[-1][0] >= start or dep not in finished:
                    local.append('Prerequisite has no earlier verified result: '+dep)
            if response.get('status') != 'returned' or check.get('status') != 'passed':
                local.append('Response or acceptance did not pass')
            artifact = response.get('artifact', {})
            path = Path(artifact.get('path', ''))
            try:
                valid = path.is_absolute() and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == artifact.get('sha256')
            except OSError:
                valid = False
            if not valid or check.get('artifact_sha256') != artifact.get('sha256'):
                local.append('Checked output is missing, changed or mismatched')
            if not check.get('evidence'):
                local.append('No acceptance evidence recorded')
        if not local:
            finished.add(key)
        issues.extend(key+': '+x for x in local)
        rows.append({'id':key, 'owner':step['owner'], 'acceptance':step['acceptance'],
                     'status':'verified' if not local else 'unverified', 'issues':local})
    return {'trace_id':trace, 'status':'verified' if not issues else 'needs-review',
            'steps':rows, 'issues':issues,
            'scope':'Receipt ordering and artifact integrity; declared acceptance is not semantic proof.'}


if __name__ == '__main__':
    import argparse
    import json
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('capture',type=Path)
    a=p.parse_args()
    try:
        capture=json.loads(a.capture.read_text(encoding='utf-8'))
        result=verify(capture['plan'],capture['events'])
        print(json.dumps(result,indent=2))
        raise SystemExit(0 if result['status']=='verified' else 1)
    except (OSError,ValueError,KeyError,TypeError) as error:
        p.exit(2,str(error)+'\n')
