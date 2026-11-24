"""Check collection lookup and its original citations on a frozen development store."""

import argparse
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phase04"))

from sec_holdout_runner import ROOT, command, read_json, restrict_runner, write_json
from frag.store import SourceStore
from frag.web import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("store", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    restrict_runner(replay=True)
    freeze = read_json(ROOT / "freeze.json")
    manifest = read_json(ROOT / "artifacts/phase05/inputs.json")
    filings = {filing["source_id"]: filing for filing in manifest["sources"]}
    client = create_app(SourceStore(args.store), ROOT / "web/dist").test_client()
    rows: list[dict[str, Any]] = []
    for case in manifest["cases"]:
        if not case["case_id"].endswith("-lookup"):
            continue
        issuer = filings[case["source_id"]]["issuer"].rstrip(".")
        question = case["question"].replace("revenue", f"{issuer} revenue")
        record_path = args.output.with_name(f'{args.output.stem}-{case["case_id"]}.json')
        row: dict[str, Any] = {"case_id": case["case_id"], "question": question}
        try:
            result = command("ask-collection", question, "--store", str(args.store), "--record", str(record_path))
        except KeyError as exc:
            if exc.args != ("interpretation",):
                raise
            # Issue #28 indexed reviewed-note commentary as a required field.
            row["cli_error"] = "KeyError: interpretation"
        else:
            response = client.post("/api/collection/lookup", json={"question": question}, headers={"X-Frag-Ask": "1"})
            record = read_json(record_path)
            citations = {}
            for citation in result.get("citations", []):
                opened = client.get(citation["href"])
                citations[citation["id"]] = {"http_status": opened.status_code, "text": opened.text}
            row.update(
                result=result, record=record,
                browser_matches=response.status_code == 200 and response.get_json() == result,
                replay_matches=command("replay-collection", str(record_path), "--store", str(args.store)) == result,
                citations=citations,
            )
        rows.append(row)
    write_json(args.output, {"production_commit": freeze["production_commit"], "mode": "one-pass", "cases": rows})


if __name__ == "__main__":
    main()
