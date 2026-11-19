"""Exercise the public CLI in fresh processes with socket access forbidden."""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic.html"
NETWORK_DISABLED_CLI = """
import sys
def forbid_network(event, args):
    if event.startswith('socket.'):
        raise RuntimeError('network disabled for this workflow')
sys.addaudithook(forbid_network)
from frag.cli import main
raise SystemExit(main())
"""


def invoke(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", NETWORK_DISABLED_CLI, *args],
        capture_output=True, text=True, check=False,
    )


def success(*args: str) -> dict[str, Any]:
    result = invoke(*args)
    assert result.returncode == 0, result.stderr
    record: dict[str, Any] = json.loads(result.stdout)
    return record


def test_preserve_and_inspect_synthetic_source_offline(tmp_path: Path) -> None:
    store = str(tmp_path / "store")
    ingested = success(
        "ingest", str(FIXTURE), "--store", store, "--provenance", "synthetic",
        "--company", "Synthetic Example", "--form", "10-K",
    )
    record = success("inspect", ingested["source_id"], "--store", store)
    assert record == ingested
    assert record["source_hash"] == hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert record["source_id"] == "sha256:" + record["source_hash"]
    assert Path(record["original_path"]).read_bytes() == FIXTURE.read_bytes()
    assert record["company"] == "Synthetic Example"
    assert record["form"] == "10-K"
    assert record["accession"] is None
    assert record["filing_date"] is None
    assert record["source_url"] is None
    assert record["parser_version"]
    assert record["provenance"]["kind"] == "synthetic"
    assert record["metadata_status"] == "supplied_unverified"
    assert record["status"] == "source_preserved"
    assert record["facts"] == []
    assert record["diagnostics"][0]["code"] == "unsupported_layout"
    assert record["real_source_acceptance"] is False


def test_retry_from_another_path_keeps_one_source_and_first_provenance(tmp_path: Path) -> None:
    store = str(tmp_path / "store")
    args = ("--store", store, "--provenance", "synthetic")
    first = success("ingest", str(FIXTURE), *args)
    copied_input = tmp_path / "renamed.html"
    copied_input.write_bytes(FIXTURE.read_bytes())
    assert success("ingest", str(copied_input), *args) == first
    assert success("inspect", "--store", store) == {"source_count": 1, "sources": [first]}


def test_supplied_identity_is_preserved_as_unverified(tmp_path: Path) -> None:
    # All identity fields are synthetic test claims, never real-source acceptance.
    record = success(
        "ingest", str(FIXTURE), "--store", str(tmp_path / "store"),
        "--provenance", "synthetic", "--company", "Synthetic Company",
        "--accession", "0000000000-23-000001", "--form", "10-K",
        "--filing-date", "2023-07-27", "--source-url", "https://example.invalid/synthetic.html",
    )
    assert record["company"] == "Synthetic Company"
    assert record["accession"] == "0000000000-23-000001"
    assert record["form"] == "10-K"
    assert record["filing_date"] == "2023-07-27"
    assert record["source_url"] == "https://example.invalid/synthetic.html"
    assert record["metadata_status"] == "supplied_unverified"
    assert record["real_source_acceptance"] is False


@pytest.mark.parametrize("changed_claim", [
    ("--provenance", "local_original"),
    ("--provenance", "synthetic", "--company", "A different company"),
])
def test_conflicting_claims_cannot_relabel_preserved_evidence(
    tmp_path: Path, changed_claim: tuple[str, ...],
) -> None:
    store = str(tmp_path / "store")
    first = success("ingest", str(FIXTURE), "--store", store, "--provenance", "synthetic")
    conflict = invoke("ingest", str(FIXTURE), "--store", store, *changed_claim)
    assert conflict.returncode == 1
    assert "different metadata or provenance" in json.loads(conflict.stderr)["error"]
    assert success("inspect", first["source_id"], "--store", store) == first


def test_byte_changes_create_distinct_sources_without_rewriting_originals(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.html"
    source.write_bytes(b"<html>SYNTHETIC\r\n\xff</html>")
    store = str(tmp_path / "store")
    args = ("--store", store, "--provenance", "synthetic")
    first = success("ingest", str(source), *args)
    source.write_bytes(b"<html>SYNTHETIC CHANGED</html>")
    second = success("ingest", str(source), *args)
    assert first["source_id"] != second["source_id"]
    assert Path(first["original_path"]).read_bytes() == b"<html>SYNTHETIC\r\n\xff</html>"
    assert success("inspect", "--store", store)["source_count"] == 2


def test_store_can_be_copied_and_inspected_after_input_is_removed(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.html"
    source.write_bytes(FIXTURE.read_bytes())
    store = tmp_path / "store"
    record = success("ingest", str(source), "--store", str(store), "--provenance", "synthetic")
    source.unlink()
    copied_store = tmp_path / "copied-store"
    shutil.copytree(store, copied_store)
    inspected = success("inspect", record["source_id"], "--store", str(copied_store))
    assert inspected["source_id"] == record["source_id"]
    assert Path(inspected["original_path"]).is_relative_to(copied_store)
    assert Path(inspected["original_path"]).read_bytes() == FIXTURE.read_bytes()


def test_inspection_reports_corrupted_original_instead_of_trusting_catalogue(tmp_path: Path) -> None:
    store = str(tmp_path / "store")
    record = success("ingest", str(FIXTURE), "--store", store, "--provenance", "synthetic")
    Path(record["original_path"]).write_bytes(b"corrupted")
    result = invoke("inspect", record["source_id"], "--store", store)
    assert result.returncode == 1
    assert "hash mismatch" in json.loads(result.stderr)["error"]


def test_unknown_store_inspection_is_read_only(tmp_path: Path) -> None:
    store = tmp_path / "missing"
    result = invoke("inspect", "--store", str(store))
    assert result.returncode == 1
    assert "Store does not exist" in json.loads(result.stderr)["error"]
    assert not store.exists()


@pytest.mark.parametrize("date_value", ["2023-02-29", "20230727", " "])
def test_invalid_metadata_is_rejected_before_preserving_input(tmp_path: Path, date_value: str) -> None:
    store = tmp_path / "store"
    result = invoke(
        "ingest", str(FIXTURE), "--store", str(store), "--provenance", "synthetic",
        "--filing-date", date_value,
    )
    assert result.returncode == 1
    assert "error" in json.loads(result.stderr)
    assert not store.exists()


def test_provenance_must_be_declared(tmp_path: Path) -> None:
    result = invoke("ingest", str(FIXTURE), "--store", str(tmp_path / "store"))
    assert result.returncode == 2
    assert "--provenance" in result.stderr


def test_declared_original_input_remains_unverified(tmp_path: Path) -> None:
    # Simulate a caller's original-input declaration; these bytes are still only
    # a synthetic test case and cannot establish real-source acceptance.
    store = str(tmp_path / "store")
    record = success(
        "ingest", str(FIXTURE), "--store", store, "--provenance", "local_original",
    )
    inspected = success("inspect", record["source_id"], "--store", store)
    assert inspected["provenance"]["kind"] == "local_original"
    assert inspected["metadata_status"] == "supplied_unverified"
    assert inspected["real_source_acceptance"] is False
    assert inspected["facts"] == []


@pytest.mark.parametrize("case", ["missing", "empty"])
def test_bad_input_reports_an_error_without_creating_store(tmp_path: Path, case: str) -> None:
    source = tmp_path / "input.html"
    if case == "empty":
        source.write_bytes(b"")
    store = tmp_path / "store"
    result = invoke("ingest", str(source), "--store", str(store), "--provenance", "synthetic")
    assert result.returncode == 1
    assert "error" in json.loads(result.stderr)
    assert not store.exists()


def test_unknown_source_reports_a_diagnostic(tmp_path: Path) -> None:
    store = str(tmp_path / "store")
    success("ingest", str(FIXTURE), "--store", store, "--provenance", "synthetic")
    result = invoke("inspect", "unknown-source", "--store", store)
    assert result.returncode == 1
    assert "Source not found" in json.loads(result.stderr)["error"]
