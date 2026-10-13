# Base-layer implementation contract

## Method

Human outcome → current attributable evidence → bounded task → artifact → independent checks → owner acceptance → versioned reusable consequence. MAPS names Memory, Agent, Pulse and Screen; ARMS names Applications, Routines, Memory and Skills. Both are views over the same record and execution lifecycle.

## Stack

Python standard library, append-only hash-chained file transactions, SQLite WAL as a query projection, versioned JSON and Markdown, Codex CLI adapter, and the original V2 canvas/D3 views. A same-origin token protects mutation requests; the service binds only to loopback. Request bodies are bounded. IDs are validated and file reads are restricted to published records/artifacts and indexed source paths. Imported text never establishes permission.

HTTP reads backend-published data/*.json. Mutations append validated requests to runtime/queue; a separate backend worker records begun/completed receipts. An ambiguous begun command is not silently repeated after restart. Publication failure never repeats a successful effect. The backend can run without serving HTTP. Private store/ledger.jsonl is written and synced before SQLite commits; replay recovers a lost projection. See FILE-STORE.md for recovery boundaries.

## Interfaces

Read: `/api/state`, `/api/brain`, `/api/messages`, `/api/chat-traces`, `/api/command`, `/api/run`, `/api/history`, `/api/file`, `/api/artifact`, `/api/git`, `/api/routines`.

Commands: `/api/save` (expected-version write), `/api/chat`, `/api/archive-research`, `/api/index`, `/api/search`, `/api/start` (stable request key), `/api/cancel`, `/api/resume`, `/api/accept`, `/api/retain`, `/api/git-save`, `/api/git-push`, `/api/backup`, `/api/improvement-propose`, `/api/improvement-apply`.

Definitions have kind, ID, version, data, archive state and update time. References use `kind:id`; graph edges distinguish containment and dependency. Projects require an existing absolute directory, a scope and explicit related records. Chat binds the selected project version and passes bounded linked evidence; registration grants no arbitrary directory execution. Agent parents must be acyclic. A loop's selected skill must be attached to its agent and its capability must be in that agent's configured set. The current capability registry is deterministic host code; changing a prompt cannot create a new tool.

## Execution and correction

Native workflow requests now enforce queued → running → completed/failed transitions in the backend, with queued → failed allowed for preflight failures. Workflow bindings and established claims are immutable. Claim/completion require the current active workflow version; completion requires a result connected to that workflow. Terminal states cannot be replayed or have their evidence replaced. The dispatcher supplies actual checks; the backend validates lifecycle and evidence structure, not semantic truth.

An opt-in local workflow may use `completion: save-reviewed-candidate`. It must retrieve evidence, draft, validate and review. The final review must pass exact source-quotation checks before the draft is saved idempotently as candidate memory and the run completes. Candidates remain outside accepted-memory retrieval. A passing model review is neither factual proof nor owner acceptance. Default workflows retain their owner-review completion policy.

Native chat video/article/research intake uses `company-brain-research-intake`: source coverage, infrastructure comparison, application plan and verified library links. It is an implicitly selected native skill, not a dashboard fetch adapter or URL-watching service. Registered research workflow links describe cooperation; they do not prove source acquisition ran.

Each run stores the exact loop, agent, skill and accepted-memory snapshot. Each attempt is recorded before execution. Completed artifacts have hashes and source IDs. Mechanical validation checks artifact integrity, source freshness and citation presence, not factual entailment. Acceptance is an explicit owner action. Memory retention is a separate idempotent operation.

Chat begins with a deterministic Layer 1 lookup. An exact memory request reads a current saved record. An exact normalized question can reuse a source-linked answer only when its project, requested role, preceding conversation context, source versions and semantic configuration signatures still match. Identifiers, case, numbers, punctuation and code layout remain significant; relative-time questions are excluded. Replays persist real messages and a zero-model-call receipt. Other requests proceed through the hidden planner and one selected Layer 2 specialist. This is bounded exact-query reuse, not semantic matching.

After an eligible Layer 2 answer completes and releases its worker lock, the command worker retains it under standing owner authority. The answer must have exact source citations, no unresolved contract gaps, current source dependencies and unchanged relevant configuration. Retention preserves the exact answer, provenance and configuration bindings, adds reciprocal project/skill links and refreshes MAPS. Mechanical checks do not make model output established fact or owner-approved canon. Retention failure is a warning on a completed chat, never a reason to replay its model calls. Explicit and automatic archival share the original answer's canonical capture.

`app/model_profiles.py` defines Lightweight (GPT-6 Luna low), Routine (GPT-6.1 Sol medium), Thinking (GPT-6 Astra medium) and Innovation (GPT-6 Astra ultra). Calls pass explicit model/effort and default service tier, ignore user configuration and disable Fast mode. Invalid combinations fail before execution. Automatic Ultra routing requires a clear innovation opt-in; manual role and configured workflow choices remain explicit selections. Calls record requested settings without asserting provider-confirmed model metadata. The adapter continues to disable external apps, shell and concurrent delegation; profiles do not create those capabilities.

Corrections create new versions and preserve prior versions. In-flight and resumed work rejects changed dependencies. Source corrections or archival invalidate derived memory recursively. Answer reuse also checks relevant role/skill/model/project semantics and preceding conversation; reciprocal-link bookkeeping does not invalidate the answer that added those links. Archiving removes a record from current retrieval without deleting history. Git stores exported definition/memory versions; private conversations and operational history remain local.

The private history inventory dated 10 October 2026 covers 3,340 messages and 1,171 final-answer pointers from 70 available local root session files, plus 54 human messages and 39 indexed visible assistant references from 13 partial cloud conversations. Combined totals are 3,394 messages and 1,210 output references. Cloud snapshots preserve truncation and partial-coverage flags; they are not complete exports or inferred accepted final artifacts. Raw history stays outside Git and file-map publication. Bounded, dated excerpts enter model context with source IDs/hashes and no authority to execute historical requests.

## Staged expansion

Add each external capability through a concrete adapter, input/output contract, authority boundary and failure/recovery tests. Introduce scheduled triggers only with an explicitly requested routine and durable occurrence identity. Introduce app-server thread lifecycle or parallel workers only after preserving the same receipts, source-version checks and cancellation semantics. Add semantic retrieval only against a measured lexical baseline. Avoid promising unattended operation while this machine is asleep.

## Human interface and growth

Overview, Chat, Team, Playbooks, Knowledge, Workflows, Results, Improvements, Workspace and Map expose human tasks. Internals live in optional audit/advanced panels. Chat uses the Layer 1 known-answer path and, when needed, a two-stage planner/specialist pipeline documented in CHAT-PIPELINE.md. Organizational hierarchy describes scope; multiple roles execute only within an explicitly configured workflow.

Improvement proposals bind the current skill version. They remain candidate knowledge until the owner applies a reviewed replacement. The previous procedure survives as an immutable version. Measured skill quality and production tool readiness require separate evidence.
