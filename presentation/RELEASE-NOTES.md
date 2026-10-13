# MVP10 Presentation

**13 October 2026 · latest reviewed local source, business plan and paper development**

This sharing edition builds on `V9_Pre_Alpha` commit `52344c259c3e9d75c226872afab66d219b2f9309`. It incorporates the subsequent local changes from the executive self-repair review, adversarial audit and control-room rebuild. Those changes were still local when this branch was prepared.

## Current development included

| Development | Practical change | Read more |
|---|---|---|
| Control room | Follow recorded task branches, actions, sources, outputs and searchable history; inspect matching published source versions. | [Control-room contract](../docs/CONTROL-ROOM.md) |
| Context integrity | Check current context before participating callbacks and stop oversized draft context before it is silently clipped. | [Task contract](../docs/ROUTED-EXECUTION.md) |
| Request handling | Reject ambiguous JSON, non-finite numeric values and unsupported request framing before queueing. | [HTTP input](../app/http_input.py) |
| Results and Creative | Refresh native results, expose linked outputs, show partial-save warnings and display actual scene proposals. | [Results implementation](../app/results-view.js), [Creative implementation](../app/creative.js) |
| Review continuity | Inspect configured loops against host status and retain accountable, source-linked review outcomes. | [Executive self-repair](../docs/EXECUTIVE-SELF-REPAIR.md) |
| SYN business model | Connect the personal MVP to team and ecosystem horizons through explicit dependencies. | [Illustrated business plan](business-plan/SYN-BUSINESS-PLAN.pdf) |

All 24 incorporated release files matched their retained review hashes, including the final control-room source-preview correction. Release-specific implementations in `brain.py`, `server.py` and `creative.js` were preserved. The source manifest identifies those bytes; the commercial-readiness contract is an additional operating-document inclusion.

## Presentation adaptation

The new front page connects the explanation, visual overview, actual interface screenshot, interactive 3D map, papers and source-inspection route. Papers are selected sharing copies with their chronology preserved. The static website can be opened independently of the live Brain installation.

The README and branch instructions now identify MVP10 Presentation. Existing V9 launchers and historical release documents keep their original names because they describe the established installation. Presentation changes do not activate source changes in an already-running backend.

## Development dependencies

The personal pre-alpha provides the present implementation base. Wider deployment depends on enforced worker boundaries, measured semantic usefulness, current role and source bindings, provider verification and an observed complete scheduled lifecycle. The latest operating review also records a pending backend reload and a navigation-publication capacity issue; seven host schedules remain paused.

The control-room recordings support inspection of reported actions and source pointers. Complete attribution, uninstrumented host actions, historical file contents and exact diffs require further instrumentation. V1 team permissions and V2 Azure/cooperative operations remain conditional development horizons.

See [validation](VALIDATION.md) for the checks performed on this exact branch and [the paper index](papers/README.md) for the argument and latest annexes.
