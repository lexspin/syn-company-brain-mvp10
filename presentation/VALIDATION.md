# MVP10 predecessor branch — historical validation

This document records the original branch checks before the independent public export. See [public release](../docs/PUBLIC-RELEASE.md) and [public checks](../PUBLIC-CHECKS.json) for this project.

Checked 13 October 2026 on the isolated presentation checkout.

## Fresh branch checks

| Check | Result | Scope |
|---|---|---|
| Reviewed source integration | **24/24 files matched** the retained review hashes. | Release-specific adaptations and the final control-room correction included. |
| Python regression suite | **495 tests passed**, 150.946 seconds. | `python -X utf8 -m unittest discover -s evaluations -v`; isolated fixtures, Python 3.14 on Windows, separately licensed local dashboard dependency. |
| Frontend tests | **11 scripts passed.** | All `evaluations/*.test.js` with Node 24.19.0. |
| Paper packaging | **4 PDFs parsed**: 19, 59, 7 and 6 pages. | Business plan, framework and the two latest annexes. |
| Paper navigation | **345 local links checked.** | 165 Markdown and 180 HTML/SVG links in the paper package. |
| Portable presentation | **Desktop and mobile checked.** | Homepage, guide, release notes and paper index; responsive layout and linked reading routes. |

The initial branch run exposed two old test-fixture assumptions: a Results helper absent from the isolated fixture and an operating-policy copy tied to a sibling checkout. The fixtures now supply the real workspace dependency and use this branch's module. Existing behavioral assertions were preserved. The complete Python and frontend suites then passed.

The licensed dashboard was available locally for these tests and remains excluded from Git. Test scratch and detailed logs stay in the ignored runtime directory. The checks exercised isolated fixtures; they did not activate schedules, call paid providers or restart the production backend.

## Inherited development evidence

The canonical 13 October control-room review recorded **580 Python tests**, seven frontend scripts and actual browser task/branch/source inspection. Its final source-preview correction received affected frontend and browser rechecks. The earlier adversarial review recorded 28 focused release checks. These are dated observations from their original environments; they are separate from this branch's 495-test run.

See the [control-room contract](../docs/CONTROL-ROOM.md), [commercial-readiness contract](../docs/COMMERCIAL-READINESS.md) and [paper collection](papers/README.md) for the relevant mechanisms, acceptance scope and development consequences.

## Reproduction and limits

Use the [inspection guide](AI-REVIEW.md#running-and-inspecting) for commands and dependencies. The static presentation runs with Python 3 alone. Full application operation requires a configured backend, the licensed dashboard and the owner's authorised integrations.

Source changes included in Git do not replace modules already imported by the running backend. The latest review records that backend activation and a navigation-publication correction remain pending. Complete native-worker containment, semantic usefulness, provider coverage and scheduled end-to-end operation require additional evidence.

The source manifest records reviewed local source-byte hashes before Git newline normalisation. The paper inventory records the selected publication copies. Integrity checks identify content; they do not establish the truth of every source claim or commercial readiness.
