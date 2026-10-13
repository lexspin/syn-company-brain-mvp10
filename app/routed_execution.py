"""Explicit gate for participating substantive Brain tasks; no host interception.

Only independent native telemetry is written here. Archives must be performed by
the existing canonical queue client and their durable receipt supplied afterward.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler

from memory_mcp import MemoryHub, NoRedirect
from native_execution import NativeExecution
from operating_policy import interpret, require_allowed

CANONICAL_ROOT = Path('C:/Users/USER/OneDrive/SYN Company Brain/V2').resolve()
CHECKER = Path('C:/Users/USER/.codex/skills/company-brain-harness/scripts/check.py')
ID = re.compile(r'[a-z0-9][a-z0-9-]{0,63}\Z')
HASH = re.compile(r'[a-f0-9]{64}\Z')


class RetentionPending(RuntimeError):
    """Reconcile this receipt; never replay work or submit a replacement effect."""


class PublishedClient:
    """Real default: bounded loopback GETs, no redirects, proxies or writes."""
    def __init__(self, base='http://127.0.0.1:14699'):
        self.hub = MemoryHub(base, native_read_only=True)

    def state(self):
        return self.hub.state()

    def knowledge(self, memory_id):
        return self.hub.call('get_knowledge', {'id': memory_id})

    def search(self, memory_id):
        return self.hub.call('search_knowledge', {'query': memory_id, 'limit': 8})

    def receipt(self, receipt_id):
        with build_opener(ProxyHandler({}), NoRedirect()).open(
                Request(self.hub.base+'/api/command?'+urlencode({'id': receipt_id}), method='GET'), timeout=8) as response:
            raw = response.read(1024*1024+1)
        if len(raw) > 1024*1024:
            raise ValueError('Receipt exceeds bounded read.')
        return json.loads(raw)


def evaluate_contract(contract):
    """Load the existing trusted checker, never a caller-selected program."""
    spec = importlib.util.spec_from_file_location('_routed_evidence_checker', CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.evaluate(contract)


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def semantic(row):
    return {key: value for key, value in row['data'].items() if key != 'refs'}


class RoutedExecution(NativeExecution):
    """Bind routing, actual checks and canonical retained evidence before success.

    Injected clients/checkers are trusted test adapters, not caller JSON options.
    This is an instruction-level contract for participating Python callers, not
    a filesystem sandbox or proof that arbitrary acceptance prose is true.
    """
    def __init__(self, root, task_id, title, *, project_id, skill_versions,
                 contract_path, client=None, checker=None, agent_id=None,
                 agent_version=None, **metadata):
        if Path(root).resolve() != CANONICAL_ROOT:
            raise ValueError('Routed execution requires the canonical V2 root.')
        if not isinstance(project_id, str) or not ID.fullmatch(project_id):
            raise ValueError('A registered project is required.')
        if not isinstance(skill_versions, dict) or not 1 <= len(skill_versions) <= 8 or any(
                not isinstance(key, str) or not ID.fullmatch(key) or type(version) is not int or version < 1
                for key, version in skill_versions.items()):
            raise ValueError('Bind one to eight exact selected skill versions.')
        if agent_id is None and agent_version is not None or agent_id is not None and (
                not isinstance(agent_id, str) or not ID.fullmatch(agent_id)
                or type(agent_version) is not int or agent_version < 1):
            raise ValueError('Bind a selected registered agent and its exact expected version.')
        super().__init__(root, task_id, title, project_id=project_id, agent_id=agent_id, **metadata)
        self.project_id, self.skill_versions = project_id, dict(skill_versions)
        self.agent_id, self.agent_version = agent_id, agent_version
        self.agent_record, self.agent_skill_records = None, {}
        self.client, self.checker = client or PublishedClient(), checker or evaluate_contract
        self.contract_path = self._private_path(contract_path)
        self.plan, self.contract_sha256 = self._read_contract(self.contract_path)
        self.acceptance_id = self.plan.get('acceptance_id')
        self.acceptance_ids = set()
        self.bound_records = {}
        self.source_records = {}
        self.gate_checks = None

    def _private_path(self, path):
        path = Path(path)
        if not path.is_absolute() or not path.resolve().is_relative_to(CANONICAL_ROOT/'runtime'):
            raise ValueError('Evidence contracts belong in canonical private runtime.')
        return path.resolve()

    @staticmethod
    def _read_contract(path):
        with path.open('rb') as handle:
            raw = handle.read(65537)
        if len(raw) > 65536:
            raise ValueError('Evidence contract exceeds 64 KiB.')
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError('Evidence contract must be an object.')
        return value, hashlib.sha256(raw).hexdigest()

    def _state(self):
        state = self.client.state()
        if not isinstance(state, dict) or not isinstance(state.get('root'), str) or Path(state['root']).resolve() != CANONICAL_ROOT:
            raise ValueError('Published workspace identity mismatch.')
        meta = state.get('_view', {})
        stamp = datetime.fromisoformat(meta.get('asof', ''))
        if stamp.tzinfo is None or meta.get('stale') or not -5 <= (datetime.now(timezone.utc)-stamp).total_seconds() <= 30:
            raise ValueError('Published state is stale or malformed.')
        rows = state.get('objects')
        if not isinstance(rows, list) or len(rows) > 12000:
            raise ValueError('Published record set is invalid or over bound.')
        return state, {(r['kind'], r['id']): r for r in rows}

    def _check_sources(self):
        sources = self.plan.get('sources')
        if not isinstance(sources, list) or not 1 <= len(sources) <= 32:
            raise ValueError('Bind bounded source file evidence.')
        for source in sources:
            if not isinstance(source, dict) or not isinstance(source.get('path'), str) or not Path(source['path']).is_absolute() or not HASH.fullmatch(str(source.get('sha256', ''))) or digest(source['path']) != source['sha256']:
                raise ValueError('Bound source changed or is malformed.')

    @staticmethod
    def _agent_skills(row):
        data = row.get('data', {})
        skills, refs = data.get('skills', []), data.get('refs', [])
        if not isinstance(skills, list) or not isinstance(refs, list) or len(skills) > 32:
            raise ValueError('Selected agent skill links are malformed or over bound.')
        ids = set()
        for ref in [*skills, *[ref for ref in refs if isinstance(ref, str) and ref.startswith('skill:')]]:
            if not isinstance(ref, str):
                raise ValueError('Selected agent skill links are malformed.')
            ident = ref[6:] if ref.startswith('skill:') else ref
            if not ID.fullmatch(ident):
                raise ValueError('Selected agent skill identity is malformed.')
            ids.add(ident)
        if not 1 <= len(ids) <= 32:
            raise ValueError('Bind one to 32 configured selected-agent skills.')
        return ids

    def _bind_agent(self, rows):
        binding = self.plan.get('agent_binding')
        if self.agent_id is None:
            if binding is not None:
                raise ValueError('Agent binding needs an explicitly selected agent.')
            return None
        if not isinstance(binding, dict) or set(binding) != {'id', 'version', 'role', 'skill_versions'}:
            raise ValueError('Bind the selected agent identity, role, version and exact linked skills.')
        if binding['id'] != self.agent_id or type(binding['version']) is not int or binding['version'] != self.agent_version:
            raise ValueError('Agent binding differs from the selected expected agent version.')
        agent = rows.get(('agent', self.agent_id))
        if agent is None or agent.get('archived') or type(agent.get('version')) is not int or agent.get('version') != self.agent_version:
            raise ValueError('Selected agent is unknown, archived or its version changed.')
        role = agent.get('data', {}).get('level') or agent.get('data', {}).get('role')
        if not isinstance(binding['role'], str) or not binding['role'].strip() or binding['role'] != role:
            raise ValueError('Selected agent role differs from its expected classification.')
        skills = binding['skill_versions']
        if not isinstance(skills, dict) or set(skills) != self._agent_skills(agent) or any(
                type(version) is not int or version < 1 for version in skills.values()):
            raise ValueError('Bind every configured selected-agent skill at an exact version.')
        for ident, version in skills.items():
            row = rows.get(('skill', ident))
            if row is None or row.get('archived') or row.get('version') != version:
                raise ValueError('Selected agent linked skill is missing, archived or changed.')
            self.agent_skill_records[('skill', ident)] = deepcopy(row)
        self.agent_record = deepcopy(agent)
        return agent

    def _check_agent(self, state, rows, *, admission=False):
        if self.agent_record is None:
            return
        records = {('agent', self.agent_id): self.agent_record, **self.agent_skill_records}
        for key, previous in records.items():
            current = rows.get(key)
            if current is None or current.get('archived') or semantic(current) != semantic(previous):
                raise ValueError('Bound agent role or linked skill semantics changed.')
            before, after = previous['data'].get('refs', []), current['data'].get('refs', [])
            if not isinstance(before, list) or not isinstance(after, list) or not set(before).issubset(after):
                raise ValueError('Bound agent role or skill lost an existing reference.')
            added = set(after) - set(before)
            if type(current.get('version')) is not int or current['version'] < previous['version'] or (
                    current['version'] != previous['version'] and not added) or (
                    current['version'] - previous['version'] > len(added)) or (
                    current['version'] == previous['version'] and added):
                raise ValueError('Bound agent role or linked skill version drifted.')
            for ref in added:
                memory = rows.get(('memory', ref[7:])) if isinstance(ref, str) and ref.startswith('memory:') else None
                if memory is None or memory.get('archived') or memory.get('data', {}).get('status') != 'accepted' or (
                        not state.get('memory_freshness', {}).get(memory['id'], {}).get('current')) or (
                        ':'.join(key) not in memory.get('data', {}).get('refs', [])):
                    raise ValueError('Agent reference drift is not verified reciprocal accepted retention.')
        if admission:
            policy = interpret(rows.get(('stack', 'operating-policy')), previously_configured=True)
            require_allowed(policy, 'task', rows[('agent', self.agent_id)])

    def __enter__(self):
        current_plan, plan_hash = self._read_contract(self.contract_path)
        if plan_hash != self.contract_sha256 or current_plan != self.plan:
            raise ValueError('The immutable routing contract changed before admission.')
        state, rows = self._state()
        policy = interpret(rows.get(('stack', 'operating-policy')), previously_configured=True)
        agent = self._bind_agent(rows)
        require_allowed(policy, 'task', agent)
        keys = [('project', self.project_id), *[('skill', key) for key in self.skill_versions]]
        for kind, key in keys:
            row = rows.get((kind, key))
            if row is None or row.get('archived') or kind == 'skill' and row['version'] != self.skill_versions[key]:
                raise ValueError('Selected project or exact skill version is unavailable.')
            self.bound_records[(kind, key)] = deepcopy(row)
        root = Path(self.bound_records[('project', self.project_id)]['data']['path']).resolve()
        if not root.is_dir() or not Path(self.plan.get('project_root', '')).is_absolute() or Path(self.plan.get('project_root', '')).resolve() != root:
            raise ValueError('Contract destination differs from registered project root.')
        expected_skills = sorted('skill:'+key+'@'+str(version) for key, version in self.skill_versions.items())
        if sorted(self.plan.get('skills', [])) != expected_skills:
            raise ValueError('Contract does not bind the exact selected skills.')
        for field in ('outcome', 'request_source'):
            if not isinstance(self.plan.get(field), str) or not self.plan[field].strip():
                raise ValueError('Bind the outcome and original request source.')
        tools = self.plan.get('tools')
        if not isinstance(tools, list) or not 1 <= len(tools) <= 32 or any(not isinstance(tool, str) or not tool.strip() or len(tool) > 160 for tool in tools) or len(set(tools)) != len(tools):
            raise ValueError('Declare a nonempty bounded set of exact selected tool names.')
        if self.plan.get('uncertain_effect') is not False:
            raise ValueError('Reconcile an uncertain existing effect before starting new work.')
        requirements = self.plan.get('requirements')
        if not isinstance(requirements, list) or not 2 <= len(requirements) <= 32:
            raise ValueError('Declare work and final acceptance requirements.')
        if any(not isinstance(item, dict) or not isinstance(item.get('id'), str) or not ID.fullmatch(item['id']) or not isinstance(item.get('description'), str) or not item['description'].strip() or not isinstance(item.get('depends_on'), list) or item.get('category') not in {'recall', 'tool-use', 'work', 'acceptance', 'audit'} for item in requirements):
            raise ValueError('Malformed requirement identity, description or dependencies.')
        self.requirements = {item['id']: item for item in requirements}
        if len(self.requirements) != len(requirements) or self.acceptance_id not in self.requirements:
            raise ValueError('Requirements need unique IDs and an exact acceptance ID.')
        if self.requirements[self.acceptance_id]['category'] != 'acceptance' or not any(r['category'] == 'work' for r in requirements):
            raise ValueError('Declare a checked work category and final acceptance category.')
        visited, visiting = set(), set()
        def visit(key):
            if key not in self.requirements or key in visiting:
                raise ValueError('Missing or cyclic requirement dependency.')
            if key in visited:return
            visiting.add(key)
            for dependency in self.requirements[key]['depends_on']:
                if not isinstance(dependency, str):raise ValueError('Malformed requirement dependency.')
                visit(dependency)
            visiting.remove(key);visited.add(key)
        for key in self.requirements:visit(key)
        self.project_root = root
        result_path = Path(self.plan.get('result_path', ''))
        if not result_path.is_absolute() or not result_path.resolve().is_relative_to(root):
            raise ValueError('Retained result summary must belong to the registered project.')
        self.result_path = result_path.resolve()
        paths = self.plan.get('artifact_paths')
        if not isinstance(paths, list) or not 1 <= len(paths) <= 64 or any(not isinstance(path, str) or not Path(path).is_absolute() or not Path(path).resolve().is_relative_to(root) for path in paths):
            raise ValueError('Declare exact permitted artifact paths within the registered root.')
        self.artifact_paths = {str(Path(path).resolve()) for path in paths}
        if len(self.artifact_paths) != len(paths) or str(self.result_path) not in self.artifact_paths:
            raise ValueError('Artifact paths must be unique and include the result summary.')
        self._check_sources()
        bindings = self.plan.get('source_bindings', {})
        if not isinstance(bindings, dict) or len(bindings) > 32:
            raise ValueError('Bound recall record versions exceed the source limit.')
        for ref, version in bindings.items():
            if not isinstance(ref, str) or not re.fullmatch(r'(memory|skill|project|loop|stack):[a-z0-9][a-z0-9-]{0,63}', ref) or type(version) is not int or version < 1:
                raise ValueError('Malformed recall source version binding.')
            key = tuple(ref.split(':', 1));row = rows.get(key)
            if row is None or row.get('archived') or row.get('version') != version or key[0]=='memory' and not state.get('memory_freshness', {}).get(key[1], {}).get('current'):
                raise ValueError('Bound recall source is missing, stale, archived or changed.')
            self.source_records[key] = deepcopy(row)
        return super().__enter__()

    def _check_stage_context(self):
        """Revalidate before callbacks; completion checks are too late for effects."""
        self._require_active()
        current_plan, plan_hash = self._read_contract(self.contract_path)
        if plan_hash != self.contract_sha256 or current_plan != self.plan:
            raise ValueError('The immutable routing contract changed.')
        self._check_sources()
        state, rows = self._state()
        self._check_agent(state, rows, admission=True)
        require_allowed(interpret(rows.get(('stack', 'operating-policy')), previously_configured=True),
                        'task', rows.get(('agent', self.agent_id)) if self.agent_id else None)
        for key, previous in {**self.bound_records, **self.source_records}.items():
            current = rows.get(key)
            if (current is None or current.get('archived') or current.get('version') != previous['version']
                    or semantic(current) != semantic(previous)
                    or key[0] == 'memory' and not state.get('memory_freshness', {}).get(key[1], {}).get('current')):
                raise ValueError('Bound stage context changed or is no longer current.')

    def stage(self, stage_id, label, callback, *, requires=tuple(), check=None, **observations):
        if stage_id not in self.requirements or tuple(self.requirements[stage_id].get('depends_on', [])) != requires:
            raise ValueError('Stage does not match the declared requirement and dependencies.')
        if check is None:
            raise ValueError('Every declared stage needs an executed check.')
        self._check_stage_context()
        return super().stage(stage_id, label, callback, requires=requires, check=check, **observations)

    def accept(self, check_id, label, check, *, requires=tuple()):
        if check_id != self.acceptance_id or not requires or not set(requires).issubset(self.checked_stage_ids-self.acceptance_ids):
            raise ValueError('Final acceptance must depend on checked non-acceptance work.')
        super().accept(check_id, label, check, requires=requires)
        self.acceptance_ids.add(check_id)

    def complete(self, summary='Checked result retained through canonical archive', *, evidence_path, receipt_id):
        self._require_active()
        if not self.accepted or set(self.requirements)-self.checked_stage_ids:
            raise ValueError('Completion needs every declared check and final acceptance.')
        if digest(self.contract_path) != self.contract_sha256:
            raise ValueError('The immutable routing contract changed.')
        if self._read_contract(self.contract_path)[0] != self.plan:
            raise ValueError('The in-memory routing snapshot changed.')
        evidence, evidence_hash = self._read_contract(self._private_path(evidence_path))
        for key in ('outcome', 'request_source', 'project_root', 'skills', 'tools', 'sources', 'source_bindings', 'agent_binding', 'acceptance_id', 'result_path', 'artifact_paths', 'max_attempts', 'timeout_seconds', 'uncertain_effect'):
            if evidence.get(key) != self.plan.get(key):
                raise ValueError('Completion evidence retargeted the routing contract.')
        shape = lambda items: [(r['id'], r['description'], r['depends_on'], r.get('category')) for r in items]
        if shape(evidence.get('requirements', [])) != shape(self.plan['requirements']):
            raise ValueError('Completion requirements differ from the immutable plan.')
        artifacts = evidence.get('artifacts', [])
        if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 64 or any(
                not isinstance(a.get('path'), str) or not Path(a['path']).is_absolute() or not Path(a['path']).resolve().is_relative_to(self.project_root) for a in artifacts):
            raise ValueError('Output evidence escaped its registered project root.')
        if not any(Path(a['path']).resolve() == self.result_path for a in artifacts):
            raise ValueError('Retained summary must be a checked artifact.')
        if {str(Path(a['path']).resolve()) for a in artifacts} != self.artifact_paths or len(artifacts) != len(self.artifact_paths):
            raise ValueError('Completion artifacts differ from the exact permitted paths.')
        self._check_sources()
        if self.checker(deepcopy(evidence)).get('action') != 'complete':
            raise ValueError('The existing evidence checker did not pass.')
        if not isinstance(receipt_id, str) or not re.fullmatch(r'[a-f0-9]{32}', receipt_id):
            raise ValueError('A durable canonical archive receipt ID is required.')
        try:
            receipt = self.client.receipt(receipt_id)
        except Exception as error:
            raise RetentionPending('Archive receipt unavailable; reconcile '+receipt_id+'.') from error
        if receipt.get('id') != receipt_id:
            raise ValueError('Archive receipt identity mismatch.')
        if receipt.get('action') != 'archive-research':
            raise ValueError('Completion requires an archive action receipt, not an unrelated save.')
        if not receipt.get('ok') or receipt.get('state') != 'completed':
            raise RetentionPending('Archive is not confirmed completed; reconcile '+receipt_id+'.')
        result = receipt.get('result', {})
        state, rows = self._state()
        self._check_agent(state, rows)
        memory = rows.get(('memory', result.get('id')))
        if result.get('kind') != 'memory' or not result.get('capture_status') or memory is None or memory.get('archived') or memory['version'] != result.get('version') or memory['data'] != result.get('data'):
            raise ValueError('Receipt does not match the current retained archive.')
        content = self.result_path.read_bytes()
        archived_text = memory['data'].get('content')
        # Archive text may use LF while Windows wrote CRLF. Artifact hashes above
        # still bind the exact bytes; do not normalize other content or whitespace.
        if len(content) > 100000 or not isinstance(archived_text, str) or archived_text.replace('\r\n', '\n') != content.decode('utf-8').replace('\r\n', '\n'):
            raise ValueError('Retained content differs from the checked result summary.')
        capture = memory['data'].get('capture', {})
        if capture.get('provenance', {}).get('chat_id') != self.identity['chat_id']:
            raise ValueError('Retained result does not carry this actual source chat identity.')
        wanted = {'project:'+self.project_id, *['skill:'+key for key in self.skill_versions]}
        memory_ref = 'memory:'+memory['id']
        if memory['data'].get('status') != 'accepted' or not wanted.issubset(memory['data'].get('refs', [])) or not state.get('memory_freshness', {}).get(memory['id'], {}).get('current'):
            raise ValueError('Retained result is stale or missing required links.')
        retrieved = self.client.knowledge(memory['id'])
        if retrieved.get('record') != memory:
            raise ValueError('Exact-ID accepted-memory retrieval does not match the retained result.')
        found = self.client.search(memory['id'])
        if not any(card.get('id') == memory['id'] and card.get('version') == memory['version'] for card in found.get('records', [])):
            raise ValueError('Retained memory is not discoverable through bounded accepted-memory search.')
        link_versions = {(r['kind'], r['id']): r['version'] for r in result.get('updated_links', [])}
        for key, previous in self.bound_records.items():
            current = rows.get(key)
            if current is None or current.get('archived') or semantic(current) != semantic(previous) or memory_ref not in current['data'].get('refs', []):
                raise ValueError('Project/skill semantics changed or reciprocal archive links are missing.')
            if current['version'] != previous['version'] and (current['version'] != previous['version']+1 or current['version'] != link_versions.get(key) or set(current['data'].get('refs', []))-set(previous['data'].get('refs', [])) != {memory_ref}):
                raise ValueError('Project/skill version drift is not attributable to this archive receipt.')
            if not set(previous['data'].get('refs', [])).issubset(current['data'].get('refs', [])):
                raise ValueError('Archive connection removed an existing project/skill link.')
        for key, previous in self.source_records.items():
            current = rows.get(key)
            if current is None or current.get('archived') or semantic(current) != semantic(previous) or key not in self.bound_records and current.get('version') != previous['version'] or key[0]=='memory' and not state.get('memory_freshness', {}).get(key[1], {}).get('current'):
                raise ValueError('Bound recall source drifted or is no longer current.')
        if digest(self._private_path(evidence_path)) != evidence_hash or digest(self.contract_path) != self.contract_sha256:
            raise ValueError('Evidence changed during completion checks.')
        if self.checker(deepcopy(evidence)).get('action') != 'complete':
            raise ValueError('Evidence no longer passes after remote reads.')
        self.gate_checks = {'declared_tool_contract': True, 'bounded_context': True, 'checked_work': True,
                            'agent_bound': self.agent_record is not None,
                            'agent_ref': 'agent:'+self.agent_id if self.agent_record is not None else None,
                            'agent_version': self.agent_version,
                            'agent_linked_skills': len(self.agent_skill_records),
                            'retained_memory': True, 'exact_id_retrieval': True, 'bounded_search': True,
                            'reciprocal_links': True, 'preserved_prior_links': True,
                            'sources': len(self.plan['sources']), 'recall_bindings': len(self.source_records), 'requirements': len(self.requirements),
                            'memory_ref': memory_ref, 'memory_version': memory['version'], 'receipt_id': receipt_id,
                            'scope': 'Executed participating-caller checks and evidence integrity; no semantic or global-interception certification.'}
        super().complete(summary)
