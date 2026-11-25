"""Exercise verified growth through the local CLI and browser API."""

import gzip
from decimal import localcontext
from pathlib import Path
from typing import Any

import pytest
from test_source_workflow import success
from test_verification_workflow import ARCHIVE
from werkzeug.test import Client

from frag.growth import calculate_growth
from frag.store import SourceStore
from frag.web import create_app


def test_retained_microsoft_growth_through_offline_cli(tmp_path: Path) -> None:
    filing = tmp_path / "filing.html"
    filing.write_bytes(gzip.decompress(ARCHIVE.read_bytes()))
    store = str(tmp_path / "store")
    source = success("ingest", str(filing), "--store", store, "--provenance", "local_original")
    filing.unlink()

    result = success("growth", source["source_id"], "2022", "2023", "--store", store)

    assert result["status"] == "calculated"
    assert result["percent"] == {"unit": "percent", "value": "6.88"}
    assert [operand["fact_id"] for operand in result["operands"]] == [
        fact["fact_id"] for fact in source["facts"]
    ]
    assert [operand["role"] for operand in result["operands"]] == ["prior", "current"]
    assert result["trace"][0]["result"] == "13645000000"
    assert result["source_hash"] == source["source_hash"]

    missing = success("growth", source["source_id"], "2021", "2023", "--store", store)
    assert missing["percent"] is None
    issue, = missing["issues"]
    assert (issue["code"], issue["role"], issue["fiscal_year"]) == ("unverified", "prior", 2021)
    assert "FY2021 revenue evidence gap" in issue["detail"]
    assert "The statement shows this year" in issue["detail"]
    assert missing["operands"][0]["fact_id"] == source["facts"][1]["fact_id"]
    assert missing["operands"][0]["status"] == "verified"


def test_browser_growth_api_resolves_only_published_citations(tmp_path: Path) -> None:
    store = SourceStore(tmp_path / "store")
    source = store.ingest_bytes(gzip.decompress(ARCHIVE.read_bytes()), provenance="local_original")
    client: Client = create_app(store, tmp_path).test_client()
    base = f'/api/sources/{source["source_id"]}/growth'
    query = "?prior=2022&current=2023"

    response = client.get(base + query)
    assert response.status_code == 200
    result = response.get_json()
    assert result == success("growth", source["source_id"], "2022", "2023", "--store", str(store.root))

    prior = client.get(base + "/citations/prior" + query)
    assert prior.mimetype == "text/plain"
    assert prior.text.endswith("Total revenue\n2022\n(In millions, except per share amounts)\n198,270\n")
    assert "HTML line 4403, character 5" in prior.text
    current = client.get(base + "/citations/current" + query)
    assert current.text.endswith("\n211,915\n")
    assert "HTML line 4399, character 5" in current.text
    note = client.get(base + "/citations/note-8" + query)
    assert "NOTE 8" in note.text
    assert "On March 4, 2022" in note.text
    assert "<div" not in note.text
    assert "HTML line 13913, character 1" in note.text
    assert client.get(base + "/citations/unknown" + query).status_code == 404
    assert client.get(base + "?prior=2023&current=2022").status_code == 400


def synthetic_verified_source() -> dict[str, Any]:
    """Supply verified statuses at the calculator boundary for synthetic evidence only."""
    source_id = "synthetic:calculator-evidence"
    facts = [
        {
            "source_id": source_id, "fact_id": f"synthetic:{year}",
            "metric": "reported_consolidated_revenue", "metric_label": "Total revenue",
            "reporting_period": {"kind": "annual", "fiscal_year": year},
            "status": "verified", "comparative": year == 2022,
            "currency": "USD", "scale": 1_000_000, "normalized_amount": amount,
            "locators": {"value": {"line": 1, "character": 1},
                         "metric_label": {}, "year_header": {}, "unit_header": {}},
            "applicable_notes": [],
        }
        for year, amount in ((2022, "0"), (2023, "12000000"))
    ]
    return {"source_id": source_id, "facts": facts, "comparison": {"status": "compatible"}}


def test_synthetic_verified_zero_baseline_yields_only_absolute_change() -> None:
    result = calculate_growth(synthetic_verified_source(), 2022, 2023)
    assert result["status"] == "undefined_zero_baseline"
    assert result["percent"] is None
    assert result["absolute_change"] == {"currency": "USD", "value": "12000000"}
    assert [step["operation"] for step in result["trace"]] == ["subtract"]


def test_synthetic_growth_is_independent_of_callers_decimal_context() -> None:
    source = synthetic_verified_source()
    source["facts"][0]["normalized_amount"] = "10000000"
    with localcontext() as context:
        context.prec = 3
        context.Emax = 5
        result = calculate_growth(source, 2022, 2023)
    assert result["percent"] == {"unit": "percent", "value": "20.00"}


@pytest.mark.parametrize("reason", ["missing", "unverified", "incompatible"])
def test_synthetic_unavailable_growth_preserves_verified_current_revenue(reason: str) -> None:
    source = synthetic_verified_source()
    if reason == "missing":
        source["facts"].pop(0)
    elif reason == "unverified":
        source["facts"][0]["status"] = "provisional"
    else:
        source["comparison"]["status"] = "unresolved"
        source["comparison"]["unresolved_requirements"] = ["segment_recast"]

    result = calculate_growth(source, 2022, 2023)

    assert result["status"] == "unavailable"
    assert result["percent"] is None and result["absolute_change"] is None
    assert [issue["code"] for issue in result["issues"]] == ["incompatible" if reason == "incompatible" else "unverified"]
    if reason == "incompatible":
        assert "segment recast" in result["issues"][0]["detail"]
    assert result["operands"][-1]["fact_id"] == "synthetic:2023"
    assert result["operands"][-1]["status"] == "verified"
