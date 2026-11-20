"""Independent reference checks through the public ingest and inspect commands."""

import gzip
import json
from pathlib import Path
from typing import Any

import pytest

from test_source_workflow import success

ARCHIVE = Path(__file__).parents[1] / "artifacts/phase01/originals/msft-20230630.htm.gz"


@pytest.fixture(scope="module")
def original() -> bytes:
    return gzip.decompress(ARCHIVE.read_bytes())


def inspect_bytes(tmp_path: Path, data: bytes, provenance: str, *metadata: str) -> dict[str, Any]:
    path = tmp_path / "input.html"
    path.write_bytes(data)
    store = str(tmp_path / "store")
    args = ("ingest", str(path), "--store", store, "--provenance", provenance, *metadata)
    result = success(*args)
    assert result == success(*args)
    path.unlink()
    assert result == success("inspect", result["source_id"], "--store", store)
    assert success("inspect", "--store", store) == {"source_count": 1, "sources": [result]}
    assert Path(result["original_path"]).read_bytes() == data
    return result


def test_preserved_microsoft_observations_match_independent_evidence(
    tmp_path: Path, original: bytes,
) -> None:
    result = inspect_bytes(tmp_path, original, "local_original", "--filing-date", "2023-07-27")
    older, current = result["facts"]
    assert [f["status"] for f in (older, current)] == ["verified", "verified"]
    assert [f["normalized_amount"] for f in (older, current)] == ["198270000000", "211915000000"]
    assert [f["locators"]["value"]["line"] for f in (older, current)] == [4403, 4399]
    assert {note["number"] for note in current["applicable_notes"]} == {1, 8, 13, 19}
    assert current["applicable_notes"][0]["locator"]["end_exclusive"]["line"] == 7608
    assert result["comparison"]["status"] == "compatible"
    assert result["real_source_acceptance"] is True
    manifest = json.loads((ARCHIVE.parents[1] / "source-manifest.json").read_bytes())
    recorded_facts = json.loads((ARCHIVE.parents[1] / manifest["facts"]).read_bytes())
    assert manifest["source_id"] == result["source_id"]
    assert manifest["source_hash"] == result["source_hash"]
    assert manifest["parser_version"] == result["parser_version"]
    assert manifest["evidence_version"] == result["evidence_version"]
    assert recorded_facts["source"]["facts"] == result["facts"]
    assert recorded_facts["source"]["comparison"] == result["comparison"]


@pytest.mark.parametrize(("before", "after", "requirement"), [
    (b"NOTE 2 ", b"XXXX 2 ", "note_1_boundary_or_content"),
    (b"REPORT OF INDEPENDENT REGIST", b"XXXXXX OF INDEPENDENT REGIST",
     "note_19_boundary_or_content"),
])
def test_uncertain_note_boundaries_prevent_verification(
    tmp_path: Path, original: bytes, before: bytes, after: bytes, requirement: str,
) -> None:
    lines = original.split(b"\n")
    index = 7607 if requirement.startswith("note_1_") else 21845
    assert before in lines[index]
    lines[index] = lines[index].replace(before, after)
    result = inspect_bytes(tmp_path, b"\n".join(lines), "synthetic")
    assert len(result["facts"]) == 2
    for fact in result["facts"]:
        assert fact["status"] == "provisional"
        assert requirement in fact["unresolved_requirements"]
    assert result["comparison"]["status"] == "unresolved"
    assert not result["real_source_acceptance"]


def test_equal_digits_with_wrong_context_leave_only_the_current_reference_match(
    tmp_path: Path, original: bytes,
) -> None:
    lines = original.split(b"\n")
    assert b"198,270" in lines[4402]
    lines[4402] = lines[4402].replace(
        b"C_efe853fc-8e8a-4899-b65b-e33c17faff7c", b"C_da7a1266-ce2b-41b7-83ff-bb6e03dc1fa5",
    )
    result = inspect_bytes(tmp_path, b"\n".join(lines), "synthetic")
    assert [(f["reporting_period"]["fiscal_year"], f["reference_status"]) for f in result["facts"]] == [
        (2023, "matched"),
    ]
    assert result["facts"][0]["status"] == "provisional"
    assert result["diagnostics"][0]["fiscal_year"] == 2022
    assert result["comparison"]["status"] == "unresolved"
    assert not result["real_source_acceptance"]


def test_provisional_comparative_does_not_hide_current_reference_match(
    tmp_path: Path, original: bytes,
) -> None:
    lines = original.split(b"\n")
    assert b"198,270" in lines[4402]
    lines[4402] = lines[4402].replace(b"198,270", b"198,271")
    result = inspect_bytes(tmp_path, b"\n".join(lines), "synthetic")
    older, current = result["facts"]
    assert older["raw_amount"] == "198,271"
    assert older["status"] == "provisional"
    assert "reference_locator:value" in older["unresolved_requirements"]
    assert current["reference_status"] == "matched"
    assert current["status"] == "provisional"
    assert result["comparison"]["status"] == "unresolved"
    assert not result["real_source_acceptance"]


def test_unresolved_comparison_keeps_both_supported_observations_available(
    tmp_path: Path, original: bytes,
) -> None:
    lines = original.split(b"\n")
    assert b"We have recast certain prior period amounts" in lines[1909]
    lines[1909] = lines[1909].replace(b"We have recast", b"We considered recasting")
    result = inspect_bytes(tmp_path, b"\n".join(lines), "synthetic")
    assert [f["reference_status"] for f in result["facts"]] == ["matched", "matched"]
    comparison = result["comparison"]
    assert comparison["status"] == "unresolved"
    assert comparison["reference_status"] == "unresolved"
    assert comparison["basis"] is None
    assert comparison["unresolved_requirements"] == ["segment_recast", "original_filing"]
    assert not result["real_source_acceptance"]


def test_changed_local_original_cannot_reuse_the_reviewed_source_identity(
    tmp_path: Path, original: bytes,
) -> None:
    result = inspect_bytes(tmp_path, original + b"\n", "local_original")
    assert [f["status"] for f in result["facts"]] == ["provisional", "provisional"]
    assert "source_identity_verification" in result["unresolved_requirements"]
    assert not result["real_source_acceptance"]


def test_ambiguity_confined_to_fy2022_preserves_the_fy2023_reference_match(
    tmp_path: Path, original: bytes,
) -> None:
    lines = original.split(b"\n")
    assert b"&#160;" in lines[4401]
    lines[4401] = lines[4401].replace(b"&#160;", b"198,270")
    result = inspect_bytes(tmp_path, b"\n".join(lines), "synthetic")
    assert [(f["reporting_period"]["fiscal_year"], f["reference_status"]) for f in result["facts"]] == [
        (2023, "matched"),
    ]
    assert "Multiple revenue cells" in result["diagnostics"][0]["message"]
    assert result["comparison"]["status"] == "unresolved"


def test_synthetic_input_can_match_a_reference_without_publishing_verified_facts(
    tmp_path: Path, original: bytes,
) -> None:
    result = inspect_bytes(tmp_path, original, "synthetic")
    assert [f["reference_status"] for f in result["facts"]] == ["matched", "matched"]
    assert [f["status"] for f in result["facts"]] == ["provisional", "provisional"]
    assert result["comparison"]["reference_status"] == "compatible"
    assert result["comparison"]["status"] == "unresolved"
    assert not result["real_source_acceptance"]


def test_conflicting_synthetic_company_prevents_reference_matches(
    tmp_path: Path, original: bytes,
) -> None:
    result = inspect_bytes(tmp_path, original, "synthetic", "--company", "Different Company")
    for fact in result["facts"]:
        assert fact["status"] == "provisional"
        assert fact["reference_status"] == "unresolved"
        assert "supplied_company_conflict" in fact["unresolved_requirements"]


def test_conflicting_cover_cik_prevents_reference_matches(tmp_path: Path, original: bytes) -> None:
    lines = original.split(b"\n")
    cik_fact = b">0000789019</ix:nonNumeric>"
    assert cik_fact in lines[7]
    lines[7] = lines[7].replace(cik_fact, b">0000123456</ix:nonNumeric>", 1)
    result = inspect_bytes(tmp_path, b"\n".join(lines), "synthetic")
    assert [fact["status"] for fact in result["facts"]] == ["provisional", "provisional"]
    for fact in result["facts"]:
        assert fact["reference_status"] == "unresolved"
        assert "reference_filing_cover" in fact["unresolved_requirements"]
