# Coverage validation verification — November 11, 2026

The coverage reviewer accepted all 30 frozen synthetic cases in a new
coverage-only pass, compared with 18/30 accepted coverage branches in the original
three-agent baseline. All 12 previously failed cases passed. This verifies
validation reliability for this sample; it is not a semantic quality improvement
claim or a new full-workflow benchmark.

| Run | Cases | Accepted | Failure details |
| --- | ---: | ---: | --- |
| Original full-workflow baseline, coverage branches | 30 | 18 | 9 schema-category, 3 source-evidence |
| Diagnostic replay of the 12 failed cases, before fixes | 12 | 4 | 5 missing-test-claim, 1 percentage-claim, 1 line-range, 1 connection |
| Coverage-only verification after fixes | 30 | 30 | None |

## Diagnosis and changes

The initial replay added sanitized stage diagnostics without changing the prompt
or validators. It showed that many failures categorized broadly as schema errors
were actually application-level claim guards, not necessarily malformed JSON.
Rejected raw completions were not retained, so their precise wording is unknown.

Offline regressions independently demonstrate that the old word-level guards
rejected legitimate scenarios involving missing files/keys or application inputs
such as 0% and 100% discounts. Claim checks now require coverage-related language
or recognizable missing-test assertions. They still reject numeric coverage
claims and unsupported statements that tests are absent. These are heuristic
guards, not comprehensive semantic claim detection.

The prompt now explicitly requests recommendations rather than missing-test
claims when no tests are supplied. Numbered application lines are provided as
untrusted data alongside the unchanged source to help the model cite correct
locations. Exact source checks still run against the original source. The source
validator, shared schemas, cardinality limits, request timeout, output budget,
and no-retry policy are unchanged. No evidence or findings are repaired or dropped
to make an invalid response pass. All 30 accepted responses were nonempty (one
through five findings).

The new immutable per-call validation diagnostics contain only a fixed stage,
optional zero-based finding index, and fixed source-error code. They distinguish
filename, out-of-range line, absent evidence, and evidence outside its cited range
without retaining rejected model text or credentials.

## Evidence and reproducibility

- Model: `accounts/fireworks/models/deepseek-v4p1-flash-1017` (unchanged).
- Dataset SHA-256: `74915922f2e6688f7a4d4d82c097457aa23b1aa56a2b5f53f57bea3598dc90b2` (unchanged).
- Post-fix prompt SHA-256: `bcb9b7e1ca36e55929c6e03e94c808931b10d4b6708bf21b48052164d21b20c5`.
- Post-fix reviewer SHA-256: `c45002bc6b39a8458e2cb5d0b65bc30b8bce29e3967d5994d65454e48a82a27e`.
- Original baseline: `baseline-2026-11-11.jsonl` (unchanged).
- Diagnostic replay: `coverage-diagnosis-2026-11-11.jsonl` and companion summary.
- Post-fix verification: `coverage-fixed-2026-11-11.jsonl` and companion summary.
- Live budget: up to 12 diagnosis requests plus 30 verification requests, all
  coverage-only with no automatic inference retries. One diagnostic call ended in
  a connection failure; provider billing for that failed call is unknown.
- Post-fix coverage duration: 283.67 seconds total. No other agents or external
  tracing services were invoked by these replay commands.
- Offline checks: 533 tests passed in the full run; one new test's dataset fixture
  needed correction. Both tests in that file passed after correction, verifying
  all 534 distinct tests across the full run and focused rerun. Compilation and
  whitespace checks also passed.

Generation is nondeterministic: this single pass does not establish a general
zero-failure rate. Numbered source context adds prompt tokens; source/context size
remains the caller's responsibility. The original anchor-based scoring limits
still apply, and the original 13% coverage macro F1 has not been replaced by a
new quality score. Semantic recommendation quality and a full three-agent
post-change baseline remain separate follow-up work.
