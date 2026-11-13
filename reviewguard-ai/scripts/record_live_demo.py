"""Record one explicit paid browser review of a synthetic sample.

Start the production app with tracing disabled, then run with --confirm-paid-run.
At most one Review Code click is issued. No automatic retry is performed.
"""

import argparse
import json
from pathlib import Path
import re

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-paid-run", action="store_true")
    parser.add_argument("--url", default="http://127.0.0.1:8501")
    parser.add_argument("--output", type=Path, default=ROOT / "demos" / "live-2026-11-13")
    args = parser.parse_args()
    if not args.confirm_paid_run:
        parser.error("--confirm-paid-run authorizes up to three paid Fireworks requests")
    if args.output.exists() and any(args.output.iterdir()):
        raise FileExistsError("Demo output already contains artifacts; refusing a possible duplicate paid run")
    args.output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000}, accept_downloads=True,
            record_video_dir=str(args.output), record_video_size={"width": 1440, "height": 1000},
            reduced_motion="reduce",
        )
        page = context.new_page()
        page.set_default_timeout(30000)
        expect.set_options(timeout=30000)
        video = page.video
        try:
            page.goto(args.url)
            review = page.get_by_role("button", name="Review Code", exact=True)
            expect(review).to_be_disabled()
            page.screenshot(path=str(args.output / "01-dashboard.png"))
            page.locator('input[type="file"]').set_input_files(str(ROOT / "samples" / "demo_review.py"))
            expect(page.get_by_text("Filename: demo_review.py", exact=True)).to_be_visible()
            expect(review).to_be_enabled()
            page.screenshot(path=str(args.output / "02-source-preview.png"))
            page.wait_for_timeout(2000)
            print("Submitting one live review: up to three paid Fireworks requests.", flush=True)
            review.click()
            status = page.get_by_text(re.compile(r"^Review status: (completed|partial|failed)$"))
            expect(status).to_be_visible(timeout=120000)
            outcome = status.inner_text()
            print(outcome, flush=True)
            page.get_by_role("heading", name="Review results", exact=True).evaluate("el => el.scrollIntoView({block:'start'})")
            page.screenshot(path=str(args.output / "03-review-results.png"))
            page.wait_for_timeout(2500)
            details = page.locator("summary")
            if details.count():
                details.first.click()
                details.first.evaluate("el => el.scrollIntoView({block:'start'})")
                page.screenshot(path=str(args.output / "04-finding-detail.png"))
                page.wait_for_timeout(3000)
            selector = page.get_by_role("combobox", name="Filter by severity")
            selector.focus()
            selector.press("ArrowDown")
            selector.press("Enter")
            page.screenshot(path=str(args.output / "05-severity-filter.png"))
            page.wait_for_timeout(2000)
            with page.expect_download() as event:
                page.get_by_role("button", name="Download JSON Report", exact=True).click()
            event.value.save_as(str(args.output / "reviewguard-report.json"))
            report = json.loads((args.output / "reviewguard-report.json").read_text(encoding="utf-8"))
            summary = {
                "demo_date": "2026-11-13", "source": "samples/demo_review.py",
                "kind": "live Fireworks review; no mocked reviewers",
                "workflow_status": report["workflow_status"],
                "total_unique_findings": report["total_unique_findings"],
                "counts_by_severity": report["counts_by_severity"],
                "agent_statuses": [{"agent": agent["agent"], "status": agent["status"],
                                     "error_category": agent.get("error_category")}
                                    for agent in report["agent_statuses"]],
                "review_submissions": 1, "maximum_model_requests": 3,
                "automatic_retries": 0,
            }
            (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(summary, indent=2), flush=True)
        except Exception:
            page.screenshot(path=str(args.output / "demo-error.png"))
            raise
        finally:
            context.close()
            if video is not None:
                video.save_as(str(args.output / "reviewguard-demo.webm"))
                video.delete()
            browser.close()


if __name__ == "__main__":
    main()
