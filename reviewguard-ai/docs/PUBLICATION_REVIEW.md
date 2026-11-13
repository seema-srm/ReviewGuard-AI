# Public repository preparation

Reviewed November 13, 2026. Public release should use sanitized tracked files and
sanitized Git history. Making a repository public exposes its historical commits,
not only the current file contents.

## File preparation

- Provider configuration is loaded from environment variables or an ignored `.env`.
- Personal human-review labels are replaced with the pseudonym `reviewer-01`.
- Private document links are removed from the report sources and regenerated PDF/HTML.
- Demonstration source, screenshots, recording, and report use synthetic examples.
- Root and application ignore rules exclude local environments, audit workspaces,
  `.env` files, and common credential/key file types.
- API-related identifiers and test placeholders remain in code because they are
  configuration names or synthetic fixtures, rather than usable credentials.

The configured provider key values were checked without printing them. The
publication audit also checked provider token patterns, private-key material,
personal email addresses, personal reviewer labels, private document links, and
user-specific filesystem paths. Commit metadata must be sanitized separately.
This review is evidence from specific checks, not a universal guarantee that
arbitrary sensitive information cannot exist.

## Evaluation integrity

Pseudonymization changes the reviewed dataset's file hash. Application source,
reference findings, severities, reviewed status, and recorded quality scores are
unchanged. Historical dataset hashes in saved evaluation results identify the
original experiment inputs; they are not hashes of the pseudonymized public file.
Do not alter those recorded hashes to imply a new experiment was performed.

## Publication checks

- [x] Sanitize current reviewer labels and private document links.
- [x] Regenerate and inspect document artifacts.
- [x] Run offline regression tests: 534 passed, one dependency warning.
- [ ] Apply and verify sanitized history for every GitHub branch and tag.
- [ ] Recheck public-facing branch heads and author/committer identities.
- [ ] Change repository visibility only after history cleanup is verified.

Push explicitly selected branches. Do not use a mirror push from the development
workspace: local tooling refs and checkpoints are not release artifacts.
