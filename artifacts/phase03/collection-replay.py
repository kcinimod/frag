"""Reproduce the preserved collection through the public CLI and browser."""

import argparse
import gzip
import hashlib
import json
import sys
from collections.abc import Callable
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from time import perf_counter
from typing import Any
from unittest.mock import patch

from frag.cli import main as frag
from frag.revenue import extract_revenue
from frag.store import SourceMetadata, SourceStore
from frag.verification import inspect_revenue

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).with_name("corpus-manifest.json")
GROWTH_BASELINE = Path(__file__).with_name("growth-baseline")
GROWTH_QUESTION = "What was Microsoft's reported consolidated revenue growth from FY2022 to FY2023?"


def audit_network(event: str, args: tuple[Any, ...]) -> None:
    # The smoke server and browser may use loopback. External sockets are blocked.
    if event == "socket.connect":
        assert args[1][0] in {"127.0.0.1", "::1"}, "External socket blocked."
    if event in {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"}:
        assert args[0] in {"127.0.0.1", "::1", "localhost"}, "External DNS blocked."


def replay(
    work: Path, *, growth_baseline: Path | None = None, freeze: bool = False,
    bounded: bool = False, paired: bool = False,
) -> None:
    store = work / "store"
    manifest = json.loads(MANIFEST.read_bytes())

    def invoke(*args: str) -> dict[str, Any]:
        store_options = () if "--store" in args else ("--store", str(store))
        with redirect_stdout(StringIO()) as output:
            assert frag([*args, *store_options]) == 0
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
    if growth_baseline is not None:
        replay_growth(invoke, work, growth_baseline, freeze=freeze)
    if bounded:
        replay_bounded(invoke, work)
    if paired:
        from paired_comparison import compare

        compare(work, invoke, Path(__file__).resolve())


def replay_bounded(invoke: Callable[..., dict[str, Any]], work: Path) -> None:
    def run(case: str, question: str, *options: str) -> tuple[dict[str, Any], dict[str, Any]]:
        record = work / f"recovery-{case}.json"
        answer = invoke("ask-collection", question, "--record", str(record), *options)
        assert answer == invoke("replay-collection", str(record))
        print(f'{case}: {answer["status"]} ({answer["stop_reason"]}). Offline replay matched.')
        return answer, json.loads(record.read_bytes())

    window = ("--initial-fact-limit", "1")
    bounded = ("--mode", "bounded", *window)
    baseline, baseline_run = run("one-pass", GROWTH_QUESTION, *window)
    assert baseline["stop_reason"] == "missing_fiscal_year" and baseline["issues"][0]["fiscal_year"] == 2022
    assert [item["fact"]["raw_amount"] for item in baseline["observations"]] == ["211,915"]
    recovered, recovery_run = run("recovered", GROWTH_QUESTION, *bounded)
    assert recovered["snapshot_id"] == baseline["snapshot_id"]
    assert recovery_run["initial_evidence_ids"] == baseline_run["selected_evidence_ids"]
    assert recovered["stop_reason"] == "sufficient_evidence"
    assert recovered["percent"] == {"unit": "percent", "value": "6.88"}
    assert [citation["locator"]["line"] for citation in recovered["citations"][:2]] == [4403, 4399]
    assert [action["operation"] for action in recovery_run["actions"]] == ["search", "calculate"]

    missing, missing_run = run("missing", "How did Microsoft revenue change from FY2021 to FY2023?", *bounded)
    assert missing["stop_reason"] == "no_progress" and missing["issues"][0]["fiscal_year"] == 2021
    assert [item["fact"]["raw_amount"] for item in missing["observations"]] == ["211,915"]
    assert missing_run["actions"][0]["result"]["fact_ids"] == []

    for limit, options, calls in (("calls", ("--max-calls", "1"), 1), ("time", ("--max-seconds", "0"), 0)):
        partial, validation = run(limit, GROWTH_QUESTION, *bounded, *options)
        assert partial["stop_reason"] == "budget_exhausted" and partial["budget_limit"] == limit
        assert partial["percent"] is None and len(validation["actions"]) == calls


def replay_growth(
    invoke: Callable[..., dict[str, Any]], work: Path, baseline: Path, *, freeze: bool,
) -> None:
    if freeze:
        baseline.mkdir(parents=True)

    def run(
        case: str, question: str = GROWTH_QUESTION, *options: str, store_path: Path | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        saved = baseline / f"{case}.json"
        record = work / f"growth-{case}.json"
        started = perf_counter()
        store_options = ("--store", str(store_path)) if store_path else ()
        answer = invoke("ask-collection", question, "--record", str(record), *options, *store_options)
        ask_ms = (perf_counter() - started) * 1000
        validation: dict[str, Any] = json.loads(record.read_bytes())
        if freeze:
            with saved.open("x", encoding="utf-8", newline="\n") as output:
                json.dump(validation, output, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
                output.write("\n")
        saved_validation = json.loads(saved.read_bytes())
        if validation["search_version"] == saved_validation["search_version"]:
            assert validation == saved_validation
        started = perf_counter()
        assert saved_validation["outcome"] == invoke("replay-collection", str(saved), *store_options)
        replay_ms = (perf_counter() - started) * 1000
        print(f'{case}: {answer["status"]} ({answer["stop_reason"]}). '
              f'Offline record matched. Ask {ask_ms:.1f} ms, replay {replay_ms:.1f} ms.')
        return answer, validation

    # The real filing amounts, locators and caveats were inspected in Phase 1.
    complete, validation = run("complete-with-distractors")
    assert complete["percent"] == {"unit": "percent", "value": "6.88"}
    assert [operand["raw_amount"] for operand in complete["operands"]] == ["198,270", "211,915"]
    assert complete["trace"][0]["result"] == "13645000000"
    assert [item["locator"]["line"] for item in complete["citations"][:2]] == [4403, 4399]
    assert "note-8" in {item["id"] for item in validation["selected_context"]}
    assert complete["scope_caveats"]
    excluded = [candidate["exclusions"] for candidate in validation["ranked_candidates"]]
    assert any("different_company" in reasons for reasons in excluded)
    assert any("different_reporting_period" in reasons for reasons in excluded)
    assert any(reasons == ["unverified"] for reasons in excluded)

    partial, _ = run("missing-year", "How did Microsoft revenue change from FY2021 to FY2023?")
    assert partial["stop_reason"] == "missing_fiscal_year" and partial["percent"] is None
    assert [issue["fiscal_year"] for issue in partial["issues"]] == [2021]
    assert [item["fact"]["raw_amount"] for item in partial["observations"]] == ["211,915"]

    partial, validation = run("missing-context", GROWTH_QUESTION, "--context-limit", "2")
    assert partial["stop_reason"] == "missing_context" and partial["percent"] is None
    assert {item["kind"] for item in validation["selected_context"]} == {"fact"}
    assert "note-8" in partial["issues"][0]["requirements"]

    from frag.web import create_app

    for case, company, amounts, disclosure in (
        ("incompatible", "Synthetic Basis Example", ["10", "25"], "the prior year was not recast"),
        ("zero", "Synthetic Zero Example", ["0", "12"], "the same consolidated reporting basis"),
    ):
        fixture = ROOT / f"tests/fixtures/synthetic_growth_{case}.html"
        payload = fixture.read_bytes()
        # Apply a fixture-only verifier to separately preserved synthetic inputs.
        # Use a separate store so no fixture can enter the retained filing catalogue.
        fixture_store = work / f"synthetic-{case}-store"
        store = SourceStore(fixture_store)

        def verify_fixture(original: bytes, source: dict[str, Any]) -> dict[str, Any]:
            if original != payload:
                return inspect_revenue(original, source)
            result = extract_revenue(original, source | {"provenance": {"kind": "synthetic"}})
            facts = result["facts"]
            assert [fact["raw_amount"] for fact in facts] == amounts
            lines = original.decode("utf-8").splitlines()
            line = next(number for number, text in enumerate(lines, 1) if disclosure in text)
            locator = {"start": {"line": line, "character": 1},
                       "end_exclusive": {"line": line + 1, "character": 1}}
            version = f"synthetic-growth-verification-{case}-v1"
            for fact in facts:
                fact.update(status="verified", evidence_version=version, applicable_notes=[])
            if case == "incompatible":
                facts[0]["basis"] = "parent_company"
                facts[1]["basis"] = "consolidated_with_subsidiary"
            return result | {"evidence_version": version, "comparison": {
                "status": "compatible" if case == "zero" else "unresolved",
                "basis": "same_consolidated_basis" if case == "zero" else None,
                "evidence": [{"id": "note_1_reporting_basis", "locator": locator}],
                "unresolved_requirements": [] if case == "zero" else ["reporting_basis"],
                "scope_caveats": [],
            }}

        with patch("frag.store.inspect_revenue", verify_fixture):
            store.ingest_bytes(payload, provenance="local_original", metadata=SourceMetadata(company=company))
        answer, _ = run(f"synthetic-{case}", f"{company} revenue growth from FY2022 to FY2023",
                        store_path=fixture_store)
        client = create_app(store, work).test_client()
        citations = {item["id"]: item for item in answer["citations"]}
        assert disclosure in client.get(citations["note_1_reporting_basis"]["href"]).text
        assert answer["percent"] is None
        if case == "incompatible":
            assert answer["stop_reason"] == "incompatible"
            assert "reporting basis" in answer["issues"][0]["detail"]
            observed = sorted(answer["observations"], key=lambda item: item["fact"]["reporting_period"]["fiscal_year"])
            for item, amount in zip(observed, amounts, strict=True):
                assert client.get(item["citation"]["href"]).text.endswith(f"\n{amount}\n")
        else:
            assert answer["status"] == "undefined_zero_baseline"
            assert answer["absolute_change"] == {"currency": "USD", "value": "12000000"}
            assert [step["operation"] for step in answer["trace"]] == ["subtract"]
            assert client.get(citations["prior"]["href"]).text.endswith("\n0\n")
            assert client.get(citations["current"]["href"]).text.endswith("\n12\n")


def smoke_browser(work: Path, *, bounded: bool = False) -> None:
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
                    if bounded:
                        search.get_by_label("Retrieval mode").select_option("bounded")
                    for growth_question, expected_text in (
                        (GROWTH_QUESTION, ("6.88%",)),
                        ("How did Microsoft revenue change from FY2021 to FY2023?", (
                            "Selected evidence lacks verified FY2021 revenue.", "USD 211,915,000,000",
                        )),
                    ):
                        question.fill(growth_question)
                        submit.click()
                        for text in expected_text:
                            expect(search.get_by_text(text)).to_be_visible()
                        with context.expect_page() as new_page:
                            search.get_by_role("link", name="Note 8", exact=False).click()
                        disclosure = new_page.value
                        try:
                            expect(disclosure.locator("body")).to_contain_text("On March 4, 2022")
                        finally:
                            disclosure.close()
                finally:
                    browser.close()
        finally:
            server.shutdown()
            thread.join()
    print("Offline browser smoke passed for original revenue cells and disclosures in complete and partial results.")


def main() -> None:
    sys.addaudithook(audit_network)
    if sys.argv[1:2] == ["--comparison-worker"]:
        from paired_comparison import worker

        worker(sys.argv[2:])
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, help="Keep the store and validation records in this new directory.")
    parser.add_argument("--browser", action="store_true", help="Open the original cells using Chromium and Playwright.")
    parser.add_argument("--bounded", action="store_true", help="Save and replay bounded recovery validation records.")
    parser.add_argument("--paired", action="store_true", help="Measure both modes on the frozen Windows corpus.")
    growth = parser.add_mutually_exclusive_group()
    growth.add_argument("--growth", action="store_true", help="Check the retained one-pass growth baseline.")
    growth.add_argument("--freeze-growth", type=Path, help="Write growth baseline records to a new directory.")
    args = parser.parse_args()

    def validate(work: Path) -> None:
        replay(work, growth_baseline=GROWTH_BASELINE if args.growth else args.freeze_growth,
               freeze=args.freeze_growth is not None, bounded=args.bounded, paired=args.paired)
        if args.browser:
            smoke_browser(work, bounded=args.bounded)

    if args.work_dir:
        args.work_dir.mkdir(parents=True)
        validate(args.work_dir.resolve())
    else:
        with TemporaryDirectory() as temporary:
            validate(Path(temporary))


if __name__ == "__main__":
    main()
