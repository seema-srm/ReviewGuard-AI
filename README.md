# ReviewGuard AI

Multi-Agent Code Review Platform with a Streamlit dashboard and three concurrent
AI reviewers: code quality, security, and test recommendations.

## Current status

Submission documentation is available in [docs](reviewguard-ai/docs/README.md), including a
[PDF report](reviewguard-ai/docs/ReviewGuardAI-PROJECT_SUBMISSION.pdf), an editable report, and four Mermaid
architecture, workflow, sequence, and data-model diagrams.

The application supports one Python upload, explicit Fireworks review execution,
prioritized findings, per-agent statuses, severity filters, and full JSON report
downloads. Uploads are validated in memory and never executed. Results persist
within the current browser session. LangSmith and Langfuse tracing are opt-in.
GitHub/pull-request integration is deferred.

Offline verification on November 13, 2026 passed all 534 tests. The latest saved
coverage-only verification accepted 30/30 responses; a new full three-agent
post-fix quality benchmark is still pending. The earlier baseline's quality
scores remain the only full-workflow measurements. See
[validation status](reviewguard-ai/evals/results/validation-2026-11-13.md) for checks and limits.

The phase sections below preserve implementation history. Statements about
placeholders, disconnected reviewers, or deferred filters/downloads describe
those earlier checkpoints, not the current application.

## Setup (Windows PowerShell)

Use Python 3.11 or 3.12. From the workspace folder:

```powershell
cd reviewguard-ai
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

For Python 3.11, replace `-3.12` with `-3.11`. Calling the virtual environment's
interpreter directly avoids PowerShell activation policy changes.
Open the local URL printed by Streamlit (normally http://localhost:8501).
No credentials are required for uploads, previews, or offline tests. Actual
reviews require `FIREWORKS_API_KEY`, `FIREWORKS_MODEL`, and `FIREWORKS_BASE_URL`
in `reviewguard-ai/.env` or the process environment. Copy `.env.example` and
fill in your own values; never commit credentials. Clicking Review Code sends
source to Fireworks and may incur charges. Uploading alone sends no request.

## Tests and compilation

From `reviewguard-ai`, using the same environment:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q app.py reviewguard tests samples
```

Tests use in-memory uploads and Streamlit AppTest without a browser, network
access, or API keys. UI tests substitute an in-memory uploader result so they
can exercise previews, validation errors, review execution, reports, and downloads.

Optional real-browser verification uses installed Google Chrome and Playwright:

```powershell
.\.venv\Scripts\python.exe -m pip install playwright
.\.venv\Scripts\python.exe scripts\verify_browser.py
.\.venv\Scripts\python.exe scripts\verify_browser.py --artifacts .pytest_cache/visual-validation
```

Use `..\.venv\Scripts\python.exe` instead if using the existing workspace-level
environment. The browser harness launches an isolated localhost server, replaces
the review service with synthetic reports, and blocks HTTPX requests. It makes
no model calls and does not load the application's credentials. Playwright is
optional validation tooling and is not required to run the application.
The artifact option saves synthetic desktop/phone screenshots and a Chrome
accessibility snapshot. The harness also checks keyboard activation for review,
finding expansion, severity selection, and download. Actual screen-reader and
human acceptance testing remain separate checks.

## Original Phase 1 project structure (historical)

```text
reviewguard-ai/
├── app.py                      # Streamlit upload and source preview UI
├── reviewguard/
│   ├── __init__.py
│   ├── config.py               # Upload limit and Phase 2 message
│   └── file_utils.py           # In-memory validation and line counting
├── samples/
│   ├── clean_example.py        # Mean calculation with input validation
│   └── buggy_example.py        # Intentional even/odd logic bug
├── tests/
│   ├── test_file_utils.py
│   └── test_app_smoke.py
├── .gitignore
├── .env.example                # Comments and placeholders only
├── requirements.txt
└── README.md
```

## Phase 1 scope (historical)

Upload one `.py` file, validate its extension (case-insensitive), size, and UTF-8
encoding, and display its filename, byte size, line count, and highlighted source.
The 1 MB limit means 1 MiB (1,048,576 bytes); files exactly at the limit are accepted.
Empty files are accepted with a clear notice and zero lines. A trailing newline
does not add an extra line; blank lines count.

The Review Code button displays: "AI review agents will be available in Phase 2."
There are no findings, LLM calls, agents, LangGraph workflows, or GitHub API calls.
Validation checks upload format only; it does not check Python syntax or safety.
Uploaded code is never executed or written to disk by the application. Sample files
define functions only and do not run them automatically.

Future phases may introduce quality, security, and test coverage agents,
parallel orchestration, pull request integration, and prioritized reports.

## Phase 2, Step 2D: opt-in Fireworks connection diagnostic

The Phase 1 UI is unchanged. No review agents have been implemented.
Install the updated requirements into your existing environment. Configure
`FIREWORKS_API_KEY`, `FIREWORKS_MODEL`, and `FIREWORKS_BASE_URL` in the application
directory's `.env` file. Use the plain base URL `https://api.fireworks.ai/inference/v1`,
without Markdown brackets. Existing process environment variables take precedence.
The key is excluded from settings representations and diagnostic output.

From the workspace folder, using the existing environment:

```powershell
.\.venv\Scripts\python.exe reviewguard-ai\scripts\test_fireworks_connection.py
```

This explicit command makes at most two small paid requests: a connection prompt
and a JSON-mode compatibility prompt. Each has a 256-token output limit and a
30-second SDK timeout. Automatic retries are disabled; no model changes occur.
Loading configuration does not depend on your terminal's working directory.
The script returns a nonzero exit code for a failure, incomplete output, or an
unexpected response. Errors use sanitized categories, never raw provider bodies.
The JSON check requests `response_format={"type":"json_object"}` and validates
the result against exactly `{"status":"ok"}`. This tests JSON mode, not strict
JSON Schema support. If unsupported, a future fallback should request plain JSON,
parse it with `json.loads`, validate the expected structure, and reject failures
without automatic paid retries. This diagnostic does not execute that fallback.

Pytest uses mocks only for the Fireworks client; it never calls the live API.

## Phase 2, Step 4: code-quality reviewer

`reviewguard.agents.code_quality.CodeQualityReviewer().review(filename, source)`
accepts a filename and already validated Python source, returning the shared
`AgentReviewResult`. Calling `review` with nonblank source sends one paid Fireworks
request; importing or constructing the reviewer does not. Empty or whitespace-only
source returns a successful empty result without a request. The Streamlit UI does
not invoke this reviewer yet.

The reviewer requests JSON mode, validates the response with Pydantic, and checks
every filename, line reference, and exact evidence snippet against the source.
One invalid finding rejects the entire response with failed status and no findings.
Provider and parsing errors are sanitized. Requests use a 30-second timeout,
2,048 output tokens, and zero automatic retries. Truncated output fails without
retry. Injecting a client and model supports fully offline testing.

Source is sent as untrusted data in a separate user message. It is never executed
or saved by the agent. Prompt instructions and grounding checks reduce risk but
cannot guarantee prompt-injection resistance or the technical correctness or
completeness of a review. Source size/context-limit handling remains the caller's
responsibility. SDK log records are filtered only in this agent's execution
context; application logs and other review threads are unaffected. Logger levels,
handlers and global disable state are unchanged. Automated agent tests
use mocked responses; live agent review quality has not been verified.

## Phase 2, Step 5: security reviewer

`reviewguard.agents.security.SecurityReviewer().review(filename, source)` returns
the shared `AgentReviewResult` for already validated Python source. Calling it
with nonblank source sends at most one paid request, with the configured model,
JSON mode, a 30-second timeout, 2,048 output tokens, and no automatic retries.
Empty input returns successful empty findings without calling the provider.
It is not connected to the Streamlit UI. Tests inject mocked clients and models.

The security prompt covers SQL/command injection, hardcoded secrets, unsafe
deserialization, path traversal, insecure subprocess usage, and dangerous input
handling. It asks for realistic exploitability/impact, explicit uncertainty,
remediation, and recognition of safe parameterized SQL and subprocess patterns.
Evidence and filenames/lines are checked against the source; one invalid finding
fails the entire review without fabricated or partially accepted findings.
Secret-related evidence should cite a variable name rather than a secret literal.
Structured results are sensitive review data and must not be logged by callers.

This reviewer does not change logging configuration. If SDK or transport DEBUG
logging is enabled, it returns a sanitized failure before sending source. Keep
that logging disabled throughout reviews; concurrent external logging changes
are outside the reviewer's control. SDK/provider errors are never returned raw.
The agent never executes or saves uploaded code.

Grounding checks establish that evidence exists, not that a vulnerability is
exploitable. Detection, severity, secret minimization, and recognition of safe
patterns still depend on the model; the prompt is not a deterministic scanner
or a guarantee against prompt injection. Automated tests use prescribed mocked
responses, not live security reviews. Source context limits remain the caller's
responsibility. Agent 1 and the shared schemas are unchanged.

## Phase 2, Step 6: test-coverage reviewer

`reviewguard.agents.test_coverage.TestCoverageReviewer().review(filename, source)`
returns static test recommendations in the shared `AgentReviewResult`. Importing
or constructing it does not call Fireworks; reviewing nonblank source makes at
most one paid JSON-mode request, with a 30-second timeout, 4,096 output tokens,
and zero automatic retries. No code or tests are executed and no uploads are saved.
The Streamlit UI and Agents 1 and 2 are unchanged.

Optional keyword arguments are:

- `existing_tests={"test_example.py": "<test source>"}`: test sources supplied as
  in-memory strings, not paths to read. The prompt asks the model to avoid
  scenarios already covered by these tests.
- `measured_coverage={"filename": "example.py", "missing_lines": [2, 3]}`:
  caller-supplied, 1-based line measurements for this exact file. Unknown keys,
  invalid lines, or a different filename are rejected. No coverage is computed.

Findings use `recommended_test`, `potential_gap` (only with supplied tests), or
`verified_coverage_gap` (only for cited lines supported by supplied measurements).
The last category means consistent with caller-supplied measurements, not
independently verified by this agent. Suggestions must be nonempty and should
name tests, inputs and expected outcomes. All findings reference the application
source and pass exact evidence and line checks. A single invalid finding fails
the review with no findings. Errors are sanitized.

The reviewer rejects numeric coverage claims rather than reporting percentages.
It rejects common missing-test claims when no tests are supplied, and its prompt
requires recommendations instead. These text checks are conservative guards,
not a proof that arbitrary model prose contains no unsupported claims. Deduplication
against supplied tests, expected behavior, and recommendation quality remain
model-dependent; mocked tests do not establish live accuracy. Input source and
measurements are untrusted data, and prompt separation does not guarantee injection
resistance. Context limits remain the caller's responsibility. SDK/transport
DEBUG logging causes a safe failure without changing logging configuration.

### Step 6C: bounded output and completion diagnostics

Agent 3 defaults to `max_output_tokens=4096`, configurable on its constructor;
Agents 1 and 2 retain their 2,048-token limits. The shorter prompt requests no
more than five high-value findings, with exactly one suggested-test entry per
finding (at most five entries total). Related inputs may share one parameterized
scenario. The reviewer rejects an
over-limit response instead of dropping findings or repairing JSON. The 30-second
timeout, JSON mode, exact grounding, and zero automatic retries remain in place.

After each review, `reviewer.last_completion_metadata` contains only an immutable
allowlist: `response_received`, `finish_reason`, `prompt_tokens`,
`completion_tokens`, `total_tokens`, and `reasoning_tokens`. Missing values are
`None`; unknown finish reasons become `unknown`; nonnumeric/negative counts are
discarded. Metadata is reset before every call, including empty-input and failed
calls, and is not logged. Use a separate reviewer instance per concurrent review.
No raw response text, reasoning trace, source, or credentials are retained there.

`length` produces an explicit output-limit failure. Missing/non-normal finish
reasons, empty output, invalid JSON, invalid schemas, and invalid source evidence
all fail closed with distinct sanitized errors and no fabricated findings.

### Coverage validation diagnostics and scenario wording

`reviewer.last_validation_diagnostics` is an immutable, per-call record containing
only a fixed validation stage, an optional zero-based finding index, and a fixed
source-error code. It distinguishes schema, count, category, unsupported coverage
claim, unsupported missing-test claim, measured-gap, and source-grounding failures.
Source-error codes distinguish filename/range problems, evidence absent from the
source, and evidence present outside the cited range. No rejected response text,
source, credentials, or arbitrary exception messages are retained in this record.
Both completion and validation diagnostics reset before each call.

Coverage claim checks require coverage-related wording rather than rejecting
every percentage. Application inputs such as a 0% discount, or scenarios involving
missing files/keys, are allowed. Numeric coverage claims and common assertions of
missing tests without supplied tests still fail closed. These text heuristics
remain conservative checks, not a semantic proof against every possible claim.

The prompt explicitly separates recommendations from absence claims and receives
numbered application lines alongside the original unmodified source. Evidence
is still checked against that original source and cited range with exact matching.
No evidence is rewritten, no findings are dropped to repair a result, and the
4,096-token budget, 30-second request timeout, one-suggestion/five-finding limits,
and zero automatic inference retries are unchanged.

Replay coverage alone against the reviewed dataset using:

```powershell
..\.venv\Scripts\python.exe scripts\check_coverage_validation.py `
  --dataset evals\reviewed_golden_v1.jsonl `
  --baseline evals\results\baseline-2026-11-11.jsonl `
  --output evals\results\coverage-unique-name.jsonl --confirm-paid-runs
```

Each selected case makes at most one paid request. Add `--failed-only` to select
only baseline cases with a failed coverage branch. Output must not already exist;
results include sanitized diagnostics and accepted findings, never rejected raw
completions. The replay does not enable external tracing or rerun the other agents.
The November 11 verification accepted 30/30 coverage-only cases versus 18/30
coverage branches in the original baseline. See
[`evals/results/coverage-validation-fix-2026-11-11.md`](evals/results/coverage-validation-fix-2026-11-11.md)
for the diagnosis, preserved checks, and limits of that comparison.

The first failed live review did not retain its finish reason or usage. Its
generic error was generated before JSON parsing, so invalid JSON was not the
observed validation failure. Truncation, reasoning consuming the budget, and
verbose output are plausible mechanisms, not established root causes. The
installed SDK exposes optional usage and reasoning-token counts. The improved
4,096-token request has not been live-tested in Step 6C.

[Fireworks reasoning documentation](https://docs.fireworks.ai/guides/reasoning)
describes `reasoning_effort` and an alternative `thinking` object with
`budget_tokens` for supported models; they cannot be combined. Compatibility and
semantics for this exact configured model have NOT been verified. No reasoning
option is sent or changed. Provider-specific usage fields outside the supported
SDK usage attributes remain unavailable in the sanitized diagnostics.

### Step 6E: explicit recommendation cardinality

Each Agent 3 finding must contain exactly one concise `suggested_tests` string,
including a test name, inputs and expected behavior. Zero through five findings
are allowed. The shared Pydantic schema remains unchanged; these additional
constraints apply only to Agent 3. Text quality remains model-dependent.

Count validation measures findings and the sum of suggested-test list lengths
separately. Sanitized failures report numeric counts for each exceeded limit and
the number of findings violating the one-entry requirement. Both exceeded limits
are reported when applicable. The entire invalid review fails with empty findings;
findings are never truncated, selectively dropped, merged or fabricated to repair
output. Valid counts do not bypass schema, exact evidence, line-reference, or
coverage-claim validation.

The Step 6D live response exceeded a limit, but its exact counts were not retained.
It is not established which count failed. The new contract and diagnostics have
offline regression coverage only; no live request was made in Step 6E. The
4,096-token output budget and zero automatic retries remain unchanged.

## Phase 3, Step 2: LangGraph foundation

`reviewguard.orchestration.graph.build_review_graph()` compiles a `StateGraph`
without loading credentials, creating clients, or making API calls. The graph
fans out from START to `code_quality_node`, `security_node`, and
`test_coverage_node`. A join edge waits for all three before running aggregation
once, then END. Aggregation currently sets workflow status only; the consolidated
report stays `None`. No deduplication or report formatting is implemented.

Create fresh state with `reviewguard.orchestration.state.create_initial_state`.
It includes filename, validated source_code, optional existing_tests and
measured_coverage, agent_results keyed by AgentType, consolidated_report, and
workflow_status. Use `await graph.ainvoke(state)` (or `asyncio.run` at a synchronous
entry point); nodes offload synchronous reviewers with `asyncio.to_thread`.
Invoke with default reviewers only when paid requests are intended: nonempty
source can cause up to three inference requests. No automatic retries are added.

For offline execution, inject synchronous `code_quality`, `security`, and
`test_coverage` callables into `build_review_graph`. The coverage callable accepts
existing_tests and measured_coverage keyword arguments. Branches emit only their
own result updates. The pure reducer copies results, merges independent keys,
and rejects all duplicate agent keys, even equal results, instead of overwriting them. Coverage inputs
are copied before being handed to its callable. Injected callables must be
thread-safe if a graph is invoked concurrently; default reviewer instances are
created per branch invocation. Unexpected branch failures become sanitized failed
results, allowing other results to reach aggregation. Use fresh initial state for
each run; completed result state is not a reset mechanism.

Shared schemas and the UI are unchanged. Agent 1 uses context-local SDK logging
filters rather than process-wide suppression, as described below.
Graph tests use injected offline callables, including a thread barrier to verify
overlapping execution and the aggregation join. Live concurrent Fireworks review
has not been verified. No persistence or tracing is configured by this foundation;
keep external LangSmith tracing disabled when handling private source.

### Step 3: concurrent real-agent wiring and logging isolation

The default graph creates a fresh reviewer and its own client inside each worker
thread for each request. No mutable SDK client or reviewer metadata is shared
between branches or concurrent workflows. Each client is closed by its owner.
Output budgets stay 2,048/2,048/4,096 tokens for quality/security/coverage,
respectively; 30-second timeouts and zero automatic retries are preserved.
The join barrier runs aggregation once after all three branches finish, with
independent results retained. It still sets execution status only, without
deduplication or report formatting.

Agent 1's context-local filter suppresses SDK/transport records in its calling
context and restores that context on exit, including exception and nested paths.
Filters are attached only to existing SDK/transport loggers and known OpenAI
client loggers; they pass records from other contexts. No application-wide logger
levels, handlers or disable flags are changed, and the old request-wide lock is
removed. Arbitrary custom loggers and transport child loggers first created after
filter registration are outside this filter's scope. Keep SDK DEBUG logging
disabled in production, as required by Agents 2 and 3; external logging/tracing
configuration remains the caller's responsibility.

Tests run all three existing reviewer implementations through default LangGraph
nodes with mocked client factories and blocked HTTP transport. Six calls across
two simultaneous workflows reach a barrier before any completes, then tests
force every possible branch-completion order. Assertions cover isolated clients,
inputs, results, logging, limits, cleanup, and exactly one aggregation per workflow.
This verifies concurrent execution offline; no live parallel Fireworks request
has been made. The previous equal-duplicate reducer assertion now requires a
failure, strengthening the new duplicate-result contract.

### Step 4: independent failures and partial workflow status

Every branch produces an explicit `AgentReviewResult`. Expected timeouts, invalid
results, unsupported source evidence, and raised callable exceptions become
failed results with empty findings and fixed sanitized error messages. Returned
failed/skipped results retain their status but their arbitrary error text is
replaced to protect source, credentials, and raw provider bodies. Successful
results are revalidated against Pydantic and exact source evidence; their
findings are preserved. No replacement findings are generated.

Aggregation requires all three agent results and runs once after the join:

- `completed`: all three agents succeeded, including successful empty reviews.
- `partial`: one or two succeeded and the others failed or skipped.
- `failed`: none succeeded, including all-skipped workflows.

A failed agent with zero findings is never counted as a clean successful review.
The report remains `None`; report formatting and deduplication remain deferred.
Duplicate-result rejection, state isolation, concurrent execution, per-agent SDK
timeouts and zero paid retries are preserved. No logging configuration changes
were introduced for failure handling. Custom injected callables remain responsible
for their own safe logging and bounded execution; exceptions are never logged
or exposed by the workflow. `asyncio.to_thread` cannot forcibly terminate a stuck
thread, and task cancellation does not guarantee cancellation of an in-flight
provider request. Internal graph/reducer invariant errors and process-level
interrupts are not converted into fabricated agent results.

Offline tests cover all 27 combinations of success/failed/skipped statuses,
successful empty findings, mocked SDK timeouts and invalid JSON, injected
exceptions and invalid evidence, all six completion orders, one aggregation per
run, preserved findings, sanitization, and simultaneous requests with mixed
outcomes. No live parallel Fireworks call has been made. The original mixed-result
assertion now expects `partial` rather than `failed`, matching this status contract.

### Step 5: deterministic aggregation data

`reviewguard.orchestration.aggregation.aggregate_findings(agent_results, sources=...)`
is a pure, network-free function requiring explicit results for all three agents.
Only successful agents contribute findings. Failed/skipped statuses remain in
`agent_statuses` with sanitized messages. Every successful original is revalidated
against the shared Pydantic schema and its exact source before grouping. The
shared schemas are unchanged.

Two findings group only when all of these match exactly after the stated
normalization: lexical filename (slash/dot normalization, case preserved),
1-based start/end location (omitted end means start), category, title, and
description. Text normalization only collapses whitespace and casefolds. Without
a start line, evidence must also match exactly. No fuzzy, semantic, LLM, or
line-overlap matching is used. Different concerns on the same line remain
separate. This conservative identity may miss differently worded duplicates;
it avoids guessing that two unrelated reports mean the same thing.

Each group retains `original_findings` in full and `provenance` with every agent
and original finding ID, including repeated identical originals. Distinct evidence,
recommendations, suggested tests, severities and confidences remain accessible.
The representative is an unchanged original selected by severity descending,
then confidence descending, normalized filename/location/category/title/description,
agent, finding ID and complete serialized original as deterministic tie-breakers.
Severity is never upgraded due to multiplicity, and confidence is never averaged
or treated as proof. Choosing the highest-severity original preserves conflicting
scores in metadata instead of synthesizing a new score.

The graph's existing join calls aggregation once and stores its JSON-compatible
intermediate data in `consolidated_report`, preserving completed/partial/failed
semantics and independent agent results. Initial report state remains `None`.
This is structured aggregation data, not final report formatting. It can contain
sensitive source evidence and must not be logged by callers. Returned data is
copied away from inputs; nested original models remain editable by their owner.
The previous report-placeholder assertions now verify structured output and
retained statuses. No live API requests or UI changes were made for this step.

### Step 6: structured review report and guarded JSON export

`reviewguard.reports.builder.build_review_report(aggregation, filename=...)`
wraps the already grounded aggregation data in `ReviewReport`. It preserves
prioritized groups, every original, provenance, evidence, recommendations,
confidence and suggested tests. It adds a UUID, timezone-aware UTC timestamp,
reviewed filename, total unique findings, counts for all four severities, and
mandatory engineering-verification and clean-review limitations. Optional
report_id/generated_at arguments permit deterministic tests. All other fields
are deterministic for identical aggregation input; summaries are validated.

The report inherits aggregation fields instead of reimplementing deduplication
or ranking. Agent status stays explicit: failed/skipped agents are never described
as clean reviews. All arbitrary error metadata is replaced by fixed sanitized
messages, including on JSON import. The builder accepts no uploaded source and
performs no execution, network calls, or file writes. It consumes aggregation
whose evidence has already been validated; it does not independently re-ground
an arbitrary caller-constructed aggregation object.

Use `reviewguard.reports.export.export_report_json(report)` for public JSON
serialization and `ReviewReport.model_validate_json(text)` for a round trip.
The exporter reads configured application .env and runtime secret values only
for comparison, without printing them, and checks common credential/private-key
patterns plus optional caller-provided `sensitive_values`. It examines decoded
strings so JSON escaping cannot bypass checks. Detected secrets raise a fixed
`UnsafeReportError`; nothing is silently redacted or removed from exact evidence.
The graph uses this guarded export in the existing single aggregation node.
An unsafe export prevents report release rather than returning sensitive JSON.
Direct Pydantic serialization bypasses that additional secret screen and is for
trusted internal use only. Pattern detection is conservative and cannot recognize
all possible secret formats; provide additional sensitive values when needed.

There is no source_code field: reports contain only validated evidence and
finding narratives, not a copy of the uploaded file. Callers should keep evidence
snippets minimal upstream; a snippet may itself contain sensitive code. Reports
remain sensitive artifacts and should not be logged. No coverage percentages
are computed. The UI and shared agent schemas remain unchanged. The graph keeps
its existing barrier and completed/partial/failed status semantics.

### Safe error-category propagation

`AgentReviewResult.error_category` is an optional, additive diagnostic field using
the shared `ErrorCategory` allowlist: `invalid_json`, `invalid_schema`,
`invalid_source_evidence`, `recommendation_limit_exceeded`, `output_truncated`,
`api_timeout`, `provider_error`, and `unknown_error`. Successful results have no
error category. Failed/skipped results without a known category use unknown_error;
unrecognized values are discarded and become unknown_error. No category is
inferred from arbitrary error text.

Each reviewer assigns known categories at its local validation/exception boundary.
Only an explicit finish_reason=length establishes output_truncated; missing or
other abnormal finish reasons remain unknown_error. Agent 3's count checks produce
recommendation_limit_exceeded. Pydantic JSON syntax errors and schema failures are
distinct, as are exact-source evidence failures and API timeouts/provider errors.
Unclassified configuration or execution failures remain unknown_error.

Graph branches retain allowlisted categories while replacing arbitrary messages
with fixed sanitized text. Aggregation and report agent_statuses preserve those
categories and sanitize messages again, including imported report metadata. Errors
remain separate from findings; successful findings and workflow status semantics
are unchanged. The previous live Agent 3 rejection cannot be reconstructed from
discarded metadata and must still be treated as unknown_error. Tests are offline
and no live request was made for this diagnostic change. No logging levels,
handlers, suppression policy, request budgets, or retries were changed.

## Phase 4, Step 1: dashboard foundation

The Streamlit app now groups the interface into Source code, Review configuration,
and Review results. It retains the Python-only uploader, 1 MiB limit, UTF-8 checks,
empty-file handling, filename/byte-size/line-count display, and Python preview.
Native bordered containers and responsive layouts organize the three reviewer
descriptions without custom CSS or additional dependencies.

This step does not connect the dashboard to LangGraph. The Review Code button
still displays the exact legacy message "AI review agents will be available in
Phase 2." A nearby explanation clarifies that it is a placeholder and no AI
requests are sent. It is disabled until a valid upload is available. Results
remain explicitly unrun: summary, unavailable severity counts, Not run agent
statuses, empty findings, and a disabled JSON download. Unavailable counts are
shown as dashes, not fabricated zeros. No configuration controls imply execution
that has not been implemented.

Headless AppTest checks cover layout, placeholder behavior, safe upload errors,
preview removal, and no graph/network calls. Existing upload/source/non-execution
regressions remain unchanged. Browser appearance at different viewport sizes and
screen-reader behavior have not been manually verified.

## Phase 4, Step 2: explicit workflow execution

Review Code now invokes the existing LangGraph workflow through
`reviewguard.ui.review_service.run_review`. Uploading, previewing, and ordinary
Streamlit reruns never call this service. Clicking Review Code sends the uploaded
source to the configured Fireworks model via the three real concurrent reviewers
and may incur charges. No live call was made during this implementation or its
automated verification.

Execution is separated from rendering. The synchronous service owns a dedicated
worker/event loop, checks application .env configuration before graph execution,
and invokes the existing async graph exactly once with fresh state. External
tracing is disabled within the execution context. Existing clients, timeouts,
token budgets and zero automatic retries remain unchanged. It stores no SDK
clients or source files. Custom exceptions are shown only as fixed safe messages.

The dashboard stores the resulting ReviewReport in session state, keyed to a
SHA-256 fingerprint of filename and source. Changing, removing, or invalidating
the upload clears the previous result. A queued/running/attempted guard disables
duplicate submission while execution is active and after an attempt. A spinner
indicates execution. Enable another review clears the result and re-arms the
button without inference; a separate Review Code click is required for any retry.
No review automatically retries after a failure.

The results area shows completed/partial/failed workflow status, unique finding
count, and explicit agent statuses. Successful zero-finding reviews are distinct
from failed/skipped agents, which are marked unavailable with allowlisted error
categories. Reports remain in memory across reruns. Detailed findings, severity
filters, and JSON download are deferred; download controls remain disabled.

All existing test cases are retained. Assertions that expected the old Phase 2
placeholder now verify mocked completed workflow results instead; their upload
validation and source-safety checks remain. New AppTest and service tests verify
submission counts, persistence, invalidation, statuses, sanitized errors, running
guards, configuration preflight and active-event-loop compatibility. Network calls
are blocked in the new tests. Live dashboard execution and browser behavior have
not been manually verified. A browser/session restart loses the in-memory result;
the running guard is session-local and is not a cross-session idempotency system.

## Phase 4, Step 3: detailed findings display

The dashboard renders the persisted consolidated ReviewReport directly. Severity
metrics use its existing unique counts, and finding expanders follow its existing
priority order; no new aggregation or sorting is performed. Each expander shows
the title, severity, reviewer, filename, line/range, description, exact source
evidence, recommended fix, original confidence value and optional test scenarios.
Deduplicated groups show contributing agent names and original IDs, plus original
evidence, recommendations, confidence/severity values and test suggestions.

All model-generated narrative is rendered with `st.text`, evidence with Python
`st.code`, and expander labels contain only fixed text, indices and enum severity.
Model HTML/Markdown is never interpreted as rich content. The existing guarded
export checks the report before display; detected secrets block report rendering
with a fixed safe message. No download is enabled by that check. This reuses the
existing guard and does not alter report or agent business logic. Secret detection
remains conservative, not a guarantee for arbitrary unknown secret formats.

Failed agents trigger a clear warning while successful findings remain visible.
Successful zero-finding reviews and unsuccessful reviews without accepted findings
have different notices. Engineering verification warnings remain visible. Results
persist on rerun and disappear when the upload changes. Submission guards,
spinner, explicit retry preparation and request budgets are unchanged. Severity
filters, JSON download and GitHub integration are deferred.

AppTest uses mocked orchestration to check counts/order, exact evidence including
indentation, line ranges, test suggestions, duplicate provenance, all workflow
statuses, zero-findings notices, plain-text handling, configured-secret blocking,
session persistence and upload invalidation without repeated requests. The old
zero-result dashboard assertion now requires the new explicit successful-empty
notice. Browser/screen-reader behavior and live dashboard execution remain
unverified; no live API requests were made in this step.

## Phase 4, Step 4: severity filters and JSON download

The saved report's findings can be filtered by All (default), Critical, High,
Medium, or Low. Filtering retains existing priority order and original finding
indices. The dashboard shows the visible/total count and a helpful no-match
notice. Summary severity counts, agent statuses, and failure warnings always
describe the full report, not the filtered subset. Filter changes never invoke
the execution service, and a new upload or explicit review re-arming resets the
selection to All.

Download JSON Report uses the existing guarded exporter and a fixed descriptive
filename `reviewguard-report.json` with MIME type `application/json`. The payload
always contains the full validated report, regardless of filter. No raw source
field is added. No report means disabled download; rejected exports show only a
sanitized error and offer no download or fallback. Secret checks are repeated
before rendering/download preparation. Existing secret-detection limitations
still apply, and evidence snippets remain sensitive data.

The native download uses `on_click="ignore"`, so a download does not request an
app rerun. Ordinary reruns also cannot bypass the existing explicit-submission
guard. AppTest checks prepared download bytes against the guarded exporter,
round-trip validation, MIME/filename, ignore-rerun configuration, filters,
persistence, warnings, rejection, and upload invalidation with mocked orchestration
and blocked HTTP transport. Browser download transfer itself is not simulated
by AppTest and has not been manually verified. No live AI requests were made.
The prior successful-review download assertion now requires enabled download;
all original test cases remain present.

## AI evaluations and LangSmith observability

The evaluation harness targets the complete code-quality, security, and test-
coverage graph. It includes 30 candidate Python cases (10 per reviewer), exact
source anchors, scenario labels, and suggested severities. These are **not
reviewed ground truth** until a human adjudicator verifies each expected finding
and records `annotation_status: "reviewed"`, `reviewer`, and `reviewer_notes`.
No evaluation command will upload or score a dataset with pending annotations.
The evaluation labels are candidates, not claims that model output is correct.

From `reviewguard-ai`, export and inspect the candidate dataset:

```powershell
.\.venv\Scripts\python.exe -m reviewguard.evals.cli export-candidates
.\.venv\Scripts\python.exe -m reviewguard.evals.cli validate --dataset evals\reviewed_golden_v1.jsonl
```

Review `evals\candidate_dataset.jsonl` with a qualified code reviewer. Keep the
30-50 case count, verify every source anchor and expected finding (including
negative cases), record the adjudicator and rationale, and preserve the original
file as the versioned evaluation dataset. Do not mark a case reviewed merely to
bypass the gate.

LangSmith tracing is opt-in. Traces can contain uploaded source code, prompts,
model outputs, and findings; use only code approved for external processing.
Set credentials in the process environment, never commit them or add them to
`.env`:

```powershell
$env:LANGSMITH_API_KEY = "<your LangSmith key>"
$env:LANGSMITH_PROJECT = "reviewguard-evals"
$env:REVIEWGUARD_LANGSMITH_TRACING = "true"
$env:REVIEWGUARD_ALLOW_PAID_EVAL = "true"
```

Upload only the adjudicated dataset:

```powershell
.\.venv\Scripts\python.exe -m reviewguard.evals.cli upload `
  --dataset evals\reviewed_golden_v1.jsonl --name reviewguard-golden-v1
```

The live command requires both `--confirm-paid-runs` and the explicit environment
authorization above. Each case invokes all three Fireworks agents (one request
per agent, no automatic retries), so a 30-case run can make up to 90 paid model
requests. Example baseline and post-change experiments:

```powershell
.\.venv\Scripts\python.exe -m reviewguard.evals.cli evaluate `
  --name reviewguard-golden-v1 --experiment-prefix baseline `
  --confirm-paid-runs

# Make and document a targeted improvement, then re-run against the same dataset.
.\.venv\Scripts\python.exe -m reviewguard.evals.cli evaluate `
  --name reviewguard-golden-v1 --experiment-prefix improved-v1 `
  --confirm-paid-runs
```

Per-case LangSmith feedback measures finding precision, recall, F1, exact match,
severity accuracy, target-agent success, workflow completion, and observed
latency. Traces include graph/agent runs and wrapped Fireworks chat-completion
child runs; inspect those for prompts/outputs, token usage, latency, errors, and
evaluation-case metadata. Provider cost is reported only when LangSmith supplies
it; no cost is inferred from assumed pricing. Compare experiment aggregates and
missed/extra finding feedback to identify failure clusters before prioritizing
prompt or workflow changes. Report before/after deltas from the same reviewed
cases and model configuration; do not claim improvement until measured.

Ordinary UI reviews remain untraced by default. Setting
`REVIEWGUARD_LANGSMITH_TRACING=true` explicitly enables traces for UI reviews.
The Python test suite uses mocked evaluator runs and does not contact LangSmith
or Fireworks. `evals/reviewed_golden_v1.jsonl` contains 30 cases marked reviewed
with pseudonymized human-review annotation metadata and passes the dataset validation gate. The
original `evals/candidate_dataset.jsonl` retains the pending candidate annotations.
No live LangSmith baseline/post-change experiment results are included. A local
30-case baseline is saved in `evals/results/baseline-2026-11-11.md` with raw
reports and summary JSON. No post-change quality improvement has been measured.

## Local quality baseline without LangSmith

The local runner uses the same three-agent workflow and reviewed cases without
requiring a LangSmith account. From `reviewguard-ai`, run:

```powershell
..\.venv\Scripts\python.exe -m reviewguard.evals.local `
  --dataset evals\reviewed_golden_v1.jsonl `
  --output evals\results\baseline-unique-name.jsonl --confirm-paid-runs
```

This makes at most 90 paid Fireworks requests for 30 cases, with no inference
retries. Both LangSmith and Langfuse tracing are explicitly disabled for this
command. Results are saved locally one case at a time, including the full report,
reference findings, model ID, dataset hash, statuses, latency, and scores. The
output file must not already exist. A companion `.summary.json` contains macro
averages overall and per target reviewer. Each case runs all three agents, but
finding quality is scored only for that case's designated target reviewer.

Scores match reference anchors against evidence verbatim with one-to-one
matching; they do not verify the semantic correctness of model prose. Unmatched
predictions count as extras even when a human might accept them. Successful
negative cases receive precision/recall/F1/exact-match of one; unavailable target
agents receive zero rather than being mistaken for correct clean reviews.
Severity accuracy is averaged per case, with zero for cases without a match;
it should not be read as accuracy among matched findings. Consult the saved
reports before deciding which prompts or labels need changes.

The November 11 baseline achieved macro anchor F1 of 64.3% (code quality 100%,
security 80%, test coverage 13%). Only 18/30 full workflows completed: test
coverage failed validation in 12/30 invocations. See
[`evals/results/baseline-2026-11-11.md`](evals/results/baseline-2026-11-11.md)
for scoring limits, disagreement analysis, and reproducibility details.

## Langfuse tracing (opt-in)

Langfuse traces are disabled unless `REVIEWGUARD_LANGFUSE_TRACING=true` is set
in the application `.env` or process environment. Configure
`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_BASE_URL` there;
`LANGFUSE_HOST` is accepted for existing configurations. `.env.example` contains
placeholders only. The Langfuse Python SDK 5 integration uses LangGraph callbacks
and traces the Fireworks generations, including provider-reported input, output,
and total token counts when available. It performs no connectivity check at
startup. Trace flushing is attempted after successful and failed graph execution;
a flush failure does not discard a completed report or replace a workflow error.

**When enabled, traces include uploaded source code, prompts, model responses,
and findings.** Only enable this for code approved for external processing.
LangSmith tracing is separately opt-in; enabling both sends trace data to both
services. Pytest uses mocks and does not contact Langfuse, LangSmith, or Fireworks.
Each traced review owns a root span whose context is copied into all three agent
workers, keeping their generations in the same trace. Dashboard browser behavior
still requires manual verification. No paid requests are needed for offline tests.

### Explicit live tracing diagnostic

From `reviewguard-ai`, run:

```powershell
..\.venv\Scripts\python.exe scripts\test_langfuse_connection.py --confirm-paid-run
```

Without the confirmation flag this command sends no requests. With the flag it
checks Langfuse authentication before running a tiny synthetic Python review.
It explicitly enables Langfuse and disables LangSmith for this diagnostic, makes
at most three paid Fireworks requests with no inference retries, and polls for
up to 45 seconds for three persisted generations with input, output, and usage.
It prints statuses and the diagnostic trace ID without printing credentials,
prompts, findings, or raw remote errors. A failed diagnostic is not automatically
retried. A polling timeout means delivery was not verified within that window.

Live verification on November 11, 2026 completed successfully after fixing worker
trace context propagation: all three agents succeeded and all three generations
were retrieved from trace `5492ac6a46a7096d4974e2036511cb29` with input, output,
and usage. This confirms delivery for the synthetic sample; it does not measure
review accuracy or replace a baseline evaluation.
