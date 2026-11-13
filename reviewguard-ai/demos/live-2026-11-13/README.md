# ReviewGuard AI live demo

Recorded November 13, 2026 using the production dashboard and the explicitly
approved synthetic `samples/demo_review.py`. This was a real Fireworks review,
not a mocked response. One submission allowed up to three paid requests with no
automatic retries; LangSmith and Langfuse tracing were disabled.

## Deliverables

- `reviewguard-demo.webm`: 30.64-second silent browser walkthrough, 1440 by 1000 pixels.
- `01-dashboard.png`: initial dashboard.
- `02-source-preview.png`: uploaded source preview.
- `03-review-results.png`: completed workflow, severity counts, and agent statuses.
- `04-finding-detail.png`: expanded finding and prioritized findings list.
- `05-severity-filter.png`: severity filtering of the saved report.
- `reviewguard-report.json`: full downloaded report with all seven findings.
- `summary.json`: concise execution outcome.

Open the WebM recording in Chrome or Edge. The video contains no spoken audio;
use the presentation script below when presenting or recording narration.
Viewing these saved artifacts makes no additional model requests.

## Actual result

All three reviewers succeeded. The report contains seven findings: zero Critical,
four High, two Medium, and one Low. The quality reviewer identified the inverted
even-number predicate. The security reviewer identified SQL injection from
interpolating a username into the SQL string. The test reviewer recommended five
scenarios, including even numbers, zero and negative even inputs, SQL-injection
behavior, database exception propagation, and empty results.

The example contains intentional defects and was never executed. The app reviewed
the source text only. A completed review confirms execution and validation for
this sample; it does not establish general accuracy or replace the pending
30-case post-fix quality benchmark. Exact provider billing was not collected.

## Suggested presentation script

**Introduce the project:** “ReviewGuard AI reviews Python source from three
perspectives: code quality, security, and test recommendations. The reviewers run
concurrently, and their validated findings become one prioritized report.”

**Show the upload:** “This is a synthetic example with an incorrect even-number
check and an unsafe SQL query. Uploading shows a source preview without running
the code or starting inference.”

**Show the review:** “Selecting Review Code explicitly starts the live Fireworks
review. This recorded run completed successfully for all three agents.”

**Explain the results:** “The dashboard reports seven findings. The code-quality
reviewer found the inverted predicate; the security reviewer found SQL injection;
the test reviewer proposed five scenarios. Each finding includes its source
location, exact evidence, a recommendation, and model-assigned confidence.”

**Show filtering and export:** “Severity filtering uses the saved report and makes
no additional model calls. The downloaded JSON contains the full report even
when the display is filtered.”

**Close:** “The application has 534 passing offline tests, browser and selected
keyboard checks, and this successful live demo. Findings still require human
verification. A broader post-fix quality benchmark and complete accessibility
acceptance remain follow-up work.”

## Repeating a live recording

The recorder requires Playwright, Google Chrome, and Playwright's FFmpeg encoder.
With a production app running and provider credentials configured, the recorder
can be invoked with an explicitly authorized new output path. Do not re-run it
merely to view this demo: a new submission may incur charges. The script refuses
to reuse a directory containing artifacts and has no automatic review retry.
