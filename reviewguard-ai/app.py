"""ReviewGuard AI dashboard with explicit, session-scoped review execution."""

from hashlib import sha256

import streamlit as st

from reviewguard.config import MAX_FILE_SIZE_BYTES
from reviewguard.fireworks_client import ConfigurationError
from reviewguard.file_utils import FileValidationError, ValidatedFile, validate_python_file
from reviewguard.ui.review_service import run_review
from reviewguard.reports.export import UnsafeReportError, export_report_json
from reviewguard.schemas import Severity


def source_upload() -> ValidatedFile | None:
    """Preview validated uploads in memory without running or saving source."""
    st.header("Source code")
    with st.container(border=True):
        uploaded_file = st.file_uploader(
            "Upload a Python file", type=["py"], max_upload_size=1,
            help="One UTF-8 .py file, up to 1 MB (1,048,576 bytes).",
            disabled=st.session_state.get("review_running", False),
        )
        if uploaded_file is None:
            st.caption("Choose a Python file to inspect its source before review.")
            return None
        if uploaded_file.size > MAX_FILE_SIZE_BYTES:
            st.error("File exceeds the 1 MB (1,048,576 bytes) limit.")
            return None
        try:
            validated = validate_python_file(uploaded_file.name, uploaded_file.getvalue())
        except FileValidationError as exc:
            st.error(str(exc))
            return None

        with st.container(horizontal=True):
            st.write(f"Filename: {validated.filename}")
            st.write(f"File size: {validated.size_bytes:,} bytes")
            st.write(f"Line count: {validated.line_count}")
        if not validated.source:
            st.info("This file is empty (0 lines).")
        st.subheader("Source preview")
        st.code(validated.source, language="python")
        return validated


def review_configuration() -> None:
    st.header("Review configuration")
    st.caption("Review Code runs all three reviewers concurrently using the configured Fireworks model.")
    with st.container(horizontal=True):
        for name, scope in (
            ("Code Quality Reviewer", "Logic, boundary conditions, exceptions, and maintainability."),
            ("Security Reviewer", "Injection risks, unsafe input handling, and credential exposure."),
            ("Test Coverage Reviewer", "Boundary scenarios, negative cases, and test recommendations."),
        ):
            with st.container(border=True, width="stretch"):
                st.subheader(name)
                st.write(scope)
                st.caption("Included in review")


def empty_review_results() -> None:
    st.header("Review results")
    st.info("No review has been run. Upload a file and select Review Code to begin.")
    with st.container(border=True):
        st.subheader("Review summary")
        st.write("Awaiting review · No report generated")
        st.subheader("Severity counts")
        st.caption("Counts are unavailable until a review completes.")
        for column, severity in zip(st.columns(4), ("CRITICAL", "HIGH", "MEDIUM", "LOW")):
            column.metric(severity, "—", help="Not measured: no review has run.")
        st.subheader("Agent execution statuses")
        for name in ("Code Quality Reviewer", "Security Reviewer", "Test Coverage Reviewer"):
            st.write(f"{name}: Not run")
        st.subheader("Prioritized findings")
        st.caption("No findings to display before execution.")
        st.subheader("JSON report export")
        st.caption("Run a review to generate a validated JSON report.")
        st.download_button("Download JSON Report", data="", file_name="reviewguard-report.json",
                           mime="application/json", disabled=True)


def queue_review() -> None:
    if not st.session_state.review_running and not st.session_state.review_attempted:
        st.session_state.review_pending = True
        st.session_state.review_running = True
        st.session_state.review_attempted = True


def enable_another_review() -> None:
    st.session_state.review_attempted = False
    st.session_state.review_report = None
    st.session_state.review_error = None
    st.session_state.severity_filter = "All"


def review_results() -> None:
    report = st.session_state.review_report
    if report is None:
        empty_review_results()
        return
    st.header("Review results")
    try:
        encoded_report = export_report_json(report)  # Guard before display or download.
    except UnsafeReportError:
        st.error("Report display blocked: potentially sensitive content detected.")
        return
    except Exception:
        st.error("Report could not be displayed safely. Sensitive details are hidden.")
        return
    message = f"Review status: {report.workflow_status}"
    if report.workflow_status == "completed":
        st.success(message)
    elif report.workflow_status == "partial":
        st.warning(message)
    else:
        st.error(message)
    st.subheader("Review summary")
    st.text(f"Reviewed file: {report.filename}")
    st.write(f"Unique findings: {report.total_unique_findings}")
    st.subheader("Severity counts")
    for column, severity in zip(st.columns(4), Severity):
        column.metric(severity.value, report.counts_by_severity[severity],
                      help="Unique findings reported by successful agents; not proof of correctness.")
    if any(agent.status == "failed" for agent in report.agent_statuses):
        st.warning("One or more agents failed. Their review is unavailable; accepted findings from successful agents are preserved.")
    st.subheader("Agent execution statuses")
    names = {"code_quality": "Code Quality Reviewer", "security": "Security Reviewer", "test_coverage": "Test Coverage Reviewer"}
    for agent in report.agent_statuses:
        findings_count = sum(item.agent == agent.agent for group in report.findings for item in group.original_findings)
        detail = f"success · {findings_count} findings" if agent.status == "success" else f"{agent.status} · review unavailable"
        st.write(f"{names[agent.agent.value]}: {detail}")
        if agent.status != "success":
            st.caption(f"Diagnostic category: {agent.error_category.value}")
    for warning in report.warnings:
        st.text(warning)
    st.subheader("Prioritized findings")
    selection = st.selectbox("Filter by severity", ["All", "Critical", "High", "Medium", "Low"],
                             key="severity_filter", help="Filters this saved report only; no review is rerun.")
    visible = [(index, group) for index, group in enumerate(report.findings, start=1)
               if selection == "All" or group.representative.severity.value == selection.upper()]
    st.caption(f"Visible findings: {len(visible)} of {report.total_unique_findings}")
    if not report.findings:
        if report.workflow_status == "completed":
            st.info("The review completed successfully with zero accepted findings. This does not prove the code is free of issues.")
        else:
            st.info("No accepted findings are available. Failed or skipped agents did not complete a successful clean review.")
    elif not visible:
        st.info(f"No findings match {selection}. Choose All or another severity to see other findings.")
    for index, group in visible:
        finding = group.representative
        # Model text is rendered only with st.text/st.code, never Markdown/HTML.
        st.text(f"{index}. {finding.title}")
        with st.expander(f"Finding {index} · {finding.severity.value}"):
            st.text(f"Title: {finding.title}")
            st.text(f"Severity: {finding.severity.value}")
            st.text(f"Agent: {names[finding.agent.value]}")
            st.text(f"Filename: {finding.filename}")
            location = "Not specified"
            if finding.line_number is not None:
                location = str(finding.line_number)
                if finding.end_line is not None and finding.end_line != finding.line_number:
                    location += f"–{finding.end_line}"
            st.text(f"Source lines: {location}")
            st.text("Description")
            st.text(finding.description)
            st.text("Exact source evidence")
            st.code(finding.evidence, language="python")
            st.text("Recommended fix")
            st.text(finding.recommendation)
            st.text(f"Confidence: {finding.confidence} (model-assigned; not proof of correctness)")
            st.text("Suggested test scenarios")
            if finding.suggested_tests:
                for scenario in finding.suggested_tests:
                    st.text(scenario)
            else:
                st.text("No test scenarios were supplied for this finding.")
            st.text("Original agent provenance")
            for item in group.provenance:
                st.text(f"{names[item.agent.value]} · Finding ID: {item.finding_id}")
            if len(group.original_findings) > 1:
                st.text("Original contributions (preserved before deduplication)")
                for original in group.original_findings:
                    st.text(f"{names[original.agent.value]} · {original.finding_id} · Severity: {original.severity.value} · Confidence: {original.confidence}")
                    st.code(original.evidence, language="python")
                    st.text(original.recommendation)
                    for scenario in original.suggested_tests or []:
                        st.text(scenario)
    st.subheader("JSON report export")
    st.caption("Download includes the complete report, regardless of the selected severity filter.")
    st.download_button("Download JSON Report", data=encoded_report, file_name="reviewguard-report.json",
                       mime="application/json", on_click="ignore", key="download_report")


def main() -> None:
    st.set_page_config(page_title="ReviewGuard AI", page_icon=":material/shield:", layout="wide")
    st.title("ReviewGuard AI")
    st.write("Multi-Agent Code Review Platform")
    st.caption("Explicit reviews · Three concurrent agents · No automatic retries")
    for key, default in {"review_report": None, "review_error": None, "review_upload": None,
                         "review_running": False, "review_pending": False, "review_attempted": False}.items():
        st.session_state.setdefault(key, default)
    validated = source_upload()
    fingerprint = sha256((validated.filename + "\0" + validated.source).encode("utf-8")).hexdigest() if validated else None
    if fingerprint != st.session_state.review_upload:
        st.session_state.review_upload = fingerprint
        st.session_state.review_report = None
        st.session_state.review_error = None
        st.session_state.review_running = False
        st.session_state.review_pending = False
        st.session_state.review_attempted = False
        st.session_state.severity_filter = "All"
    review_configuration()
    st.button("Review Code", type="primary", key="submit_review", on_click=queue_review,
              disabled=validated is None or st.session_state.review_running or st.session_state.review_attempted)
    st.caption("Sending a review shares this file with Fireworks AI and may incur charges. Uploading alone sends no request.")
    if st.session_state.review_pending and validated is not None:
        st.session_state.review_pending = False
        try:
            with st.spinner("Running the three reviewers…"):
                st.session_state.review_report = run_review(validated)
        except ConfigurationError:
            st.session_state.review_error = "Fireworks configuration is missing or invalid. Check the application .env file."
        except Exception:
            st.session_state.review_error = "Review could not be completed. Sensitive provider details are hidden. No automatic retry was attempted."
        finally:
            st.session_state.review_running = False
        # Refresh widgets rendered while the queued review was still running.
        # The pending flag is already cleared, so this cannot resubmit a review.
        st.rerun()
    if st.session_state.review_error:
        st.error(st.session_state.review_error)
    if st.session_state.review_attempted and not st.session_state.review_running:
        st.button("Enable another review", on_click=enable_another_review,
                  help="Clears this result. You must click Review Code separately to send another request.")
    st.divider()
    review_results()


if __name__ == "__main__":
    main()
