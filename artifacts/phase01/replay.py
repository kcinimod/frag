"""Replay the public CLI with socket operations forbidden."""

import argparse
import gzip
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PHASE = ROOT / "artifacts/phase01"
MICROSOFT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000095017023035122/msft-20230630.htm"
MIRROR_URL = "https://edgar-mirror.sec-api.io/789019/000095017023035122/msft-20230630.htm"
MICROSOFT_HASH = "6506060f3f928e31abcbcfe46792ff4e0ae5c60bd9ad40964933c37ac854a9ea"
CLI = """
import sys
def forbid_network(event, args):
    if event.startswith('socket.'):
        raise RuntimeError('network disabled for offline replay')
sys.addaudithook(forbid_network)
from frag.cli import main
raise SystemExit(main())
"""


def invoke(*args: str) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-c", CLI, *args], cwd=ROOT,
        capture_output=True, text=True, check=True,
    )
    record: dict[str, Any] = json.loads(result.stdout)
    return record


def replay_synthetic() -> None:
    store = str(ROOT / "artifacts/phase01/local-store")
    args = (
        "ingest", "tests/fixtures/synthetic.html", "--store", store,
        "--provenance", "synthetic", "--company", "Synthetic Example", "--form", "10-K",
    )
    first = invoke(*args)
    second = invoke(*args)
    inspected = invoke("inspect", first["source_id"], "--store", store)
    catalogue = invoke("inspect", "--store", store)
    assert first == second == inspected
    assert catalogue == {"source_count": 1, "sources": [first]}
    assert Path(inspected["original_path"]).read_bytes() == (ROOT / "tests/fixtures/synthetic.html").read_bytes()
    output = {
        "input_kind": "synthetic",
        "network_policy": "all socket audit events rejected in each CLI subprocess",
        "identical_reingest": True,
        "source_count": catalogue["source_count"],
        "source": inspected,
        "real_source_acceptance": False,
        "extraction_performed": False,
        "verification_performed": False,
    }
    (ROOT / "artifacts/phase01/source-manifest.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(output, indent=2))


def replay_microsoft() -> None:
    archive = PHASE / "originals/msft-20230630.htm.gz"
    original = gzip.decompress(archive.read_bytes())
    assert len(original) == 9963591
    assert hashlib.sha256(original).hexdigest() == MICROSOFT_HASH
    with TemporaryDirectory() as temp:
        input_path = Path(temp) / "msft-20230630.htm"
        input_path.write_bytes(original)
        store = str(Path(temp) / "store")
        args = (
            "ingest", str(input_path), "--store", store, "--provenance", "local_original",
            "--company", "Microsoft Corporation", "--accession", "0000950170-23-035122",
            "--form", "10-K", "--filing-date", "2023-07-27", "--source-url", MICROSOFT_URL,
        )
        first = invoke(*args)
        assert invoke(*args) == first
        input_path.unlink()
        inspected = invoke("inspect", first["source_id"], "--store", store)
        assert inspected == first
        assert Path(inspected.pop("original_path")).read_bytes() == original
    facts = inspected["facts"]
    assert [
        (fact["reporting_period"]["fiscal_year"], fact["raw_amount"], fact["normalized_amount"])
        for fact in facts
    ] == [(2022, "198,270", "198270000000"), (2023, "211,915", "211915000000")]
    assert not inspected["real_source_acceptance"] and not inspected["diagnostics"]
    assert all(fact["status"] == "provisional" for fact in facts)
    lines = original.decode("utf-8-sig").split("\n")
    for fact in facts:
        for key, expected in (
            ("year_header", str(fact["reporting_period"]["fiscal_year"])),
            ("value", fact["raw_amount"]),
        ):
            locator = fact["locators"][key]
            evidence = lines[locator["line"] - 1][locator["character"] - 1:]
            assert evidence.startswith("<td") and expected in evidence
    # The archive path stands in for temporary local paths and timestamps.
    inspected["provenance"] = {
        "kind": inspected["provenance"]["kind"],
        "archive": archive.relative_to(ROOT).as_posix(), "retrieved_from": MIRROR_URL,
    }
    print(json.dumps({
        "network_policy": "all socket audit events rejected in each CLI subprocess",
        "identical_reingest": True,
        "source": inspected,
    }, indent=2, sort_keys=True))


def main() -> None:
    flags = argparse.ArgumentParser()
    flags.add_argument("--microsoft", action="store_true", help="Replay the retained Microsoft FY2023 10-K")
    if flags.parse_args().microsoft:
        replay_microsoft()
    else:
        replay_synthetic()


if __name__ == "__main__":
    main()
