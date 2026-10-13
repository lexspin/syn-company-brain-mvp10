# Explicit routed-task completion gate

`app/routed_execution.py` adds `RoutedExecution`, a separate subclass of the low-level `NativeExecution` utility. Participating substantive tasks use it to bind the registered project, exact selected skill versions, private plan, executed checks, checked outputs and canonical archive receipt. `NativeExecution` remains compatible for small integrity utilities. This is an explicit Python execution contract; it does not intercept every host tool, read private reasoning, enforce a filesystem sandbox or establish universal routing.

Before the first callback or start event, the wrapper reads fresh canonical HTTP state, verifies its root and publication age, resolves the active registered project and selected skill versions, and applies the existing operating-policy task admission check. Off and Idle refuse new substantive tasks; Active admits them. Missing or malformed policy fails closed. Work already begun is still allowed to reconcile its outputs and retention. No new schedule or writer is created.

An explicitly selected role uses `agent_id` and `agent_version`, plus immutable plan field `agent_binding = {"id": "engineering-manager", "version": expected_version, "role": "manager", "skill_versions": {linked_skill_id: expected_skill_version}}`. The role classification matches the published agent's `level` or `role`; every configured `skills` entry and `skill:` reference must be bound at its current version. Unknown or archived agents, wrong versions or roles, missing linked skills, and agent Off/Idle overrides refuse before any callback or start event. Task support skills such as the harness can be outside those role links. Selected role and linked-skill semantics are reread before callbacks and completion. Reference-only version advances are allowed only for additive, current accepted memories whose backlinks point to that exact role or skill; other version drift, changed instructions/profile or removed links fail. This checks a participating caller's selected role; it does not change the actual host model or claim that every host agent is intercepted.

Existing calls without `agent_id` remain supported and report `gate_checks.agent_bound = false`. With an agent binding the report includes its reference, original expected version and configured linked-skill count. The low-level `NativeExecution(agent_id=...)` accepts validated public attribution only; published role admission belongs to `RoutedExecution`. Declaring a name alone is not evidence that the named worker ran.

The private plan lives under canonical `V2/runtime/`. Its 64 KiB snapshot remains immutable. It uses the existing harness evidence-contract fields: `outcome`, original `request_source`, absolute registered `project_root`, exact `skills` such as `skill:checker@1`, actual selected `tools`, budgets, `uncertain_effect`, source paths/hashes and requirement metadata. Additional routing fields are `acceptance_id`, `result_path` and `artifact_paths` (the exact permitted absolute output paths). Requirements declare unique IDs, descriptions and acyclic `depends_on` lists. At least one work check and final acceptance must be declared. Initial requirement statuses can be unknown; final evidence is a separate private contract.

Tool names must be nonempty, unique and bounded to 32 exact entries. At most 32 source files and 32 optional `source_bindings` (`kind:id` to exact version) can be declared; accepted memory bindings must still be fresh at admission and completion. Sources are explicit version/hash pointers, not copied raw chats or private reasoning. Requirements use the categories `recall`, `tool-use`, `work`, `acceptance` or `audit`; a work category and final acceptance category are mandatory. Categories name the review obligation, not proof that an arbitrary external tool executed.

Each `stage` must match a declared requirement and its exact dependency list and supply an actual check callback. Final `accept` must use the declared acceptance ID and depend on checked non-acceptance work. Literal `True` is required for checks. An acceptance callback alone cannot complete the task. All declared checks must execute before completion; stable task/stage identities retain the low-level protection against replay.

After work, supply a final evidence contract at `complete(evidence_path=..., receipt_id=...)`. Its routing identity, source hashes, selected tools, exact artifact destinations and acceptance criteria must match the immutable plan. Only measured counters, requirement statuses/evidence indexes and artifact hashes can change. The wrapper executes the existing trusted harness checker and rereads files after remote receipt/state checks. Every artifact must match an exact permitted path within the registered project, including the bounded UTF-8 retained result summary. The checker verifies integrity and declared acceptance; the task owner remains responsible for meaningful criteria and representative regression or human-flow checks.

Archive the result through the existing canonical archive helper outside this wrapper. Completion reads the supplied durable `archive-research` receipt by its exact ID, verifies completed success, and matches its saved memory to the fresh current publication. The retained content must equal the checked summary file, carry the actual source chat identity, remain current, link the project and every selected skill, and have reciprocal backlinks. Ordinary saves, pending receipts, foreign identities, stale content and changed skill/project semantics cannot pass. Archive-created backlinks can advance a selected record by exactly one version only when the receipt identifies that exact new version, the semantic fields are unchanged and the only added reference is this result memory. No existing links may be removed.

Completion also reads that accepted result through the existing exact-ID memory tool and finds its ID/version through bounded accepted-memory search. `gate_checks` exposes the passed mechanics for repeatable review: declared tool-contract shape, bounded context, executed work checks, durable memory save, exact-ID retrieval/searchability, reciprocal records and preservation of prior links. Declared names do not certify host-tool availability or a remote tool invocation. Bounded context means explicit source/file counts and current declared bindings; it does not imply that all private thought or recall happened here. Candidate records cannot pass as the accepted retained result. Context shaving means selecting these bounded current pointers and allowing transient context to fall away after consolidation; this helper never deletes files, wipes context or removes historical versions.

The personal Company Brain plugin is deliberately selected with `@Company Brain` in participating chats. Existing plugin/skill instructions must call this gate where applicable; merely loading a plugin does not instrument unrelated host tools. Audits, repair and self-improvement should inspect the retained checked result and the existing candidate-versus-accepted procedure gate, preserving predecessors and unresolved failures. No new plugin or watcher is installed here.

The wrapper makes GET requests and independent public telemetry calls only. It never archives, promotes, writes Brain state or replays a queue effect. `RetentionPending` means reconcile the original archive receipt; catch it inside the active context to retry the read-only completion check. Do not restart task callbacks or submit a replacement archive identity. If the context exits before completion, low-level telemetry records failure and a fresh start with that task identity is refused; use the preserved evidence and original receipt for a separately scoped reconciliation. Public labels are caller-selected and must exclude prompts, credentials and private reasoning.

Default reads use the bounded loopback HTTP client and the installed harness checker. Dependency injection is for trusted isolated tests, not JSON-controlled bypasses. `python -X utf8 -m unittest discover -s V2/evaluations -p test_routed_execution.py -v` executes callbacks, the actual checker and a real local HTTP fixture. Archive fixture effects are explicitly simulated outside the wrapper. Passing fixtures prove the gate mechanics; live release retention must supply its actual canonical receipt and current linked memory.

Minimal release integration, using an already prepared immutable plan and separately finalized evidence:

```python
from routed_execution import RoutedExecution

# project_id and selected_versions come from the fresh canonical registry;
# plan_path/evidence_path are private absolute V2/runtime paths. The plan's
# requirement IDs, categories, sources, result/artifact paths match these calls.
with RoutedExecution(canonical_root, task_id, 'Validate release integration',
                     project_id=project_id, skill_versions=selected_versions,
                     contract_path=plan_path) as run:
    checked = run.stage('release-check', 'Check release artifacts and behavior',
                        actual_release_checks, check=lambda result: result is True)
    run.accept('release-acceptance', 'Compare release outcome to requirements',
               lambda: checked is True, requires=('release-check',))
    # Existing archive helper performs the authorized queue action. Finalize
    # evidence counters/statuses/hashes without changing plan criteria/budgets.
    receipt_id = archive_using_existing_canonical_helper()
    run.complete(evidence_path=evidence_path, receipt_id=receipt_id)
    checked_gate = run.gate_checks
```

`actual_release_checks` must exercise the release behavior and counterexamples, not return a constant. The retained summary must already be a checked permitted artifact. `archive_using_existing_canonical_helper` denotes the existing actual archive action; it is not a helper supplied or automatically invoked by this module.

### Text retention on Windows
Completion compares archived summary text with CRLF normalized to LF on both sides. All other whitespace and content remain significant. Evidence checks continue to bind the exact artifact bytes by SHA-256; text normalization does not replace or relax those hashes.
