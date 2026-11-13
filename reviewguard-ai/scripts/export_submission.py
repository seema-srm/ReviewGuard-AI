"""Render the submission report and its Mermaid diagrams locally.

Requires Playwright, Google Chrome, and cached mermaid/marked npm packages:
  npm install --prefix .pytest_cache/submission-tools mermaid marked
Run from reviewguard-ai: python scripts/export_submission.py
No project data is sent to an external service.
"""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
TOOLS = ROOT / ".pytest_cache" / "submission-tools" / "node_modules"

STYLE = """
@page { size: A4; margin: 18mm 16mm; }
* { box-sizing: border-box; }
body { font-family: Arial, sans-serif; color: #172b42; font-size: 12px;
       line-height: 1.55; max-width: 760px; margin: 30px auto; }
h1 { font-size: 22px; margin: 32px 0 12px; color: #153b60; }
h1:first-child { font-size: 32px; border-bottom: 3px solid #26888d; padding-bottom: 16px; }
h2 { font-size: 17px; }
h1, h2 { break-after: avoid; }
p, li { orphans: 3; widows: 3; }
table { border-collapse: collapse; width: 100%; margin: 14px 0; font-size: 11px; }
th, td { border: 1px solid #cbd5df; padding: 8px; text-align: left; vertical-align: top; }
th { background: #e9f1f7; color: #153b60; }
tr { break-inside: avoid; }
thead { display: table-header-group; }
pre { background: #f2f5f8; padding: 12px; border: 1px solid #dbe2e8;
      white-space: pre-wrap; overflow-wrap: anywhere; font-size: 10px; }
code { font-family: Consolas, monospace; }
a { color: #135e80; overflow-wrap: anywhere; }
.mermaid { break-inside: avoid; margin: 20px 0; background: white; }
.mermaid svg { display: block; margin: auto; max-width: 100%; max-height: 850px; }
@media print { body { margin: 0; max-width: none; } }
"""


def main():
    markdown = (DOCS / "PROJECT_SUBMISSION.md").read_text(encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page(viewport={"width": 900, "height": 1100}, device_scale_factor=1.5)
            page.route("http://**/*", lambda route: route.abort())
            page.route("https://**/*", lambda route: route.abort())
            page.set_content(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>ReviewGuard AI Project Submission</title><style>{STYLE}</style></head><body></body></html>')
            page.add_script_tag(path=str(TOOLS / "marked" / "lib" / "marked.umd.js"))
            page.add_script_tag(path=str(TOOLS / "mermaid" / "dist" / "mermaid.min.js"))
            page.evaluate("source => { document.body.innerHTML = marked.parse(source); }", markdown)
            page.evaluate("""async () => {
                mermaid.initialize({startOnLoad: false, securityLevel: 'strict', theme: 'neutral'});
                const blocks = [...document.querySelectorAll('pre:has(code.language-mermaid)')];
                for (let i = 0; i < blocks.length; i++) {
                    const source = blocks[i].textContent;
                    await mermaid.parse(source);
                    const result = await mermaid.render('diagram-' + i, source);
                    const container = document.createElement('div');
                    container.className = 'mermaid';
                    container.innerHTML = result.svg;
                    blocks[i].replaceWith(container);
                }
            }""")
            names = ("architecture", "workflow", "sequence", "data-model")
            diagrams = page.locator("div.mermaid")
            assert diagrams.count() == len(names)
            for index, name in enumerate(names):
                diagram = diagrams.nth(index)
                svg = diagram.locator("svg")
                assert svg.count() == 1
                (DOCS / "diagrams" / f"{name}.svg").write_text(svg.evaluate("el => el.outerHTML"), encoding="utf-8")
                diagram.screenshot(path=str(DOCS / "diagrams" / f"{name}.png"))
            # Save a standalone document containing rendered inline SVGs, no scripts.
            page.evaluate("document.querySelectorAll('script').forEach(el => el.remove())")
            (DOCS / "PROJECT_SUBMISSION.html").write_text(page.content(), encoding="utf-8")
            page.pdf(path=str(DOCS / "ReviewGuardAI-PROJECT_SUBMISSION.pdf"), print_background=True,
                     prefer_css_page_size=True, display_header_footer=True,
                     header_template="<span></span>",
                     footer_template='<div style="font-size:8px;width:100%;text-align:center;color:#607080">ReviewGuard AI Project Submission · <span class="pageNumber"></span> / <span class="totalPages"></span></div>')
            pdf = (DOCS / "ReviewGuardAI-PROJECT_SUBMISSION.pdf").read_bytes()
            assert pdf.startswith(b"%PDF-") and len(pdf) > 10000
            print(json.dumps({"diagrams_rendered": len(names), "pdf_bytes": len(pdf),
                              "document": str(DOCS / "ReviewGuardAI-PROJECT_SUBMISSION.pdf")}, indent=2))
        finally:
            browser.close()


if __name__ == "__main__":
    main()
