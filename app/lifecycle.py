"""Bounded native-chat recall and proof-bound cleanup of owned scratch files.

Never constructs Brain or mutates its database. Cleanup defaults to a dry run.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

from history_recall import search as history_search, verify as verify_history, STOP
from read_models import ReadModels

ROOT = Path(__file__).resolve().parents[1]
ID = re.compile(r'[a-z0-9][a-z0-9-]{0,63}\Z')
HASH = re.compile(r'[a-f0-9]{64}\Z')
EXTENSIONS = {'.tmp', '.log', '.txt', '.json', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.wav', '.mp3', '.mp4'}
KINDS = {'preview', 'test-output', 'temporary-file'}

def now(): return datetime.now(timezone.utc).isoformat()
def encoded(value): return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024*1024), b''): result.update(block)
    return result.hexdigest()

def recall(root, query, project_id='', domain=None):
    """Read existing projections and historical excerpts, with no writes."""
    if not isinstance(query, str) or not 1 <= len(query) <= 12000:
        raise ValueError('Provide an outcome query of 1–12000 characters.')
    if project_id and (not isinstance(project_id, str) or not ID.fullmatch(project_id)):
        raise ValueError('Invalid registered project ID.')
    root = Path(root).resolve(); reader = ReadModels(root); state = reader.read('state')
    objects = {(r['kind'], r['id']): r for r in state['objects'] if not r['archived']}
    project = objects.get(('project', project_id)) if project_id else None
    if project_id and project is None: raise ValueError('The selected project is not active in the published state.')
    linked = [ref.split(':', 1)[1] for ref in project['data'].get('refs', []) if ref.startswith('memory:')] if project else []
    tokens = set(re.findall(r'\w+', query.lower()))-STOP
    candidates = []
    for (kind, id), row in objects.items():
        if kind != 'memory' or not state.get('memory_freshness', {}).get(id, {}).get('current'): continue
        data = row['data']; name = set(re.findall(r'\w+', data['name'].lower()))
        words = set(re.findall(r'\w+', ' '.join(str(data.get(k,'')) for k in ('name','content','source')).lower()))
        explicit = bool(re.search(r'(?<![a-z0-9-])'+re.escape(id)+r'(?![a-z0-9-])', query.lower()))
        matched = len(tokens & words)
        if not explicit and not matched: continue
        candidates.append((explicit, matched+2*len(tokens & name), id in linked, row))
    candidates.sort(key=lambda item:(-item[0], -item[1], -item[2], item[3]['id']))
    memory = []
    for _, _, _, row in candidates[:6]:
        data = row['data']; content = data.get('content', '')
        memory.append({'id': row['id'], 'version': row['version'], 'citation': '['+row['id']+'@'+str(row['version'])+']',
                       'name': data['name'], 'evidence_type': data.get('evidence_type', 'unspecified'),
                       'source': data.get('source', ''), 'excerpt': content[:1200], 'truncated': len(content)>1200})
    history = history_search(root, query, limit=4, project_path=project['data']['path'] if project else None, domain=domain)
    verify_history(root, history)
    selected = ({'id': project['id'], 'version': project['version'], **{k: project['data'].get(k, '') for k in ('name', 'scope', 'path')}} if project else None)
    linked_skills = [objects[('skill', ref.split(':', 1)[1])] for ref in project['data'].get('refs', []) if ref.startswith('skill:') and ('skill', ref.split(':', 1)[1]) in objects] if project else []
    return {'query': query, 'project': selected, 'domain': domain, 'publication': state['_view'], 'memory': memory, 'history': history,
            'project_skills': [{'id': r['id'], 'version': r['version'], 'name': r['data']['name'], 'description': r['data'].get('description', '')} for r in linked_skills[:12]],
            'worker_busy': bool(state.get('worker_busy')), 'authority': 'Current owner request controls. Historical excerpts retain their original date and scope, not present permission.',
            'next': 'Load only the selected domain master and exact skills. If this publication is stale, verify current records through the running backend before a write.'}

def checked_path(root, relative, must_exist=True):
    if not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative:
        raise ValueError('Use a relative project path with forward slashes.')
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(p in ('..', '.') for p in relative.split('/')) or '' in relative.split('/'):
        raise ValueError('Path traversal or empty path component is not allowed.')
    path = root.joinpath(*pure.parts)
    current = root
    for part in pure.parts:
        current = current/part
        try: info = current.lstat()
        except FileNotFoundError: continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024):
            raise ValueError('Symlinks and reparse points cannot be cleanup inputs.')
    if not path.resolve().is_relative_to(root): raise ValueError('Path escapes the canonical project.')
    if must_exist and not path.is_file(): raise ValueError('Required file is missing: '+relative)
    return path

def require_hash(value):
    if not isinstance(value, str) or not HASH.fullmatch(value): raise ValueError('An exact SHA-256 is required.')
    return value

def log_path(root): return checked_path(root, 'store/lifecycle/events.jsonl', must_exist=False)

def previous_deletions(root, manifest_id):
    path = log_path(root); deleted = set()
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            try: record = json.loads(line)
            except ValueError: continue
            if record.get('manifest_id') == manifest_id and record.get('event') == 'deleted':
                deleted.add((record['path'], record['sha256']))
    return deleted

def cleanup_plan(root, manifest):
    root = Path(root).resolve()
    if not isinstance(manifest, dict) or set(manifest) != {'work_id', 'completed', 'files'} or manifest['completed'] is not True:
        raise ValueError('Cleanup needs a completed work manifest with work_id and files.')
    work = manifest['work_id']; entries = manifest['files']
    if not isinstance(work, str) or not ID.fullmatch(work): raise ValueError('Use a lowercase work ID.')
    if not isinstance(entries, list) or len(entries)>100: raise ValueError('List at most 100 explicit disposable files.')
    manifest_id = hashlib.sha256(encoded(manifest)).hexdigest(); deleted = previous_deletions(root, manifest_id)
    result = []; seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'path', 'sha256', 'kind', 'reason', 'replacement', 'validation'}:
            raise ValueError('Each file needs path, sha256, kind, reason, replacement and validation.')
        if entry['kind'] not in KINDS or not isinstance(entry['reason'], str) or not 1 <= len(entry['reason'].strip()) <= 2000:
            raise ValueError('State the disposable file kind and a concrete retention reason.')
        path = checked_path(root, entry['path'], must_exist=False); expected = require_hash(entry['sha256'])
        if not path.is_relative_to(root/'runtime/scratch'/work) or path.suffix.lower() not in EXTENSIONS:
            raise ValueError('Cleanup supports only explicit preview/test/temp files in runtime/scratch/'+work+'/ .')
        if entry['path'] in seen: raise ValueError('A cleanup path may appear only once.')
        seen.add(entry['path'])
        replacement, validation = entry['replacement'], entry['validation']
        for binding in (replacement, validation):
            if not isinstance(binding, dict) or set(binding) != {'path', 'sha256'}: raise ValueError('Replacement and validation must bind path and sha256.')
            require_hash(binding['sha256'])
        target = checked_path(root, replacement['path']); proof = checked_path(root, validation['path'])
        if target.is_relative_to(root/'runtime/scratch') or proof.is_relative_to(root/'runtime/scratch'):
            raise ValueError('Replacement and validation must be retained outside disposable scratch.')
        if digest(target) != replacement['sha256'] or digest(proof) != validation['sha256']:
            raise ValueError('The replacement or its validation receipt changed.')
        report = json.loads(proof.read_text(encoding='utf-8'))
        if report.get('status') != 'passed' or report.get('artifact') != replacement or not isinstance(report.get('method'), str) or not report['method'].strip():
            raise ValueError('Validation must record a passed check of this exact replacement and the method used.')
        try: datetime.fromisoformat(report['checked_at'])
        except (KeyError, ValueError, TypeError): raise ValueError('The validation receipt needs its actual checked_at time.')
        if not path.exists():
            if (entry['path'], expected) not in deleted: raise ValueError('Scratch file is missing without a completed deletion receipt.')
            action = 'already-deleted'; size = 0
        else:
            if not path.is_file() or digest(path) != expected: raise ValueError('Scratch file changed; create a new reviewed manifest.')
            action = 'delete'; size = path.stat().st_size
        result.append({'path': entry['path'], 'sha256': expected, 'action': action, 'bytes': size,
                       'reason': entry['reason'], 'retained_replacement': replacement, 'validation': validation})
    return {'manifest_id': manifest_id, 'work_id': work, 'files': result, 'bytes_to_remove': sum(r['bytes'] for r in result)}

@contextmanager
def scratch_lease(root, work_id):
    """Producers and cleanup hold this lease while touching the same work scratch."""
    if not ID.fullmatch(work_id): raise ValueError('Invalid scratch work ID.')
    root = Path(root).resolve(); folder = root/'runtime/scratch'/work_id
    checked_path(root, 'runtime/scratch/'+work_id+'/owner.lock', must_exist=False)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder/'owner.lock').open('a+b') as handle:
        if handle.tell()==0: handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error: raise ValueError('Scratch is currently leased by another process.') from error
        try: yield folder
        finally:
            handle.seek(0)
            if os.name == 'nt': msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(handle, fcntl.LOCK_UN)

def append_event(root, value):
    path = log_path(root); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('ab+') as output:
        if output.tell():
            output.seek(-1, 2)
            if output.read(1) != b'\n': output.write(b'\n')
        output.write(encoded(value)+b'\n'); output.flush(); os.fsync(output.fileno())

def check_idle(root):
    state = ReadModels(root).read('state')
    if state['_view']['stale']: raise ValueError('A fresh backend publication is required before cleanup.')
    if state.get('worker_busy') or any(r['state'] in ('queued', 'running', 'cancelling') for r in state.get('runs', [])):
        raise ValueError('Company Brain work is active; finish or stop it before cleanup.')
    requests = root/'runtime/queue/requests'; receipts = root/'runtime/queue/receipts'
    if any(not (receipts/p.name).exists() for p in requests.glob('*.json')):
        raise ValueError('Pending or uncertain commands must finish before cleanup.')

def cleanup(root, manifest, apply=False):
    root = Path(root).resolve(); plan = cleanup_plan(root, manifest)
    if not apply: return plan | {'dry_run': True, 'changed': False}
    check_idle(root)
    with scratch_lease(root, plan['work_id']):
        # Recheck after admission; files can have changed since a prior dry run.
        plan = cleanup_plan(root, manifest)
        for item in plan['files']:
            if item['action'] == 'already-deleted': continue
            event = {'at': now(), 'manifest_id': plan['manifest_id'], 'work_id': plan['work_id'], **item}
            append_event(root, event | {'event': 'delete-started'})
            path = checked_path(root, item['path'])
            if digest(path) != item['sha256']: raise ValueError('Scratch changed at deletion; retained.')
            path.unlink()
            append_event(root, event | {'event': 'deleted', 'at': now()})
    return plan | {'dry_run': False, 'changed': any(r['action']=='delete' for r in plan['files']), 'retention_log': 'store/lifecycle/events.jsonl'}

def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--root', default=str(ROOT))
    actions = parser.add_subparsers(dest='action', required=True)
    recall_args = actions.add_parser('recall'); recall_args.add_argument('--query', required=True); recall_args.add_argument('--project', default=''); recall_args.add_argument('--domain', choices=['lore','linkedin-blog','thesis-writing','prompt-engineering'])
    review_args = actions.add_parser('learning-review', help='Read unreviewed procedure proposals; no execution or promotion.')
    review_args.add_argument('--query', default=''); review_args.add_argument('--project', default=''); review_args.add_argument('--limit', type=int, default=8)
    curation_args = actions.add_parser('skill-curation', help='Read bounded skill overlap and usage review hints; no changes.')
    curation_args.add_argument('--project', default=''); curation_args.add_argument('--limit', type=int, default=8); curation_args.add_argument('--query', default='')
    cleanup_args = actions.add_parser('cleanup'); cleanup_args.add_argument('manifest', type=Path); cleanup_args.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.action == 'recall': result = recall(args.root, args.query, args.project, args.domain)
    elif args.action == 'learning-review':
        from learning_review import review
        result = review(ReadModels(args.root).read('state'), args.query, args.project, args.limit)
    elif args.action == 'skill-curation':
        from skill_curation import read_curation
        result = read_curation(args.root, ReadModels(args.root).read('state'), args.project, args.limit, query=args.query)
    else: result = cleanup(args.root, json.loads(args.manifest.read_text(encoding='utf-8-sig')), args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__': main()
