"""Replay the public CLI with socket operations forbidden, using synthetic input."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
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


def main() -> None:
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


if __name__ == "__main__":
    main()
