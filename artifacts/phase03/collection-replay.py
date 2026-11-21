"""Reproduce the preserved collection through the public CLI and browser."""

import argparse
import gzip
import hashlib
import json
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from typing import Any

from frag.cli import main as frag

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).with_name("corpus-manifest.json")


def audit_network(event: str, args: tuple[Any, ...]) -> None:
    # The smoke server and browser may use loopback. External sockets are blocked.
    if event == "socket.connect":
        assert args[1][0] in {"127.0.0.1", "::1"}, "External socket blocked."
    if event in {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"}:
        assert args[0] in {"127.0.0.1", "::1", "localhost"}, "External DNS blocked."


def replay(work: Path) -> None:
    store = work / "store"
    manifest = json.loads(MANIFEST.read_bytes())

    def invoke(*args: str) -> dict[str, Any]:
        with redirect_stdout(StringIO()) as output:
            assert frag([*args, "--store", str(store)]) == 0
        result: dict[str, Any] = json.loads(output.getvalue())
        return result

    commands: list[list[str]] = []
    for source in manifest["sources"]:
        payload = (ROOT / source["path"]).read_bytes()
        if "archive_sha256" in source:
            assert hashlib.sha256(payload).hexdigest() == source["archive_sha256"]
            payload = gzip.decompress(payload)
            assert len(payload) == source["byte_count"]
        assert hashlib.sha256(payload).hexdigest() == source["source_hash"]
        path = work / source["name"]
        path.write_bytes(payload)
        command = ["ingest", str(path), "--provenance", source["provenance"]]
        for key, value in source["metadata"].items():
            command.extend(("--" + key.replace("_", "-"), value))
        assert invoke(*command)["source_hash"] == source["source_hash"]
        commands.append(command)

    first = invoke("index-collection")
    for command in commands:
        invoke(*command)
        Path(command[1]).unlink()
    assert first == invoke("index-collection")
    assert len(first["sources"]) == 3
    assert len(first["fact_ids"]) == len(set(first["fact_ids"])) == 6
    print(f'Validated {first["snapshot_id"]} with three sources, six facts, and stable reindexing.')

    for expected in manifest["expected_answers"]:
        year = expected["fiscal_year"]
        record = work / f"fy{year}-lookup.json"
        answer = invoke("ask-collection", expected["question"], "--record", str(record))
        assert answer == invoke("replay-collection", str(record))
        assert answer["snapshot_id"] == first["snapshot_id"]
        assert answer["status"] == "answered"
        fact = answer["fact"]
        assert fact["status"] == "verified"
        assert fact["reporting_period"]["fiscal_year"] == year
        assert fact["reporting_period"]["end"] == expected["reporting_period_end"]
        for field in ("filing_date", "currency", "scale", "raw_amount", "normalized_amount"):
            assert fact[field] == expected[field]
        assert answer["citations"][0]["source_hash"] == expected["source_hash"]
        assert answer["citations"][0]["locator"] == expected["cell"]
        validation = json.loads(record.read_bytes())
        assert len(validation["ranked_candidates"]) == 6
        assert validation["selected_evidence_ids"] == [fact["fact_id"]]
        print(f'FY{year} USD {fact["raw_amount"]} million, HTML line {expected["cell"]["line"]}. CLI replay matched.')

    files = set(work.rglob("*"))
    before = (store / "sources.sqlite3").read_bytes()
    for question in ("FY2022 revenue", "Microsoft revenue", "Microsoft FY2022 and FY2023 revenue",
                     "Microsoft FY2022 segment revenue", "Microsoft FY2023 revenue guidance"):
        assert invoke("ask-collection", question)["status"] == "clarify"
    assert invoke("ask-collection", "Microsoft FY2021 revenue")["status"] == "evidence_unavailable"
    assert invoke("ask-collection", "Synthetic Example FY2023 revenue")["status"] == "evidence_unavailable"
    assert set(work.rglob("*")) == files
    assert (store / "sources.sqlite3").read_bytes() == before
    print("Clarification and unsupported cases passed. Ordinary questions left the store unchanged.")


def smoke_browser(work: Path) -> None:
    from os import environ

    from playwright.sync_api import expect, sync_playwright
    from werkzeug.serving import make_server

    from frag.store import SourceStore
    from frag.web import create_app

    assets = ROOT / "web/dist"
    assert (assets / "index.html").is_file(), "Run npm.cmd --prefix web run build first."
    app = create_app(SourceStore(work / "store"), assets)
    manifest = json.loads(MANIFEST.read_bytes())
    with make_server("127.0.0.1", 0, app) as server:
        origin = f"http://127.0.0.1:{server.port}"
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    channel=environ.get("FRAG_BROWSER", "chrome"), args=["--disable-background-networking"],
                )
                try:
                    context = browser.new_context(service_workers="block")
                    context.route("**/*", lambda route: route.continue_()
                                  if route.request.url.startswith(origin + "/") else route.abort())
                    page = context.new_page()
                    page.goto(origin)
                    search = page.get_by_role("region", name="Ask the collection")
                    question = search.get_by_role("textbox")
                    submit = search.get_by_role("button", name="Search collection")
                    for expected in manifest["expected_answers"]:
                        year = expected["fiscal_year"]
                        question.fill(expected["question"])
                        submit.click()
                        amount = f'{int(expected["normalized_amount"]):,}'
                        expect(search.get_by_text(f"USD {amount}", exact=True)).to_be_visible()
                        with context.expect_page() as new_page:
                            search.get_by_role("link", name=f"FY{year} Total revenue cell").click()
                        excerpt = new_page.value
                        try:
                            assert excerpt.url.startswith(origin + "/api/collection/citations/")
                            body = excerpt.locator("body")
                            expect(body).to_contain_text(expected["source_hash"])
                            expect(body).to_contain_text(f'HTML line {expected["cell"]["line"]}')
                            assert body.inner_text().splitlines()[-4:] == [
                                "Total revenue", str(year), "(In millions, except per share amounts)",
                                expected["raw_amount"],
                            ]
                        finally:
                            excerpt.close()
                finally:
                    browser.close()
        finally:
            server.shutdown()
            thread.join()
    print("Offline browser smoke passed for both exact original revenue cells.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, help="Keep the store and validation records in this new directory.")
    parser.add_argument("--browser", action="store_true", help="Open the original cells using Chromium and Playwright.")
    args = parser.parse_args()
    sys.addaudithook(audit_network)

    def validate(work: Path) -> None:
        replay(work)
        if args.browser:
            smoke_browser(work)

    if args.work_dir:
        args.work_dir.mkdir(parents=True)
        validate(args.work_dir.resolve())
    else:
        with TemporaryDirectory() as temporary:
            validate(Path(temporary))


if __name__ == "__main__":
    main()
