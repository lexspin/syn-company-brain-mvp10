# V9 memory, context and maintenance

Implemented: versioned records, source-linked retention, bounded recall, selected procedure loading and checked artifact destinations. These mechanisms reduce the context supplied to participating work. They do not automatically summarize every document or compress every host chat.

## What is retained and retrieved

`app/lifecycle.py recall` reads published state without writing. It returns at most **six current memory excerpts**, each at most **1,200 characters**, with ID, version, source and a truncation flag; at most **four historical excerpts**; and at most **twelve linked project skill cards**. Query matching selects relevant material before these limits. Stale memory is excluded; publication freshness remains visible and current records must be checked before mutation.

`app/history_recall.py` defaults to four excerpts of 1,200 characters, permits 1–8 excerpts of 100–3,000 characters, and preserves original dates, scope, source locations and record hashes. It selects a substring around a lexical match. `verify` checks active-index eligibility and retained-record integrity; cloud snapshots have additional exact-source checks. An explicitly referenced assistant final answer can be read separately, capped at 100,000 characters and verified against its retained source pointer/hash.

This is **selection and truncation**, not semantic compression. The prefix of a memory may omit a later qualification; retrieve the exact source when an excerpt is insufficient. Original documents remain at their source locations. History intake retains eligible root-chat human text with provenance and credential redaction, plus assistant final-answer pointers; it excludes tool/media bodies and injected/programmatic context. It does not fetch all cloud history. Historical instructions are evidence of their original scope, not new permission.

## Planner and interaction context

Dashboard chat selects up to twelve recent conversation messages. Serialized history is character-sliced to 18,000 characters for planning and 20,000 for the specialist. Compact role cards omit procedure bodies; the selected specialist receives its exact role and selected skill instructions. Accepted evidence is serialized under a default 24,000-character content budget with identities retained and truncated content marked. These are character budgets, not token guarantees or meaning-preserving summaries.

The native discovery helper separately caps candidate cards at eight and linked cards at six. Native-chat continuity is driven by loaded instructions and explicit recall. It does not force a reset, rewrite or automatic semantic summary of every conversation. Manually authored bounded memories still need accurate sources and review; shortening text alone does not verify its claims.

## Path and maintenance controls

`RoutedExecution` requires canonical V2, a current registered project root, a private contract under canonical runtime, and 1–64 declared absolute artifact paths inside that project root. Completion rejects an altered destination, undeclared artifact set or evidence outside the registered root, and checks bound source versions. These gates govern participating task admission and evidence acceptance. Python callbacks and arbitrary host tools are not filesystem-sandboxed by this wrapper; preventing every possible write remains outside its capability. The OS/product separation is also a loaded workspace instruction.

Lifecycle cleanup defaults to a dry run. Apply only accepts at most 100 explicitly listed eligible files under the owning `runtime/scratch/<work_id>` with unchanged hashes, retained replacements and passed validation evidence outside disposable scratch. Traversal, symlinks/reparse points, changed inputs, stale/busy state, uncertain commands and conflicting scratch ownership are rejected. Actual deletion events are retained. This is controlled scratch maintenance, not automatic deletion, document consolidation or history erasure.

## Existing regression evidence

Relevant tests, included in the release suite rather than newly claimed executions here:

- `test_lifecycle.py`: `test_recall_prefers_selected_project_memory_and_excludes_stale_sources`, `test_large_project_library_does_not_crowd_out_query_relevant_source`, `test_only_owned_scratch_is_eligible_and_path_traversal_rejected`, `test_changed_scratch_or_replacement_is_retained`, `test_pending_command_and_owned_scratch_lease_prevent_cleanup`.
- `test_history.py`: `test_import_keeps_only_root_human_text_and_exact_final_output_pointer`, `test_idempotent_rescan_does_not_rewrite_message_records`, `test_domains_keep_lore_and_linkedin_voice_context_separate`, `test_changed_immutable_record_is_rejected`.
- `test_routing_context.py`: `test_compact_cards_exclude_procedure_bodies`, `test_plan_then_exact_selected_context_and_tool_scope`.
- `test_brain.py`: `test_evidence_budget_preserves_prioritized_source_identity`, `test_source_correction_invalidates_transitive_derived_memory`, `test_chat_does_not_publish_stale_context`.
- `test_routed_execution.py`: `test_final_evidence_cannot_weaken_requirements_change_sources_or_escape_paths`, `test_bound_accepted_recall_sources_checked_at_start_and_completion`.

The inspected implementation supports retained originals plus linked bounded recall and checked maintenance. Universal automatic document/chat compression, guaranteed retention of every interaction and interception of all host writes are not implemented claims. See V9 validation for final suite results.
