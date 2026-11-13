# Offline validation — November 13, 2026

The core application passed its offline suite and real Chrome browser checks.
One browser-discovered widget-state bug was fixed. A full post-fix live quality
benchmark remains pending because the user chose to keep validation offline.
No Fireworks, LangSmith, or Langfuse requests were made for this validation.

## Verified results

| Check | Result |
| --- | --- |
| Full pytest suite after the application fix | 534 passed, 1 dependency deprecation warning |
| Python compilation | Passed for app, library, tests, samples, browser harness |
| Installed dependency consistency (`pip check`) | No broken requirements |
| Reviewed evaluation dataset | 30 reviewed cases, zero pending annotations; validation gate passed |
| Initial browser state | Review and download disabled before upload |
| Upload behavior | Invalid UTF-8 rejected, empty file accepted, preview does not invoke review |
| Explicit review submission | One synthetic execution per click; completed review cannot be resubmitted without re-arming |
| Severity filter | Keyboard selection of Critical shows no-match notice for saved High/Low findings |
| Browser download | Actual Chrome download named `reviewguard-report.json`; parsed and validated as `ReviewReport` |
| Full export under filter | Download retained both High and Low findings despite the Critical filter; no top-level source field |
| Re-arming | Clears results and disables download without another execution |
| Upload replacement | Clears old results and enables a new explicit review |
| Partial and empty results | Failure warning and retained findings; distinct successful-zero-findings notice |
| Execution error | Sanitized message, download disabled, private exception text absent |
| Post-review uploader | Enabled after completed/partial/error review |
| Responsive overflow | No document-level horizontal overflow at 390, 768, and 1440 pixels |
| Browser JavaScript errors | None observed |
| Keyboard activation | Review via Enter, finding expansion via Enter, severity selection via arrow/Enter, and JSON download via Enter passed |
| Visual inspection | Desktop empty state and desktop/phone results and expanded findings inspected; no clipped content or overlapping controls observed in these screenshots |
| Accessibility structure | Saved Chrome accessibility snapshot includes section headings, status message, named severity combobox, download button, and expanded finding content |

The browser harness made exactly four synthetic reviews. It replaced only the
review service, exercised the production dashboard, blocked synchronous and
asynchronous HTTPX calls, and used a temporary localhost Streamlit server.
Downloaded bytes were read from Chrome's download artifact, not substituted
from Streamlit's test API. No application credentials were loaded by the fixture.

## Bug found and fixed

The uploader was rendered while `review_running` was true. After the synchronous
review completed, the flag was cleared but that already-rendered widget remained
disabled until another interaction reran the app. The application now performs
one rerun after execution ends. The pending flag has already been cleared, so
the rerun cannot repeat inference. The browser harness verifies upload recovery
and its execution counter checks for unintended submissions.

## Reproduce

From `reviewguard-ai`, using the existing workspace environment:

```powershell
..\.venv\Scripts\python.exe -m pytest -q --tb=short
..\.venv\Scripts\python.exe -m compileall -q app.py reviewguard tests samples scripts/verify_browser.py
..\.venv\Scripts\python.exe -m pip check
..\.venv\Scripts\python.exe -m reviewguard.evals.cli validate --dataset evals/reviewed_golden_v1.jsonl
..\.venv\Scripts\python.exe -m pip install playwright
..\.venv\Scripts\python.exe scripts/verify_browser.py
..\.venv\Scripts\python.exe scripts/verify_browser.py --artifacts .pytest_cache/visual-validation
git diff --check
```

Environment: Windows, Python 3.13.7, Streamlit 1.66.1, Playwright 1.65.1,
installed Google Chrome in headless mode. Playwright is optional validation
tooling, not an application dependency. Initial sandboxed pytest runs produced
11 temporary-directory permission errors; the full suite passed when run with
the necessary filesystem access. Those setup errors were not application failures.
The remaining warning concerns a deprecated import inside LangSmith.

The optional artifact command saves five screenshots (desktop empty state,
desktop/phone results, desktop/phone expanded findings) and
`results-accessibility.txt`. Artifacts are local, ignored by Git, and contain only
synthetic fixtures. The screenshot review is an assistant visual inspection;
it does not replace user acceptance testing. Focus-and-Enter checks verify those
controls can be operated from the keyboard, but do not establish that every
control can be reached in a complete Tab-only journey.

## Still pending

- Full three-agent quality evaluation after the coverage fix. The earlier
  [baseline](baseline-2026-11-11.md) remains the only full-workflow quality score.
  The [coverage-only verification](coverage-validation-fix-2026-11-11.md) accepted
  30/30 responses but did not measure semantic recommendation quality.
- Live provider execution through the browser. Browser results here use fixtures;
  they establish dashboard behavior, not provider availability or review accuracy.
- Human acceptance, actual screen-reader testing, complete Tab-order testing,
  and other browser engines. Screenshot review, an accessibility snapshot, and
  selected keyboard checks do not constitute a comprehensive accessibility audit.

The live evaluation was not run after automatic approval review rejected the
paid external requests and the user explicitly selected offline validation.
No paid authorization was assumed. GitHub/PR integration and deployment were
outside this validation scope.
