# ReviewGuard AI submission documentation

Start with **ReviewGuardAI-PROJECT_SUBMISSION.pdf**, the 10-page project report containing
project details and four rendered diagrams. The report distinguishes implemented
and offline-validated behavior from the remaining live and acceptance checks.

## Files

- `ReviewGuardAI-PROJECT_SUBMISSION.pdf`: printable submission report with selectable text and vector diagrams.
- `PROJECT_SUBMISSION.html`: standalone browser-readable report with inline SVG diagrams and no external scripts.
- `PROJECT_SUBMISSION.md`: editable report with Mermaid source blocks.
- `diagrams/architecture.mmd`: system architecture.
- `diagrams/workflow.mmd`: parallel review and aggregation workflow.
- `diagrams/sequence.mmd`: upload, explicit review, filtering, and download sequence.
- `diagrams/data-model.mmd`: findings, agent results, aggregation, and report relationships.
- Matching `.svg` and `.png` files: rendered versions for presentations or other documents.

Editable online copy:
[ReviewGuard AI Project Submission](../evals/results/validation-2026-11-13.md).

## Regeneration

From `reviewguard-ai`, with Google Chrome installed:

```powershell
..\.venv\Scripts\python.exe -m pip install playwright
npm install --prefix .pytest_cache/submission-tools mermaid marked
..\.venv\Scripts\python.exe scripts/export_submission.py
```

The renderer parses all four embedded Mermaid blocks, renders them locally,
and regenerates HTML, PDF, PNG, and SVG outputs. It blocks browser HTTP/HTTPS
requests during rendering. npm downloads rendering libraries only; project
content is not sent to a rendering service. These packages are documentation
tooling, not application runtime dependencies.

Edit the Mermaid blocks in `PROJECT_SUBMISSION.md` and keep the matching `.mmd`
files synchronized. Regeneration reads the report's embedded Mermaid blocks.
The online Page is an independent editable copy and must be updated separately
if submission content changes.
