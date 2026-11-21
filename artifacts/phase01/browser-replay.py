"""Exercise the built workspace and CLI using Chrome and a temporary store."""

import gzip
import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

from replay import CLI

ROOT = Path(__file__).resolve().parents[2]
SERVER_CLI = """
import sys
def loopback_only(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname'}:
        host = args[1][0] if event == 'socket.connect' else args[0]
        if host not in {'127.0.0.1', 'localhost', '::1'}:
            raise RuntimeError('External network access is disabled for the browser replay')
sys.addaudithook(loopback_only)
from frag.cli import main
raise SystemExit(main())
"""


def main() -> None:
    with TemporaryDirectory() as temp:
        base = Path(temp)
        upload = base / "browser-synthetic.html"
        upload.write_bytes(b"<html><p>Synthetic browser replay input.</p></html>")
        store = str(base / "store")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        server = subprocess.Popen(
            [sys.executable, "-c", SERVER_CLI, "serve", "--store", store, "--port", str(port)],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            deadline = monotonic() + 15
            while True:
                try:
                    with urlopen(origin, timeout=1):
                        break
                except URLError:
                    if monotonic() >= deadline or server.poll() is not None:
                        raise
                    sleep(0.1)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    channel=os.environ.get("FRAG_BROWSER", "chrome"),
                    args=["--disable-background-networking"],
                )
                try:
                    context = browser.new_context(service_workers="block")
                    context.route("**/*", lambda route: route.continue_()
                                  if route.request.url.startswith(origin + "/") else route.abort())
                    page = context.new_page()
                    page.goto(origin)
                    expect(page.get_by_text("No sources saved yet.")).to_be_visible()
                    page.get_by_label("HTML file").set_input_files(upload)
                    page.get_by_label("Synthetic fixture").check()
                    save = page.get_by_role("button", name="Preserve source")
                    save.click()
                    digest = hashlib.sha256(upload.read_bytes()).hexdigest()
                    expect(page.get_by_text(f"sha256:{digest}", exact=True)).to_be_visible()
                    expect(page.get_by_text(digest, exact=True)).to_be_visible()
                    expect(page.get_by_text("Synthetic input · Source preserved")).to_be_visible()
                    expect(page.get_by_text("Unknown", exact=True)).to_have_count(5)
                    save.click()
                    expect(page.get_by_text("Source saved and open for inspection.")).to_be_visible()
                    expect(page.get_by_role("heading", name="Saved sources (1)")).to_be_visible()
                    page.get_by_text("Optional filing metadata", exact=True).click()
                    page.get_by_label("Company", exact=True).fill("Conflicting company")
                    save.click()
                    expect(page.get_by_role("alert")).to_contain_text("different metadata or provenance")

                    def cli(*args: str) -> dict:
                        return json.loads(subprocess.check_output(
                            [sys.executable, "-c", CLI, *args, "--store", store], cwd=ROOT,
                        ))

                    saved = cli("inspect", f"sha256:{digest}")
                    assert Path(saved["original_path"]).read_bytes() == upload.read_bytes()
                    assert saved["company"] is None and saved["real_source_acceptance"] is False
                    cli("ingest", "tests/fixtures/synthetic.html", "--provenance", "synthetic",
                        "--company", "CLI synthetic fixture")
                    page.get_by_role("button", name="Refresh").click()
                    page.get_by_role("button", name="CLI synthetic fixture").click()
                    expect(page.get_by_role("heading", name="CLI synthetic fixture")).to_be_visible()
                    expect(page.get_by_text("Expected exactly one table headed Income Statements.")).to_be_visible()

                    # Older servers can return a preserved source without extraction diagnostics.
                    legacy = {**saved, "parser_version": None}
                    legacy.pop("diagnostics")
                    legacy_page = context.new_page()
                    legacy_page.route(
                        origin + "/api/sources",
                        lambda route: route.fulfill(json={"source_count": 1, "sources": [legacy]}),
                    )
                    legacy_page.goto(origin)
                    legacy_page.locator(".sources button").click()
                    expect(legacy_page.get_by_role("heading", name="Source record")).to_be_visible(timeout=1500)
                    expect(legacy_page.get_by_text("Revenue extraction is unavailable for this saved source.")).to_be_visible()
                    legacy_page.close()

                    page.get_by_label("Company", exact=True).fill("Synthetic revenue fixture")
                    page.get_by_label("HTML file").set_input_files(ROOT / "tests/fixtures/synthetic_income.html")
                    save.click()
                    expect(page.get_by_text("FY2023 · USD 963,000,000 · Provisional")).to_be_visible()
                    page.get_by_text("FY2022 · USD 817,000,000 · Provisional").click()
                    expect(page.get_by_text("2021-07-01 through 2022-06-30")).to_be_visible()
                    expanded = page.locator("details[open]").filter(has_text="FY2022")
                    expect(expanded.get_by_text("Revenue cell", exact=True)).to_be_visible()
                    filing = base / "msft-20230630.htm"
                    archive = ROOT / "artifacts/phase01/originals/msft-20230630.htm.gz"
                    original = gzip.decompress(archive.read_bytes())
                    filing.write_bytes(original)
                    filing_hash = hashlib.sha256(original).hexdigest()
                    page.get_by_label("Company", exact=True).fill("")
                    page.get_by_label("Local original", exact=True).check()
                    page.get_by_label("HTML file").set_input_files(filing)
                    save.click()
                    page.get_by_text("FY2023 · USD 211,915,000,000 · Verified").click()
                    expect(page.get_by_text("FY2022 · USD 198,270,000,000 · Verified")).to_be_visible()
                    expanded = page.locator("details[open]").filter(has_text="FY2023")
                    expect(expanded.get_by_text("Note 8 · Business Combinations")).to_be_visible()
                    expect(expanded.get_by_text("HTML lines 13913–14338")).to_be_visible()
                    expect(page.get_by_text("Nuance was consolidated from March 4, 2022.", exact=False)).to_be_visible()

                    filing.unlink()
                    calculate = page.get_by_role("button", name="Calculate revenue growth")
                    calculate.click()
                    growth = page.get_by_role("region", name="Revenue growth", exact=True)
                    expect(growth.get_by_text("6.88%", exact=True)).to_be_visible()
                    expect(growth.get_by_text("Microsoft disclosed an unfavorable foreign currency impact",
                                              exact=False)).to_be_visible()
                    growth.get_by_text("Operation trace and operands").click()
                    expect(growth.get_by_text("13645000000", exact=False).first).to_be_visible()
                    for link, evidence in (
                        ("FY2022 Total revenue cell", ("HTML line 4403", "Total revenue", "198,270")),
                        ("FY2023 Total revenue cell", ("HTML line 4399", "Total revenue", "211,915")),
                        ("Note 1 · Accounting Policies", ("NOTE 1", "ACCOUNTING POLICIES")),
                        ("Note 8 · Business Combinations", ("NOTE 8", "On March 4, 2022")),
                        ("Note 13 · Unearned Revenue", ("NOTE 13", "UNEARNED REVENUE")),
                        ("Note 19 · Segment Information and Geographic Data", ("NOTE 19", "GEOGRAPHIC DATA")),
                        ("Segment recast", ("HTML line 1909", "Reportable Segments", "We have recast")),
                        ("Acquisition and exchange rates", ("HTML line 2315", "Fiscal Year 2023 Compared with Fiscal Year 2022",
                                                            "unfavorable foreign currency impact of 4%")),
                        ("Xandr acquisition", ("HTML line 2671", "Fiscal Year 2023 Compared with Fiscal Year 2022",
                                               "More Personal Computing", "the Xandr acquisition")),
                    ):
                        with context.expect_page() as excerpt:
                            growth.get_by_role("link", name=link, exact=True).click()
                        try:
                            for text in evidence:
                                expect(excerpt.value.locator("body")).to_contain_text(text)
                            expect(excerpt.value.locator("body")).to_contain_text(filing_hash)
                        finally:
                            excerpt.value.close()

                    page.get_by_label("Prior fiscal year").fill("2021")
                    calculate.click()
                    expect(growth.get_by_text("Missing reported consolidated revenue for FY2021 (prior).")).to_be_visible()
                    expect(growth.get_by_text("6.88%", exact=True)).to_have_count(0)
                    expect(page.get_by_text("FY2023 · USD 211,915,000,000 · Verified")).to_be_visible()
                    print("Browser growth replay passed: 6.88%, operation trace, both original cells, "
                          "all four applicable notes, three comparison disclosures, "
                          "and retained FY2023 evidence with a missing prior year.")
                    if "--lookup" in sys.argv[1:]:
                        chat = page.get_by_role("region", name="Ask the filing")
                        question = chat.get_by_role("textbox")
                        ask = chat.get_by_role("button", name="Ask", exact=True)
                        question.fill("What was revenue?")
                        ask.click()
                        expect(chat.get_by_text("Ask for annual reported consolidated revenue",
                                                exact=False)).to_be_visible()
                        for year, amount, cell in (
                            (2022, "198,270,000,000", "198,270"),
                            (2023, "211,915,000,000", "211,915"),
                        ):
                            question.fill(f"What was FY{year} revenue?")
                            ask.click()
                            expect(chat.get_by_text(f"USD {amount}", exact=True)).to_be_visible(timeout=35000)
                            with context.expect_page() as excerpt:
                                chat.get_by_role("link", name=f"FY{year} Total revenue cell").click()
                            try:
                                body = excerpt.value.locator("body")
                                expect(body).to_contain_text(f"Total revenue {year} (In millions, except per share amounts) {cell}")
                                expect(body).to_contain_text(filing_hash)
                            finally:
                                excerpt.value.close()
                        print("Browser lookup passed: clarification, both verified answers, and both original cells.")
                finally:
                    browser.close()
            print("Browser replay passed: upload, hash, unknowns, retry, conflict, CLI interoperability, "
                  "provisional and verified facts, notes, and comparison. External requests blocked.")
        finally:
            server.terminate()
            server.wait(timeout=10)


if __name__ == "__main__":
    main()
