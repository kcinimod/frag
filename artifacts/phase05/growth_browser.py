"""Replay the Intel growth and compatibility results in the built workspace."""

import gzip
import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from frag.store import SourceStore
from frag.web import create_app

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT / "artifacts/phase05/originals/intc-20231230.htm.gz"
EQUAL_LENGTH = "What was reported consolidated revenue growth from FY2022 to FY2023 using equal-length fiscal years?"
OFFLINE_CLI = """
import sys
def offline(event, args):
    if event.startswith('socket.'):
        raise RuntimeError('Network disabled for CLI replay')
sys.addaudithook(offline)
from frag.cli import main
raise SystemExit(main())
"""


def main() -> None:
    with TemporaryDirectory() as work:
        store = SourceStore(Path(work) / "store")
        source = store.ingest_bytes(gzip.decompress(ORIGINAL.read_bytes()), provenance="local_original")
        output = subprocess.check_output([
            sys.executable, "-c", OFFLINE_CLI, "growth", source["source_id"], "2022", "2023",
            "--store", str(store.root),
        ])
        cli_percent = json.loads(output)["percent"]["value"]
        assert cli_percent == "-14.00"

        def offline_planner(_: object) -> str:
            raise AssertionError("This browser replay should not need the planner")

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
                    page.locator(".sources button").click()
                    expect(page.get_by_role("heading", name="FY2022 and FY2023 comparison")).to_be_visible()
                    growth = page.get_by_role("region", name="Revenue growth")
                    growth.get_by_role("button", name="Calculate revenue growth").click()
                    expect(growth.get_by_text(f"{cli_percent}%", exact=True)).to_be_visible()
                    expect(growth.get_by_text("FY2022 spans 53 weeks and FY2023 spans 52 weeks.", exact=False)).to_be_visible()
                    growth.get_by_text("Operation trace and operands").click()
                    expect(growth.get_by_text("prior · FY2022 · USD 63054000000", exact=False)).to_be_visible()
                    expect(growth.get_by_text("current · FY2023 · USD 54228000000", exact=False)).to_be_visible()
                    chat = page.get_by_role("region", name="Ask the filing")
                    chat.get_by_role("textbox").fill(EQUAL_LENGTH)
                    chat.get_by_role("button", name="Ask", exact=True).click()
                    expect(chat.get_by_text("Supported observations")).to_be_visible()
                    expect(chat.get_by_text("requested equal-length comparison", exact=False)).to_be_visible()
                    expect(chat.get_by_text(f"{cli_percent}%", exact=True)).to_have_count(0)
                    expect(chat.get_by_text("prior · FY2022 · USD 63054000000", exact=False)).to_be_visible()
                    expect(chat.get_by_text("current · FY2023 · USD 54228000000", exact=False)).to_be_visible()
                    for region in (growth, chat):
                        for title, evidence in (
                            (r"^FY2022 Net revenue cell$", ("Dec 31, 2022", "63,054", "iso4217:USD", "In Millions")),
                            (r"^FY2023 Net revenue cell$", ("Dec 30, 2023", "54,228", "iso4217:USD", "In Millions")),
                            (r"Basis of Presentation$", ("2022 was a 53-week fiscal year",)),
                            (r"Revenue Recognition$", ("transfer of control",)),
                        ):
                            with context.expect_page() as opened:
                                region.get_by_role("link", name=re.compile(title)).click()
                            citation = opened.value
                            for text in (*evidence, source["source_hash"]):
                                expect(citation.locator("body")).to_contain_text(text)
                            citation.close()
                    print(f"Chrome {browser.version}. CLI and browser both returned {cli_percent}%.")
                    print("Equal-length growth withheld the percentage and showed both verified operands.")
                    print("Both results reopened the two original cells, fiscal-calendar note, and revenue note.")
                    print(f'Intel source SHA-256: {source["source_hash"]}')
                    browser.close()
            finally:
                server.shutdown()
                thread.join()


if __name__ == "__main__":
    main()
