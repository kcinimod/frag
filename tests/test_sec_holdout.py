import gzip
from typing import Any
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "artifacts/phase04/sec_holdout_runner.py"


def test_holdout_runner_uses_public_workflow_for_development_evidence_gap(tmp_path: Path) -> None:
    original = tmp_path / "apple.html"
    original.write_bytes(gzip.decompress(
        (ROOT / "artifacts/phase04/development/originals/aapl-20230930.htm.gz").read_bytes()
    ))
    # Development control only. The missing year has no annual row in this original.
    program = """
import json
import runpy
import sys
from pathlib import Path
runner = runpy.run_path(sys.argv[1])
path = Path(sys.argv[2])
store = path.parent / ("replay-store" if sys.argv[3] == "replay" else "store")
filing = dict(issuer="Apple Inc.", accession="0000320193-23-000106", form="10-K",
              filing_date="2023-11-03",
              source_url="https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl-20230930.htm")
source = runner["ingest"](store, path, filing)
case = dict(case_id="development-gap", source_id=filing["accession"],
            question="How did revenue change from FY2020 to FY2023?")
saved = path.parent / "saved.json"
if sys.argv[3] == "replay":
    print(json.dumps(runner["replay_case"](store, case, source, json.loads(saved.read_text()))))
else:
    result = runner["ask_case"](store, case, source, saved)
    saved.write_text(json.dumps(result), encoding="utf-8")
    print(json.dumps(result))
"""
    def control(mode: str) -> dict[str, Any]:
        process = subprocess.run([sys.executable, "-c", program, str(RUNNER), str(original), mode],
                                 check=True, capture_output=True, text=True)
        result: dict[str, Any] = json.loads(process.stdout)
        return result

    live = control("run")
    assert live["result"]["status"] == "unavailable"
    assert live["result"]["percent"] is None
    assert any(issue["code"] == "absent" and issue["fiscal_year"] == 2020 for issue in live["result"]["issues"])
    assert live["record"]["model_request"] is None
    assert "383,285" in live["citations"]["current"]["text"]
    assert control("replay") == {"status": "matched"}
