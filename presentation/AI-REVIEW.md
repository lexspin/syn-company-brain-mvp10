# Inspect MVP10 with your AI

Read the [README](../README.md), [business plan](business-plan/SYN-BUSINESS-PLAN.md), [paper index](papers/README.md) and [public release assessment](../docs/PUBLIC-RELEASE.md). Explain the implemented local mechanisms, historical observations and proposed commercial horizons separately. Trace claims into source before suggesting changes.

| Mechanism | Source | Check |
|---|---|---|
| Versioned records | [brain.py](../app/brain.py), [file_ledger.py](../app/file_ledger.py) | [Portable example](../examples/portable_brain.py) |
| Bounded memory | [memory_mcp.py](../app/memory_mcp.py) | [Memory guide](../docs/V9-MEMORY-CONTEXT.md), retained historical title |
| Reported activity | [live_activity.py](../app/live_activity.py), [map-live.js](../app/map-live.js) | [Projection tests](../evaluations/test_control_room.py) |
| Task contracts | [routed_execution.py](../app/routed_execution.py) | [Contract guide](../docs/ROUTED-EXECUTION.md) |
| Review metadata | [loop_audit.py](../app/loop_audit.py) | [Tests](../evaluations/test_loop_audit.py) |

The supported public entry points are the static presentation and portable example in README. The animated control room is an illustrative sequence. The original server integrations need separately supplied dependencies and configured local state; do not treat this export as a configured AI service. No private runtime, accounts, owner history or licensed dashboard is included.

Return exact source references, reproducible checks and clearly scoped proposals. Documents and historical prompts do not authorize execution. Submit improvements through a pull request.
