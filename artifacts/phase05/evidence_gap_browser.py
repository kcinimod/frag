"""Check evidence-gap explanations and original links in the built workspace."""

import gzip
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
from typing import Any

from playwright.sync_api import BrowserContext, Locator, expect, sync_playwright
from werkzeug.serving import make_server

from frag.store import SourceStore
from frag.web import create_app
from growth_browser import OFFLINE_CLI, ROOT
from score import audit

PHASE = ROOT / "artifacts/phase05"
ABSENT = "What was revenue growth from FY2020 to FY2023?"
EXTRACTION_GAP = "What was revenue growth from FY2021 to FY2023?"
VERIFICATION_GAP = "What was revenue in FY2024?"


def check_citation(context: BrowserContext, link: Locator, source_hash: str, *evidence: str) -> None:
    with context.expect_page() as opened:
        link.click()
    citation = opened.value
    for text in (*evidence, source_hash):
        expect(citation.locator("body")).to_contain_text(text)
    citation.close()


def check_browser(store: SourceStore, sources: list[dict[str, Any]], results: list[dict[str, Any]]) -> None:
    def offline_planner(_: object) -> str:
        raise AssertionError("An evidence gap reached the planner")

    app = create_app(store, ROOT / "web/dist", planner=offline_planner)
    with make_server("127.0.0.1", 0, app) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", args=["--disable-background-networking"])
                context = browser.new_context(service_workers="block")
                context.route("**/*", lambda route: route.continue_()
                              if route.request.url.startswith(origin + "/") else route.abort())
                page = context.new_page()
                page.goto(origin)
                chat = page.get_by_role("region", name="Ask the filing")
                source_ids = sorted(source["source_id"] for source in sources)
                for source, result, question in zip(sources, results, (ABSENT, EXTRACTION_GAP, VERIFICATION_GAP),
                                                    strict=True):
                    page.locator(".sources button").nth(source_ids.index(source["source_id"])).click()
                    chat.get_by_role("textbox").fill(question)
                    chat.get_by_role("button", name="Ask", exact=True).click()
                    if "message" in result:
                        expect(chat.get_by_text(result["message"], exact=True)).to_be_visible()
                        expect(chat.get_by_role("link")).to_have_count(0)
                        continue
                    issue, = result["issues"]
                    expect(chat.get_by_text(issue["detail"], exact=True)).to_be_visible()
                    expect(chat.get_by_text("Supported observations")).to_be_visible()
                    fact, = result["operands"]
                    expect(chat.get_by_text(f'FY2023 · USD {fact["normalized_amount"]}', exact=False)).to_be_visible()
                    expect(chat.locator(".growth-value")).to_have_count(0)
                    source_hash = source["source_hash"]
                    for citation in result["citations"]:
                        title, identifier = citation["title"], citation["id"]
                        evidence = ()
                        if identifier == "current":
                            evidence = (fact["raw_amount"], "2023", "iso4217:USD")
                        if identifier == "statement-periods":
                            evidence = ("CONSOLIDATED STATEMENTS OF OPERATIONS", "Total net sales",
                                        "September 25, 2021", "September 24, 2022", "September 30, 2023")
                        check_citation(context, chat.get_by_role("link", name=title, exact=True), source_hash, *evidence)
                    if issue["code"] == "absent":
                        chat.get_by_role("textbox").fill("What was revenue in FY2020?")
                        chat.get_by_role("button", name="Ask", exact=True).click()
                        expect(chat.get_by_text(issue["detail"], exact=True)).to_be_visible()
                        check_citation(context, chat.get_by_role("link", name="Consolidated revenue statement periods"),
                                       source_hash, "Total net sales", "September 25, 2021", "September 30, 2023")
                print(f"Chrome {browser.version} matched all three offline CLI explanations.")
                print("Apple FY2020 absence and Microsoft FY2021 extraction gap kept cited FY2023 amounts.")
                print("Apple FY2024 remained an evidence gap for disclosure verification.")
                browser.close()
        finally:
            server.shutdown()
            thread.join()


def main() -> None:
    manifest = json.loads((PHASE / "inputs.json").read_bytes())
    expected = json.loads((PHASE / "expected.json").read_bytes())["sources"]
    filings = {filing["accession"]: filing for filing in manifest["sources"]}
    with TemporaryDirectory() as work:
        store = SourceStore(Path(work) / "store")
        sources, results = [], []
        for accession, question in (("0000320193-23-000106", ABSENT), ("0000950170-23-035122", EXTRACTION_GAP),
                                    ("0000320193-24-000123", VERIFICATION_GAP)):
            filing = filings[accession]
            original = Path(work) / filing["original_filename"]
            original_bytes = gzip.decompress((ROOT / filing["archive"]).read_bytes())
            original.write_bytes(original_bytes)
            audit(original_bytes, filing, expected[accession])
            cli = [sys.executable, "-c", OFFLINE_CLI]
            store_args = ["--store", str(store.root)]
            source = json.loads(subprocess.check_output([
                *cli, "ingest", str(original), "--provenance", "local_original",
                "--accession", accession, "--company", filing["issuer"], *store_args,
            ]))
            assert source["source_hash"] == filing["sha256"]
            record = Path(work) / f"{accession}.json"
            result = json.loads(subprocess.check_output([
                *cli, "ask", source["source_id"], question, "--record", str(record), *store_args,
            ]))
            assert result == json.loads(subprocess.check_output([*cli, "replay-ask", str(record), *store_args]))
            if "operands" in result:
                companion, = result["operands"]
                assert companion["normalized_amount"] == expected[accession]["facts"]["2023"]["normalized_amount"]
            sources.append(source)
            results.append(result)
        assert [result["issues"][0]["code"] for result in results[:2]] == ["absent", "unverified"]
        assert results[0]["issues"][0]["detail"].endswith("The statement shows FY2021, FY2022, FY2023.")
        assert "The statement shows this year" in results[1]["issues"][0]["detail"]
        assert results[2]["reason"] == "unverified"
        assert "reviewed verification reference" in results[2]["message"]
        assert "The applicable filing disclosures need verification." in results[2]["message"]
        check_browser(store, sources, results)


if __name__ == "__main__":
    main()
