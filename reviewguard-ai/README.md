# ReviewGuard AI

Multi-Agent Code Review Platform — Phase 1 starter.

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
No API keys, `.env` file, or external service accounts are required.

## Tests and compilation

From `reviewguard-ai`, using the same environment:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q app.py reviewguard tests samples
```

Tests use in-memory uploads and Streamlit AppTest without a browser, network
access, or API keys. UI tests substitute an in-memory uploader result so they
can exercise previews, validation errors, and the placeholder review button.

## Project structure

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

## Phase 1 scope

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
