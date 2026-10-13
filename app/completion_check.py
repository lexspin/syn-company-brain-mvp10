"""Bind native completion to existing queue effects and current artifact bytes.

This is an integrity check, not semantic review or an external-tool attestation.
The local filesystem/sole writer remain the trust boundary; an OS administrator
can alter local evidence. This module never executes or retries a command.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def data_hash(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''): h.update(block)
    return h.hexdigest()


def command_receipt(root, identity):
    if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{32}', identity):
        raise ValueError('Supply an actual canonical command receipt ID.')
    queue = Path(root)/'runtime/queue'
    try:
        request, begun, receipt = [json.loads((queue/group/(identity+'.json')).read_text(encoding='utf-8'))
                                   for group in ('requests', 'begun', 'receipts')]
    except (OSError, ValueError) as exc:
        raise ValueError('Missing/invalid command evidence; reconcile the existing receipt, never replay: '+identity) from exc
    if (any(not isinstance(v, dict) for v in (request, begun, receipt)) or
        any(v.get('id') != identity for v in (request, begun, receipt)) or
        receipt.get('action') != request.get('action') or begun.get('action') != request.get('action') or
        receipt.get('ok') is not True or receipt.get('state') != 'completed' or
        receipt.get('requested_at') != request.get('requested_at')):
        raise ValueError('Command evidence is incomplete, failed or mismatched: '+identity)
    return request, receipt


def same_record(left, right):
    return all(left.get(k) == right.get(k) for k in ('kind', 'id', 'version', 'data', 'archived', 'updated'))


def source_snapshot(root, key, records):
    """Use the scanner's exact snapshot format without calling the live HTTP writer."""
    from review_scan import digest
    root = Path(root).resolve()
    if not isinstance(key, str) or ':' not in key: raise ValueError('Invalid reviewed source identity.')
    kind, name = key.split(':', 1)
    if kind in ('agent', 'skill', 'loop', 'stack', 'project', 'memory'):
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', name): raise ValueError('Invalid record source.')
        record = records.get(key)
        if record is None: return None
        return {'hash': digest(json.dumps(record, sort_keys=True).encode()),
                'version': record['version'], 'archived': bool(record['archived'])}
    if kind in ('file', 'native'):
        base = root if kind == 'file' else Path.home()/'.codex/skills'
        rel = Path(name)
        if rel.is_absolute() or '..' in rel.parts or not rel.parts: raise ValueError('Invalid source path.')
        path = (base/rel).resolve()
        if not path.is_relative_to(base.resolve()): raise ValueError('Source leaves its owning root.')
        if kind == 'file' and len(rel.parts) > 1 and rel.parts[0] not in ('app','evaluations','company','routines','docs','skills'):
            raise ValueError('Source is outside the review scanner scope.')
    elif kind == 'configuration':
        path = Path(name).resolve()
        if path not in ((Path.home()/'.codex/config.toml').resolve(), (root/'runtime/creative/storage.json').resolve()):
            raise ValueError('Unknown configuration source.')
    else: raise ValueError('Unknown reviewed source kind.')
    return {'hash': file_hash(path)} if path.is_file() else None


def displayed_records(brain):
    from presentation import display_records
    return {r['kind']+':'+r['id']: r for r in display_records(brain.list(archived=True))}


def artifacts_check(root, artifacts, result, get):
    if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 32:
        raise ValueError('Completion requires 1–32 checked output files.')
    roots = [Path(root).resolve()]
    for ref in result['data'].get('refs', []):
        if ref.startswith('project:'):
            project = get('project', ref.split(':', 1)[1])
            if not project['archived']: roots.append(Path(project['data']['path']).resolve())
    content_sha = hashlib.sha256(result['data'].get('content','').encode()).hexdigest()
    provenance = result['data'].get('capture',{}).get('provenance',{})
    bound_output = False
    for artifact in artifacts:
        if not isinstance(artifact, dict) or set(artifact) != {'path','sha256'}:
            raise ValueError('Artifact must bind an absolute path and SHA256.')
        if not isinstance(artifact['path'], str) or not isinstance(artifact['sha256'], str):
            raise ValueError('Invalid artifact binding.')
        path = Path(artifact['path'])
        if not path.is_absolute() or not any(path.resolve().is_relative_to(r) for r in roots):
            raise ValueError('Artifact must remain in the OS or a linked registered project root.')
        if not path.is_file() or file_hash(path) != artifact['sha256']:
            raise ValueError('Checked artifact is missing or changed: '+str(path))
        bound_output |= artifact['sha256'] == content_sha or (
            isinstance(provenance.get('source_file'),str) and
            path.resolve() == Path(provenance['source_file']).resolve() and
            artifact['sha256'] == provenance.get('source_sha256'))
    if not bound_output:
        raise ValueError('Checked output must match saved result content or its captured source path/hash.')


def validate_completion(brain, request_id, request_version, previous, data, *, current_sources=True):
    check = data.get('completion_check')
    fields = {'schema_version','request_id','request_version','request_sha256','claimant','loop_id','loop_version',
              'claim_receipt','result_receipt','result_id','result_version','result_sha256','artifacts','review_sources'}
    if not isinstance(check, dict) or set(check) != fields or check.get('schema_version') != 1:
        raise ValueError('New completion requires receipt-bound completion_check; use app/completion_check.py.')
    if (check['request_id'] != request_id or check['request_version'] != request_version or
        check['request_sha256'] != data_hash(previous) or check['claimant'] != previous.get('claimant') or
        check['loop_id'] != data['loop_id'] or check['loop_version'] != data['loop_version'] or
        check['result_id'] != data['result_ref']):
        raise ValueError('Completion check does not bind this exact claimed request and workflow.')
    claim_request, claim = command_receipt(brain.root, check['claim_receipt'])
    payload = claim_request.get('payload', {})
    claimed = claim.get('result', {})
    if (claim_request['action'] != 'save' or payload.get('kind') != 'memory' or payload.get('id') != request_id or
        payload.get('version') != request_version-1 or payload.get('data') != previous or
        claimed.get('kind') != 'memory' or claimed.get('id') != request_id or claimed.get('version') != request_version or
        claimed.get('data') != previous or claimed.get('archived') or previous.get('request_state') != 'running'):
        raise ValueError('Claim receipt does not match the current running request; reconcile ownership.')
    result_request, result_receipt = command_receipt(brain.root, check['result_receipt'])
    result = brain.get('memory', data['result_ref'])
    if result_request['action'] not in ('save', 'archive-research') or not same_record(result_receipt.get('result', {}), result):
        raise ValueError('Result receipt is not the exact current saved result.')
    if result_request['action'] == 'save':
        rp = result_request.get('payload', {})
        if (rp.get('kind') != 'memory' or rp.get('id') != result['id'] or
            rp.get('version', 0) != result['version']-1 or rp.get('data') != result['data']):
            raise ValueError('Result save request does not match its receipt.')
    from datetime import datetime
    try:
        if datetime.fromisoformat(result_request['requested_at']) < datetime.fromisoformat(claim['finished_at']):
            raise ValueError('Result must be saved after the recorded claim.')
    except (KeyError, TypeError) as exc: raise ValueError('Receipt timestamps are unavailable.') from exc
    if (result['archived'] or result['data'].get('type') == 'native-work-request' or
        check['result_version'] != result['version'] or check['result_sha256'] != data_hash(result['data']) or
        not {'memory:'+request_id, 'loop:'+data['loop_id']} <= set(result['data'].get('refs', [])) or
        'memory:'+result['id'] not in data.get('refs', [])):
        raise ValueError('Result must bind this request, workflow, current result version/hash and reciprocal link.')
    artifacts_check(brain.root, check['artifacts'], result, brain.get)
    sources = check['review_sources']
    if not isinstance(sources, dict) or len(sources) > 512: raise ValueError('Invalid reviewed source bindings.')
    if current_sources:
        loop = brain.get('loop', check['loop_id'])
        if loop['archived'] or loop['version'] != check['loop_version']:
            raise ValueError('Reviewed workflow changed or was archived; review with the current workflow.')
        records = displayed_records(brain)
        for key, expected in sources.items():
            if source_snapshot(brain.root, key, records) != expected:
                raise ValueError('Reviewed source changed: '+key+'; preserve the attempt and review the current version.')
    return {'status':'receipt-and-artifact-bound', 'semantic_validation':'not-established-by-integrity-check'}


def build(brain, request_id, claim_receipt, result_receipt, artifacts, sources):
    request = brain.get('memory', request_id)
    if request['data'].get('request_state') != 'running': raise ValueError('Build a check only for an owned running request.')
    _, receipt = command_receipt(brain.root, result_receipt)
    result = receipt['result']; data = request['data']; records = displayed_records(brain)
    loop = brain.get('loop', data['loop_id'])
    if loop['archived'] or loop['version'] != data['loop_version']:
        raise ValueError('Requested workflow changed; retain the result and fail for a fresh review.')
    if data.get('change_event_id'):
        from change_events import validate_sources
        validate_sources(brain, data.get('change_sources'))
    check = {'schema_version':1, 'request_id':request_id, 'request_version':request['version'],
             'request_sha256':data_hash(data), 'claimant':data['claimant'], 'loop_id':data['loop_id'],
             'loop_version':data['loop_version'], 'claim_receipt':claim_receipt, 'result_receipt':result_receipt,
             'result_id':result['id'], 'result_version':result['version'], 'result_sha256':data_hash(result['data']),
             'artifacts':[{'path':str(Path(p).resolve()), 'sha256':file_hash(p)} for p in artifacts],
             'review_sources':{k:source_snapshot(brain.root, k, records) for k in sources}}
    done = data | {'result_ref':result['id'], 'refs':sorted(set(data.get('refs', []))|{'memory:'+result['id']}), 'completion_check':check}
    validate_completion(brain, request_id, request['version'], data, done)
    return check


class PublishedRecords:
    """Read-only adapter; never opens a second Brain writer."""
    def __init__(self, root):
        from read_models import ReadModels
        self.root = Path(root).resolve()
        try: state = ReadModels(self.root).read('state')
        except (OSError,ValueError) as exc:
            raise ValueError('Canonical published state unavailable; reconcile publication before building evidence.') from exc
        if state['_view']['stale'] or Path(state.get('root','')).resolve() != self.root:
            raise ValueError('Canonical published state is stale or belongs to another root; wait/reconcile.')
        self.records = {r['kind']+':'+r['id']:r for r in state['objects']}
    def get(self, kind, identity):
        try: return self.records[kind+':'+identity]
        except KeyError as exc: raise ValueError('Record does not exist.') from exc
    def list(self, archived=False): return list(self.records.values())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=ROOT); p.add_argument('--request', required=True)
    p.add_argument('--claim-receipt', required=True); p.add_argument('--result-receipt', required=True)
    p.add_argument('--artifact', action='append', required=True); p.add_argument('--source', action='append', default=[])
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    check = build(PublishedRecords(args.root), args.request, args.claim_receipt, args.result_receipt, args.artifact, args.source)
    args.output.write_text(json.dumps(check, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'output':str(args.output.resolve()), 'status':'receipt-and-artifact-bound',
                      'scope':'Integrity only. Run meaningful acceptance before completion; no commands replayed.'}))


if __name__ == '__main__': main()
