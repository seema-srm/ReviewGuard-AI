"""Offline browser validation. Requires optional playwright and installed Chrome.

Run from the application directory: python scripts/verify_browser.py
The isolated server replaces inference with synthetic reports and blocks HTTPX.
Production app and configuration are not modified.
"""

import argparse
import json
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "def example(value):\n    return value\n"


def serve(counter):
    sys.path.insert(0, str(ROOT))
    from reviewguard.orchestration.aggregation import aggregate_findings
    from reviewguard.reports.builder import build_review_report
    from reviewguard.schemas import AgentReviewResult, AgentType, ReviewFinding

    def synthetic_review(upload):
        counter.write_text(str(int(counter.read_text()) + 1))
        if upload.filename == "error.py":
            raise RuntimeError("PRIVATE_PROVIDER_ERROR")
        findings = [] if upload.filename == "clean.py" else [
            ReviewFinding(
                finding_id=f"browser-{index}", agent="code_quality",
                title=f"Synthetic {severity} concern <b>plain text</b>",
                category="logic", severity=severity, filename=upload.filename,
                line_number=2, description="Synthetic browser validation finding.",
                evidence="    return value", recommendation="Check input behavior.",
                confidence=0.8, suggested_tests=["test_value: input=1; expected=1"],
            ) for index, severity in enumerate(("HIGH", "LOW"))
        ]
        results = {
            agent: AgentReviewResult(
                agent=agent,
                status="failed" if upload.filename == "partial.py" and agent == AgentType.security else "success",
                findings=findings if agent == AgentType.code_quality else [],
            ) for agent in AgentType
        }
        return build_review_report(
            aggregate_findings(results, sources={upload.filename: upload.source}),
            filename=upload.filename,
        )

    with patch("reviewguard.ui.review_service.run_review", side_effect=synthetic_review), \
         patch("httpx.Client.send", side_effect=AssertionError("Offline validation: HTTP prohibited")), \
         patch("httpx.AsyncClient.send", side_effect=AssertionError("Offline validation: HTTP prohibited")):
        runpy.run_path(str(ROOT / "app.py"), run_name="__main__")


def verify(artifacts=None):
    from playwright.sync_api import sync_playwright, expect
    sys.path.insert(0, str(ROOT))
    from reviewguard.reports.models import ReviewReport

    if artifacts is not None:
        artifacts.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="reviewguard-browser-", ignore_cleanup_errors=True) as directory:
        directory = Path(directory)
        counter = directory / "calls.txt"
        counter.write_text("0")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        with (directory / "server.log").open("w") as log:
            server = subprocess.Popen([
                sys.executable, "-m", "streamlit", "run", str(Path(__file__).resolve()),
                "--server.headless=true", "--server.address=127.0.0.1",
                f"--server.port={port}", "--browser.gatherUsageStats=false",
                "--", "--serve", "--counter", str(counter),
            ], cwd=ROOT, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                for _ in range(100):
                    if server.poll() is not None:
                        raise RuntimeError("Validation server exited; inspect browser harness configuration")
                    try:
                        with urlopen(url + "/_stcore/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(0.2)
                else:
                    raise RuntimeError("Validation server did not become healthy")

                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(channel="chrome", headless=True)
                    try:
                        page = browser.new_page(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
                        page.set_default_timeout(20000)
                        expect.set_options(timeout=20000)
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.goto(url)
                        review = page.get_by_role("button", name="Review Code", exact=True)
                        download = page.get_by_role("button", name="Download JSON Report", exact=True)
                        upload = page.locator('input[type="file"]')
                        expect(review).to_be_disabled()
                        expect(download).to_be_disabled()
                        if artifacts is not None:
                            page.screenshot(path=str(artifacts / "desktop-empty.png"))

                        def load(name, data=SOURCE.encode()):
                            upload.set_input_files({"name": name, "mimeType": "text/x-python", "buffer": data})
                            expect(page.get_by_text(f"Filename: {name}", exact=True)).to_be_visible()
                            expect(review).to_be_enabled()

                        upload.set_input_files({"name": "invalid.py", "mimeType": "text/x-python", "buffer": b"\xff"})
                        expect(page.get_by_test_id("stAlertContainer").filter(has_text="UTF-8")).to_be_visible()
                        expect(review).to_be_disabled()
                        load("empty.py", b"")
                        expect(page.get_by_text("This file is empty (0 lines).", exact=True)).to_be_visible()
                        assert counter.read_text() == "0"
                        load("example.py")
                        review.focus()
                        expect(review).to_be_focused()
                        review.press("Enter")
                        expect(page.get_by_text("Review status: completed", exact=True)).to_be_visible()
                        expect(review).to_be_disabled()
                        expect(upload).to_be_enabled()
                        expect(download).to_be_enabled()
                        expect(page.get_by_text("Visible findings: 2 of 2", exact=True)).to_be_visible()
                        assert counter.read_text() == "1"
                        assert page.locator("b").filter(has_text="plain text").count() == 0
                        details = page.locator("summary").first
                        details.focus()
                        expect(details).to_be_focused()
                        details.press("Enter")
                        expect(page.get_by_text("Description", exact=True).first).to_be_visible()
                        if artifacts is not None:
                            for width, label in ((1440, "desktop"), (390, "phone")):
                                page.set_viewport_size({"width": width, "height": 1000})
                                page.get_by_role("heading", name="Review results", exact=True).evaluate("el => el.scrollIntoView({block: 'start'})")
                                page.screenshot(path=str(artifacts / f"{label}-results.png"))
                                page.get_by_role("heading", name="Prioritized findings", exact=True).evaluate("el => el.scrollIntoView({block: 'start'})")
                                page.screenshot(path=str(artifacts / f"{label}-findings.png"))
                            (artifacts / "results-accessibility.txt").write_text(page.locator("body").aria_snapshot(), encoding="utf-8")
                            page.set_viewport_size({"width": 1440, "height": 1000})
                        selector = page.get_by_role("combobox", name="Filter by severity")
                        selector.focus()
                        expect(selector).to_be_focused()
                        selector.press("ArrowDown")
                        selector.press("Enter")
                        expect(page.get_by_text("No findings match Critical. Choose All or another severity to see other findings.", exact=True)).to_be_visible()
                        with page.expect_download() as event:
                            download.focus()
                            expect(download).to_be_focused()
                            download.press("Enter")
                        artifact = event.value
                        assert artifact.suggested_filename == "reviewguard-report.json"
                        payload = json.loads(Path(artifact.path()).read_text(encoding="utf-8"))
                        report = ReviewReport.model_validate(payload)
                        assert report.filename == "example.py" and report.total_unique_findings == 2
                        assert {group.representative.severity.value for group in report.findings} == {"HIGH", "LOW"}
                        assert "source" not in payload
                        assert counter.read_text() == "1"
                        page.get_by_role("button", name="Enable another review", exact=True).click()
                        expect(review).to_be_enabled()
                        expect(download).to_be_disabled()
                        assert counter.read_text() == "1"

                        load("partial.py")
                        review.click()
                        expect(page.get_by_text("Review status: partial", exact=True)).to_be_visible()
                        expect(upload).to_be_enabled()
                        expect(page.get_by_text("One or more agents failed.", exact=False)).to_be_visible()
                        expect(download).to_be_enabled()
                        load("clean.py")
                        expect(download).to_be_disabled()
                        review.click()
                        expect(page.get_by_text("The review completed successfully with zero accepted findings.", exact=False)).to_be_visible()
                        load("error.py")
                        review.click()
                        expect(page.get_by_text("Review could not be completed. Sensitive provider details are hidden. No automatic retry was attempted.", exact=True)).to_be_visible()
                        expect(upload).to_be_enabled()
                        expect(download).to_be_disabled()
                        assert "PRIVATE_PROVIDER_ERROR" not in page.locator("body").inner_text()
                        assert counter.read_text() == "4"

                        for width in (390, 768, 1440):
                            page.set_viewport_size({"width": width, "height": 900})
                            expect(page.get_by_role("heading", name="ReviewGuard AI", exact=True)).to_be_visible()
                            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), f"Horizontal overflow at {width}px"
                        assert not errors, errors
                        print("PASS: real Chrome upload validation, explicit execution, severity filter, full JSON download,")
                        print("      re-arming, upload invalidation, partial/empty/error reports, 390/768/1440px overflow,")
                        print("      no page errors; exactly four synthetic reviews and zero model requests.")
                        print("      Keyboard: review, finding expansion, severity selection, and download passed.")
                    finally:
                        browser.close()
            finally:
                server.terminate()
                server.wait(timeout=15)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--counter", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--artifacts", type=Path, help="Save screenshots and an accessibility snapshot locally")
    args = parser.parse_args()
    if args.serve:
        serve(args.counter)
    else:
        verify(args.artifacts)
