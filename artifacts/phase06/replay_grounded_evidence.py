"""Reproduce issue #40 results from preserved originals and open the links in Chrome."""

import gzip
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from unittest.mock import patch
from urllib.parse import urlencode

from werkzeug.serving import make_server

from frag.store import SourceStore
from frag.web import create_app

PHASE = Path(__file__).resolve().parent
ROOT = PHASE.parents[1]
sys.path.insert(0, str(PHASE.parent / "phase04"))
from sec_holdout_runner import ask_case, command, open_citations, replay_case

CASES = (
    ("coca-cola-absent", "06", "ko-20241231.htm",
     "What was reported consolidated revenue growth from FY2021 to FY2024?"),
    ("pg-equal-length", "06", "pg-20240630.htm",
     "What was reported consolidated revenue growth from FY2023 to FY2024 using equal-length fiscal years?"),
    ("ge-historical", "06", "ge10-k2018.htm", "What was reported consolidated revenue in FY2018?"),
    ("apple-fy2024", "05", "aapl-20240928.htm", "What was revenue in FY2024?"),
    ("microsoft-growth", "01", "msft-20230630.htm",
     "How did reported consolidated revenue change from FY2022 to FY2023?"),
)


def check_results(runs):
    def excerpt(run, key):
        opened = run["citations"][key]
        assert opened["http_status"] == 200
        assert run["result"]["source_hash"] in opened["text"]
        return opened["text"]

    coke, pg, ge, apple, microsoft = runs
    result = coke["result"]
    assert result["status"] == "unavailable" and result["percent"] is None
    assert result["issues"][0]["code"] == "absent"
    assert [(fact["role"], fact["normalized_amount"]) for fact in result["operands"]] == [
        ("current", "47061000000"),
    ]
    periods = excerpt(coke, "statement-periods").partition("\n\n")[2]
    assert {"2022", "2023", "2024", "Year Ended December 31,"} <= set(periods.splitlines())
    assert "47,061" in excerpt(coke, "current")

    result = pg["result"]
    assert result["status"] == "unavailable" and result["percent"] is None
    assert "FY2023 spans 365 days and FY2024 spans 366 days" in result["issues"][0]["detail"]
    assert "82,006" in excerpt(pg, "prior")
    assert "84,039" in excerpt(pg, "current")
    calendar = excerpt(pg, "fiscal-calendar")
    assert "2022-07-01\n2023-06-30" in calendar and "2023-07-01\n2024-06-30" in calendar

    assert ge["result"]["reason"] == apple["result"]["reason"] == "unverified"
    assert "inline XBRL" in ge["result"]["message"]
    assert "disclosures" in apple["result"]["message"]
    assert not ge["citations"] and not apple["citations"]
    assert microsoft["result"]["percent"] == {"unit": "percent", "value": "6.88"}
    for role, amount in (("prior", "198,270"), ("current", "211,915")):
        text = excerpt(microsoft, role)
        assert amount in text and "iso4217:USD" in text and "In millions" in text


def check_browser(store, runs, replays, planner):
    from playwright.sync_api import expect, sync_playwright

    app = create_app(store, ROOT / "web/dist", planner=planner)
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
                for (case_id, _, _, question), run, replay in zip(CASES, runs, replays, strict=True):
                    result = run["result"]
                    page.goto(f'{origin}/?{urlencode({"source": result["source_id"]})}')
                    chat = page.get_by_role("region", name="Ask the filing")
                    chat.get_by_role("textbox").fill(question)
                    with page.expect_response(lambda response: response.url.endswith("/lookup")) as asked:
                        chat.get_by_role("button", name="Ask", exact=True).click()
                    assert asked.value.json() == result
                    if result.get("percent"):
                        expect(chat.get_by_text("6.88%", exact=True)).to_be_visible()
                    elif result.get("issues"):
                        expect(chat.get_by_text(result["issues"][0]["detail"], exact=True)).to_be_visible()
                        expect(chat.get_by_text("Supported observations")).to_be_visible()
                    else:
                        expect(chat.get_by_text(result["message"], exact=True)).to_be_visible()
                    for citation in result["citations"]:
                        with context.expect_page() as opened:
                            chat.get_by_role("link", name=citation["title"], exact=True).click()
                        tab = opened.value
                        body = tab.locator("body")
                        expect(body).to_contain_text(result["source_hash"])
                        assert body.inner_text().strip() == replay[citation["id"]]["text"].strip()
                        tab.close()
                    print(f'{case_id}: Chrome {browser.version}, {len(replay)} citation responses matched')
                browser.close()
        finally:
            server.shutdown()
            thread.join()


def deny_network(*args, **kwargs):
    raise AssertionError("Offline replay opened a socket")


def main():
    # Reuse the original recorded Microsoft planner response at the model boundary.
    legacy_record = ROOT / "artifacts/phase02/chat-growth-validation/warm.json"
    saved = json.loads(legacy_record.read_bytes())

    def planner(payload):
        assert payload["messages"] == saved["model_request"]["messages"]
        return saved["proposed_plan"]

    with TemporaryDirectory(prefix="frag-issue40-") as work:
        base = Path(work)
        store, offline = SourceStore(base / "original"), SourceStore(base / "offline")
        runs, replays = [], []
        with (patch("socket.socket", deny_network), patch("socket.create_connection", deny_network),
              patch("socket.getaddrinfo", deny_network), patch("frag.cli.propose_lookup", planner)):
            for case_id, phase, filename, question in CASES:
                archive = PHASE.parent / f"phase{phase}" / "originals" / f"{filename}.gz"
                original = gzip.decompress(archive.read_bytes())
                source = store.ingest_bytes(original, provenance="local_original")
                case = {"case_id": case_id, "question": question}
                run = ask_case(store.root, case, source, base / f"{case_id}-ask.json")
                replay_source = offline.ingest_bytes(original, provenance="local_original")
                assert replay_case(offline.root, case, replay_source, run) == {"status": "matched"}
                runs.append(run)
                replays.append(open_citations(offline.root, run["result"]))
            assert command("replay-ask", str(legacy_record), "--store", str(offline.root)) == saved["result"]
        check_results(runs)
        print(f"Socket-blocked replay matched {len(runs)} results and {sum(map(len, replays))} citation responses.")
        check_browser(offline, runs, replays, planner)


if __name__ == "__main__":
    main()
