# Live control room — observed work, 13 October 2026

## Human purpose

Follow a task from its reported actions, source access, changes, outputs and branch handoffs. The central map and worker markers are supported by an accessible branch tree, a timeline, a source inspector and searchable recordings. These controls inspect evidence; they do not execute or replay work. Private chain-of-thought, unreported tool calls and guessed activity are excluded.

## Implemented

- Central map with fitted observed areas and directed reported paths; worker diamonds use the same coordinates for rendering and selection. Dotted parent links represent reported task hierarchy, not inferred execution causality.
- Selected-task histories take priority within the existing eight-request polling budget. A queued request explicitly says execution has not started; it no longer pretends its missing native recording is loading.
- Branch tree selection narrows recorded action lanes. The inspector names action, source pointer/version, change/output metadata and task/event identifiers. Unknown worker/model identity is explicit.
- Source-object inspection reads a matching published historical record when a numeric version was recorded. Otherwise it labels current published content. Version absence, failed access and clipped 6,000-character previews remain explicit. Selection tokens prevent late replies or old previews appearing under another event.
- History is searchable and initially limited to twelve rows, with a working show-more control. Original history remains intact.
- Artifact strip selects the originating recorded action. Images render only for explicit local creative asset paths; remote image references are not fetched automatically. The inspected real tasks contain document/code outputs, so no photograph is invented.
- Existing pause, follow, multi-branch selection, reduced-motion handling, static map layouts, full map and event evidence are retained. Map controls remain below the recording area.
- Malformed URL pointers are skipped without erasing valid sibling source entries. This Python projection repair is tested but imported gateway activation awaits a permitted reload.

## Evidence and acceptance

Full Python suite: 580 tests in 221.735 seconds, passed. Seven Node scripts passed. Real browser flow: selected `MVP08 timeline interaction acceptance`, selected its `Verify timeline evidence` child, selected the source-read action and observed its source/report pointers. Pause/resume worked. A live current procedure source was opened at recorded version 10. Fresh source inspection exposed escaped JSON and a CSS specificity conflict; both were corrected. Synthetic fixtures also check selected-history priority, unsafe source links, late-response isolation, preview clearing and local-only image rendering.

Independent Astra review reproduced history starvation and malformed URL failure. Its browser surface was unavailable; parent browser checks are separately recorded. Investigator acceptance is partial: the tested recordings reconstruct task actions, branches, source pointers and outcomes, but not omitted identities, uninstrumented tool calls, historical bytes or exact code diffs. The UI does not claim complete surveillance of the native host. A source hash is integrity evidence, not proof of truth.

## Research and design choices

Primary sources reviewed 13 October 2026:

- [Langfuse trace best practices](https://langfuse.com/docs/observability/best-practices): use meaningful stable action names and a trace tree tied to a unit of work.
- [Phoenix tracing concepts](https://arize.com/docs/phoenix/learn/tracing): preserve explicit parent/child relationships and distinguish individual operations from the whole request.

Applied those structural patterns to the existing pinned vis-timeline 8.5.4 and LINKS canvas. No third-party product code or brand design was copied, and no additional UI dependency was installed. A map-first HUD follows the owner's requested game/control-room direction.

## Operations, continuity and rollback

Canonical OS remains V2; release static assets are synchronized in MVP03_AI_OS. The gateway reads JavaScript/CSS files dynamically. Backend restart was previously rejected by automatic approval; this work does not bypass that block. Seven host schedules remain paused. Existing review loops consume retained results on their current cadence.

Evidence and predecessors: `runtime/scratch/control-room-20261013`. Restore only files whose current repair hash still matches the saved manifest; preserve later work and the release's own predecessor. No database migration, public write endpoint or new timer was introduced. Retain known missing coverage for the next worker-boundary/instrumentation milestone rather than relabelling it complete.
