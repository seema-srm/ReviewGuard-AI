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
responsibility. To suppress SDK debug output, reviews through this agent are
serialized while logging is temporarily disabled and restored afterward; other
threads' logs may also be suppressed during that interval. Automated agent tests
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
