"""Bounded explicit instrumentation of local callbacks, never a shell executor."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from native_activity import emit_activity, validate_event


class AlreadyRecorded(RuntimeError):
    """Reconcile the existing operation rather than replaying its callbacks."""


class NativeExecution:
    """One task owner. Callbacks execute once; completion needs an actual check.

    Public descriptions are caller-selected single lines. Exception messages and
    callback results are never logged automatically. No heartbeat or retries.
    """
    def __init__(self, root, task_id, title, *, chat_id=None, parent_task_id=None,
                 model=None, reasoning_effort=None, project_id=None, agent_id=None):
        self.root = root
        self.identity = dict(task_id=task_id, chat_id=chat_id or os.environ.get('CODEX_THREAD_ID'))
        self.start = dict(title=title, provenance='native-execution:explicit-local-callback')
        for key, value in dict(parent_task_id=parent_task_id, model=model,
                               reasoning_effort=reasoning_effort, project_id=project_id,
                               agent_id=agent_id).items():
            if value is not None:
                self.start[key] = value
        if agent_id is not None:
            # Attribution shape only. RoutedExecution separately checks the
            # actual published role and admission policy before any callback.
            validate_event(dict(self.identity, event_id=f'{task_id}:started',
                                type='started', **self.start))
        self.active = False
        self.accepted = False
        self.stages = 0
        self.used_stage_ids = set()
        self.checked_stage_ids = set()

    def _event(self, suffix, kind, **fields):
        event = dict(self.identity, event_id=f'{self.identity["task_id"]}:{suffix}', type=kind, **fields)
        return emit_activity(self.root, event)

    def __enter__(self):
        receipt = self._event('started', 'started', **self.start)
        if receipt['duplicate']:
            raise AlreadyRecorded('Existing task must be reconciled; callbacks were not replayed')
        self.active = True
        return self

    def _require_active(self):
        if not self.active:
            raise RuntimeError('execution is not active')

    def stage(self, stage_id, label, callback, *, requires=tuple(), check=None,
              reads=None, area_refs=None, edges=None, outputs=None):
        """Record boundary before callback; record supplied observations after return.

        Supply reads only when this callback actually reads those inputs. A failed
        callback cannot assert them. Output pointers require caller artifact checks.
        """
        self._require_active()
        if stage_id in self.used_stage_ids:
            raise AlreadyRecorded('Stage identity already used; callback was not replayed')
        # Dependencies must already have executed and passed an explicit check.
        # Forward/self references cannot enter this sequential graph, so cycles
        # are impossible. A mere returned callback is not a checked predecessor.
        if (not isinstance(requires, tuple) or len(requires) > 32
                or any(not isinstance(item, str) for item in requires)
                or stage_id in requires or any(item not in self.checked_stage_ids for item in requires)):
            self._fail()
            raise RuntimeError('Dependencies require exact previously checked stage identities')
        if check is not None and not callable(check):
            self._fail()
            raise ValueError('Stage check must be callable')
        observed = dict(summary=label)
        for key, value in dict(reads=reads, area_refs=area_refs, edges=edges, outputs=outputs).items():
            if value is not None:
                observed[key] = value
        # Fail input validation before starting any callback or logging any effects.
        validate_event(dict(self.identity, event_id=f'{self.identity["task_id"]}:{stage_id}:returned',
                            type='step', **observed))
        receipt = self._event(f'{stage_id}:began', 'step', summary=f'Began: {label}')
        if receipt['duplicate']:
            raise AlreadyRecorded('Existing stage must be reconciled; callback was not replayed')
        self.used_stage_ids.add(stage_id)
        self.accepted = False
        try:
            result = callback()
            if check is not None and check(result) is not True:
                raise RuntimeError('Stage check did not pass')
            self._event(f'{stage_id}:returned', 'step', **observed)
        except BaseException:
            self._fail()
            raise
        self.stages += 1
        if check is not None:
            self.checked_stage_ids.add(stage_id)
        return result

    def accept(self, check_id, label, check, *, requires=tuple()):
        """Execute a local acceptance callback; literal True is required."""
        self.stage(check_id, label, check, requires=requires, check=lambda result: result is True)
        self.accepted = True

    def complete(self, summary='Acceptance check passed'):
        self._require_active()
        if not self.accepted or not self.stages:
            raise RuntimeError('Completion requires an executed acceptance check')
        self._event('completed', 'completed', summary=summary)
        self.active = False

    def _fail(self):
        if self.active:
            try:
                self._event('failed', 'failed', summary='Local execution failed; reconcile private evidence before retry')
            finally:
                self.active = False

    def __exit__(self, exc_type, exc, traceback):
        if self.active:
            self._fail()
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--chat-id', default=os.environ.get('CODEX_THREAD_ID'))
    parser.add_argument('--parent-task-id')
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--expected-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        if len(args.expected_sha256) != 64 or any(c not in '0123456789abcdef' for c in args.expected_sha256):
            raise ValueError('Expected SHA256 must be 64 lowercase hex characters')
        path = args.source.resolve(strict=True)
        def read_source():
            with path.open('rb') as stream:
                data = stream.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise ValueError('Source exceeds bounded read')
            return hashlib.sha256(data).hexdigest()
        with NativeExecution(args.root, args.task_id, 'Check local source integrity',
                             chat_id=args.chat_id, parent_task_id=args.parent_task_id) as run:
            digest = run.stage('source-read', 'Read local source for integrity check', read_source,
                               check=lambda result: result == args.expected_sha256,
                               reads=[dict(label='Local source', reference=str(path))])
            run.accept('hash-check', 'Check source SHA256', lambda: digest == args.expected_sha256,
                       requires=('source-read',))
            run.complete()
        print(json.dumps(dict(checked=True, sha256=digest)))
        return 0
    except Exception:
        print(json.dumps({'error': 'Local source check failed; reconcile task and private evidence'}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
