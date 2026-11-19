"""Public ingest and inspect regressions for explicitly synthetic HTML."""

from pathlib import Path
from typing import Any

import pytest

from test_source_workflow import success

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_income.html"


def test_inspect_provisional_revenue_from_spanning_annual_headers(tmp_path: Path) -> None:
    store = str(tmp_path / "store")
    args = ("ingest", str(FIXTURE), "--store", store, "--provenance", "synthetic",
            "--filing-date", "2023-07-27")
    first = success(*args)
    assert first == success(*args)
    assert success("inspect", "--store", store) == {"source_count": 1, "sources": [first]}
    record = success("inspect", first["source_id"], "--store", store)
    assert record == first
    older, current = record["facts"]
    assert (older["raw_amount"], older["normalized_amount"]) == ("817", "817000000")
    assert (current["raw_amount"], current["normalized_amount"]) == ("963", "963000000")
    assert older["reporting_period"] == {
        "kind": "annual", "fiscal_year": 2022, "start": "2021-07-01", "end": "2022-06-30",
    }
    assert current["reporting_period"]["end"] == "2023-06-30"
    assert current["filing_date"] == "2023-07-27"
    assert older["fact_id"] != current["fact_id"]
    for fact in record["facts"]:
        assert fact["status"] == "provisional"
        assert fact["metric_label"] == "Total revenue"
        assert (fact["currency"], fact["scale"], fact["scope"]) == ("USD", 1000000, "consolidated")
        assert fact["source_id"] == record["source_id"]
        assert fact["parser_version"] == record["parser_version"]
    assert older["locators"]["value"] == {
        "table": 1, "row": 5, "cell": 3, "column": 3, "line": 10, "character": 39,
    }
    assert current["locators"]["year_header"]["column"] == 4


def inspect_perturbation(tmp_path: Path, html: str) -> dict[str, Any]:
    source = tmp_path / "synthetic-perturbation.html"
    source.write_text(html, encoding="utf-8")
    store = str(tmp_path / "store")
    ingested = success("ingest", str(source), "--store", store, "--provenance", "synthetic")
    return success("inspect", ingested["source_id"], "--store", store)


def test_reordered_rows_preserve_year_association_and_changed_source_is_distinct(tmp_path: Path) -> None:
    original = FIXTURE.read_text(encoding="utf-8")
    first = inspect_perturbation(tmp_path, original)
    lines = original.splitlines(keepends=True)
    lines[9], lines[10] = lines[10], lines[9]
    reordered = inspect_perturbation(tmp_path, "".join(lines))
    assert first["source_id"] != reordered["source_id"]
    assert first["parser_version"] == reordered["parser_version"]
    assert [fact["raw_amount"] for fact in reordered["facts"]] == ["817", "963"]
    assert reordered["facts"][0]["locators"]["value"]["row"] == 6


@pytest.mark.parametrize("symbol", ["", "—", "*", "€"])
def test_missing_or_unresolved_amount_stays_unknown(tmp_path: Path, symbol: str) -> None:
    html = FIXTURE.read_text(encoding="utf-8").replace(">817<", f">{symbol}<")
    record = inspect_perturbation(tmp_path, html)
    older, current = record["facts"]
    assert older["raw_amount"] == symbol
    assert older["normalized_amount"] is None
    assert current["normalized_amount"] == "963000000"
    assert record["diagnostics"][0]["fiscal_year"] == 2022


@pytest.mark.parametrize(("original", "changed"), [
    ('<th colspan="4">Year Ended', '<th colspan="5">Year Ended'),
    ('<td>817</td><td>$</td>', '<td colspan="2">817</td>'),
    ('<td>$</td><td>817</td>', ''),
    ('<th colspan="2">2023</th>', '<th colspan="2">2022</th>'),
    ('<tr><th colspan="2">2022</th><th colspan="2">2023</th></tr>',
     '<tr><th colspan="2">2023</th><th colspan="2">2022</th></tr>\n'
     '<tr><th colspan="2">2022</th><th colspan="2">2023</th></tr>'),
    ('<h2>Consolidated Income Statements</h2>', '<h2>Segment Income Statements</h2>'),
])
def test_ambiguous_or_unsupported_geometry_reports_a_diagnostic(
    tmp_path: Path, original: str, changed: str,
) -> None:
    html = FIXTURE.read_text(encoding="utf-8").replace(original, changed)
    record = inspect_perturbation(tmp_path, html)
    assert record["facts"] == []
    assert record["diagnostics"][0]["code"] == "unsupported_layout"


def test_inline_context_cannot_override_the_displayed_year(tmp_path: Path) -> None:
    original = FIXTURE.read_text(encoding="utf-8")
    html = original.replace("<h2>Consolidated", """
<xbrli:context id="wrong-year"><xbrli:entity>
<xbrli:identifier scheme="http://www.sec.gov/CIK">0000789019</xbrli:identifier>
</xbrli:entity><xbrli:period><xbrli:startDate>2022-07-01</xbrli:startDate>
<xbrli:endDate>2023-06-30</xbrli:endDate></xbrli:period></xbrli:context>
<h2>Consolidated""").replace(
        ">817<", '><ix:nonfraction contextref="wrong-year" scale="6" '
        'name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax">817</ix:nonfraction><',
    )
    record = inspect_perturbation(tmp_path, html)
    assert [fact["reporting_period"]["fiscal_year"] for fact in record["facts"]] == [2023]
    assert record["facts"][0]["status"] == "provisional"
    assert record["diagnostics"][0]["fiscal_year"] == 2022
    assert "context" in record["diagnostics"][0]["message"].lower()
