"""Synthetic local originals for the standalone revenue selection experiment."""

import json
from pathlib import Path

import pytest

from frag.revenue_model_selection import PROMPT_BYTE_LIMIT, SYSTEM_PROMPT, run_model_selection
from frag.revenue_selection import Selection, extract_selection, filing_inventory, run_rules

SYNTHETIC_SOURCE = {
    "filing_date": None, "company": None, "form": None,
    "source_url": None, "accession": None, "provenance": {"kind": "synthetic"},
}


def test_inventory_retains_visible_tables_before_shortlisting() -> None:
    original = (
        b'\xef\xbb\xbf<table hidden><tr><td>Hidden</td></tr></table>\n'
        b'<h2>Segment data</h2>\n'
        b'<table><tr><th rowspan="2">Region</th><th colspan="2">Years ended December 31</th></tr>\n'
        b'<tr><td>2024</td><td>2023</td></tr>\n'
        b'<tr><td>Retail<table><tr><td>Nested</td></tr></table></td><td>19</td><td>12</td></tr></table>\n'
        b'<table><tr><td>Navigation</td></tr></table>'
    )
    inventory = filing_inventory(original).record()
    assert [table["table_id"] for table in inventory] == ["table-2", "table-3", "table-4"]
    table = inventory[0]
    assert table["nearby"][-1] == {"text": "Segment data", "locator": {"line": 2, "character": 1}}
    assert table["rows"][1]["row_id"] == "table-2/row-2"
    assert table["rows"][1]["locator"] == {"line": 4, "character": 1}
    assert table["rows"][1]["cells"][0]["column"] == 2
    assert table["rows"][0]["cells"][0]["rowspan"] == "2"
    assert table["rows"][0]["cells"][1]["colspan"] == "2"
    assert table["rows"][2]["cells"][0]["text"] == "Retail"
    assert inventory[1]["rows"][0]["cells"][0]["text"] == "Nested"


@pytest.mark.parametrize("total_present", [True, False])
def test_rules_select_consolidated_total_or_report_missing_target(total_present: bool) -> None:
    original = b"""
    <h2>Segment results</h2>
    <table><tr><td>Net revenues</td><td>12</td><td>10</td></tr></table>
    <h2>Example Corporation</h2>
    <h2>Consolidated Statements of Income</h2>
    <table>
    <tr><td>Years Ended December 31,</td><td colspan="2">2024</td><td colspan="2">2023</td></tr>
    <tr><td>(In millions)</td></tr>
    <tr><td>Retail segment</td><td>$</td><td>12</td><td>$</td><td>10</td></tr>
    TOTAL
    <tr><td>Net income</td><td></td><td>7</td><td></td><td>6</td></tr>
    </table>
    """
    total = b"<tr><td>Net revenues</td><td>$</td><td>19</td><td>$</td><td>15</td></tr>"
    inventory = filing_inventory(original.replace(b"TOTAL", total if total_present else b""))
    result = run_rules(inventory, SYNTHETIC_SOURCE)
    if total_present:
        assert result["selected"] == {"table_id": "table-2", "row_id": "table-2/row-4"}
        assert [(fact["normalized_amount"], fact["status"]) for fact in result["observations"]] == [
            ("15000000", "provisional"), ("19000000", "provisional"),
        ]
        assert result["observations"][0]["source_id"] == f"sha256:{inventory.original_sha256}"
    else:
        assert result["selected"] is None
        assert result["stop"] == "no_candidate"
        assert result["observations"] == []
    segment = extract_selection(inventory, SYNTHETIC_SOURCE, Selection("table-1", "table-1/row-1"))
    assert segment["stop"] == "unsupported_scope"
    assert segment["observations"] == []


def test_rules_abstain_between_consolidated_statement_candidates() -> None:
    statement = b"""
    <h2>Consolidated Statements of Income</h2>
    <table><tr><td>LABEL</td><td>19</td><td>15</td></tr></table>
    """
    original = statement.replace(b"LABEL", b"Net revenues") + statement.replace(b"LABEL", b"Total revenue")
    result = run_rules(filing_inventory(original), SYNTHETIC_SOURCE)
    assert len(result["candidates"]) == 2
    assert result["selected"] is None
    assert result["stop"] == "ambiguous_candidates"


@pytest.mark.parametrize(("segment", "competing", "expected"), [
    (False, False, "table-1/row-2"),
    (True, False, None),
    (False, True, None),
])
def test_unfamiliar_label_requires_unique_consolidated_revenue_evidence(
    segment: bool, competing: bool, expected: str | None,
) -> None:
    dimension = '<xbrldi:explicitMember dimension="test:Segment">test:Retail</xbrldi:explicitMember>'
    contexts = "".join(
        f'<xbrli:context id="c{year}"><xbrli:entity>'
        '<xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>'
        f'{dimension if segment else ""}</xbrli:entity><xbrli:period>'
        f'<xbrli:startDate>{year}-01-01</xbrli:startDate><xbrli:endDate>{year}-12-31</xbrli:endDate>'
        '</xbrli:period></xbrli:context>'
        for year in (2024, 2023)
    )
    values = "".join(
        f'<td><ix:nonFraction name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax" '
        f'contextRef="c{year}" unitRef="usd">{amount}</ix:nonFraction></td>'
        for year, amount in [(2024, 19), (2023, 15)]
    )
    other = f"<tr><td>Other receipts</td>{values}</tr>" if competing else ""
    original = f"""
    <ix:nonNumeric name="dei:EntityCentralIndexKey">0000000001</ix:nonNumeric>
    {contexts}
    <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
    <h2>Consolidated Statements of Income</h2>
    <table>
    <tr><td>Years ended December 31</td><td>2024</td><td>2023</td></tr>
    <tr><td>Sales</td>{values}</tr>
    {other}
    </table>
    """
    result = run_rules(filing_inventory(original.encode()), SYNTHETIC_SOURCE)
    assert result["selected"] == ({"table_id": "table-1", "row_id": expected} if expected else None)
    if competing:
        assert result["stop"] == "ambiguous_candidates"


def test_shared_extractor_rejects_a_subtotal_in_the_selected_statement() -> None:
    inventory = filing_inventory(b"""
    <h2>Consolidated Statements of Income</h2>
    <table>
    <tr><td>Net sales</td><td>19</td><td>15</td></tr>
    <tr><td>Total revenues</td><td>22</td><td>17</td></tr>
    </table>
    """)
    result = extract_selection(inventory, SYNTHETIC_SOURCE, Selection("table-1", "table-1/row-1"))
    assert result["stop"] == "unsupported_scope"
    assert result["observations"] == []


def test_an_intervening_segment_heading_blocks_a_stale_statement_title() -> None:
    inventory = filing_inventory(b"""
    <h2>Consolidated Statements of Income</h2>
    <h2>Segment results</h2>
    <table>
    <tr><td>Years Ended December 31,</td><td colspan="2">2024</td><td colspan="2">2023</td></tr>
    <tr><td>(In millions)</td></tr>
    <tr><td>Net revenues</td><td>$</td><td>12</td><td>$</td><td>10</td></tr>
    </table>
    """)
    result = run_rules(inventory, SYNTHETIC_SOURCE)
    assert result["stop"] == "no_candidate"
    assert result["observations"] == []


def test_explicit_selection_can_extract_a_supported_label_outside_shortlisting() -> None:
    inventory = filing_inventory(b"""
    <h2>Consolidated Statements of Income</h2>
    <table>
    <tr><td>Years Ended December 31,</td><td colspan="2">2024</td><td colspan="2">2023</td></tr>
    <tr><td>(In millions)</td><td>$</td><td></td><td>$</td><td></td></tr>
    <tr><td>Total operating revenue</td><td></td><td>$ 22</td><td></td><td>$ 17</td></tr>
    </table>
    """)
    result = run_rules(inventory, SYNTHETIC_SOURCE)
    assert result["selected"] is None
    result = extract_selection(inventory, SYNTHETIC_SOURCE, Selection("table-1", "table-1/row-3"))
    assert [fact["normalized_amount"] for fact in result["observations"]] == ["17000000", "22000000"]


@pytest.mark.parametrize("conflicting", [False, True])
def test_external_annual_dates_align_to_fiscal_labels_and_inline_contexts(conflicting: bool) -> None:
    current_end = "2024-02-02" if conflicting else "2024-02-03"
    original = f"""
    <ix:nonNumeric name="dei:EntityCentralIndexKey">0000000001</ix:nonNumeric>
    <xbrli:context id="current"><xbrli:entity>
    <xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2023-01-29</xbrli:startDate><xbrli:endDate>{current_end}</xbrli:endDate></xbrli:period>
    </xbrli:context>
    <xbrli:context id="prior"><xbrli:entity>
    <xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2022-01-30</xbrli:startDate><xbrli:endDate>2023-01-28</xbrli:endDate></xbrli:period>
    </xbrli:context>
    <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
    <h2>Consolidated Statements of Income</h2>
    <p>Years Ended February 3, 2024 and January 28, 2023</p>
    <p>(In millions)</p>
    <table>
    <tr><td></td><td colspan="2">2023</td><td colspan="2">2022</td></tr>
    <tr><td></td><td colspan="2">(53 weeks)</td><td colspan="2">(52 weeks)</td></tr>
    <tr><td>Net revenue</td><td>$</td>
    <td><ix:nonFraction name="us-gaap:Revenues" contextRef="current" unitRef="usd"
    scale="6" format="ixt:num-dot-decimal">19</ix:nonFraction></td><td>$</td>
    <td><ix:nonFraction name="us-gaap:Revenues" contextRef="prior" unitRef="usd"
    scale="6" format="ixt:num-dot-decimal">15</ix:nonFraction></td></tr>
    </table>
    """
    result = extract_selection(filing_inventory(original.encode()), SYNTHETIC_SOURCE,
                               Selection("table-1", "table-1/row-3"))
    prior, current = result["observations"]
    assert prior["reporting_period"] == {
        "kind": "annual", "fiscal_year": 2022, "start": "2022-01-30", "end": "2023-01-28",
    }
    assert current["reporting_period"] == {
        "kind": "annual", "fiscal_year": 2023, "start": None if conflicting else "2023-01-29", "end": "2024-02-03",
    }
    assert current["normalized_amount"] == "19000000"
    assert current["locators"]["year_header"]["cell"] == 2
    assert current["locators"]["value"]["cell"] == 3
    assert "Years Ended February" in original.splitlines()[current["locators"]["annual_header"]["line"] - 1]
    if conflicting:
        assert result["stop"] == "extraction_gap"
        assert any("conflicts with the displayed fiscal year-end" in item["message"] for item in result["diagnostics"])


def test_bom_and_unicode_text_do_not_change_original_locator_conventions() -> None:
    inventory = filing_inventory("\ufeff<table><tr><td>\u2028</td></tr></table>\n<table></table>".encode())
    first, second = inventory.record()
    assert first["locator"] == {"table": 1, "line": 1, "character": 1}
    assert second["locator"] == {"table": 2, "line": 2, "character": 1}
    assert len(inventory.lines) == 2


def test_model_selection_uses_the_same_original_evidence_as_rules() -> None:
    inventory = filing_inventory(b"""
    <table><tr><td>Segment revenue</td><td>12</td><td>10</td></tr></table>
    <h2>Consolidated Statements of Income</h2>
    <table>
    <tr><td>Years Ended December 31,</td><td colspan="2">2024</td><td colspan="2">2023</td></tr>
    <tr><td>(In millions)</td></tr>
    <tr><td>Net revenues</td><td>$</td><td>19</td><td>$</td><td>15</td></tr>
    </table>
    """)

    def model(prompt: str, row_ids: tuple[str, ...]) -> str:
        assert "table-1/row-1" in prompt
        assert "table-2/row-3" in row_ids
        return '{"row_id":"table-2/row-3"}'

    result = run_model_selection(inventory, SYNTHETIC_SOURCE, model)
    assert result["selected"] == {"table_id": "table-2", "row_id": "table-2/row-3"}
    assert result["observations"] == run_rules(inventory, SYNTHETIC_SOURCE)["observations"]
    assert [fact["normalized_amount"] for fact in result["observations"]] == ["15000000", "19000000"]


def test_shortlisted_model_receives_totals_and_subtotals_but_uses_original_cells() -> None:
    fixture = Path(__file__).with_name("fixtures") / "revenue-selection-distractor.html"
    inventory = filing_inventory(fixture.read_bytes())

    def model(prompt: str, row_ids: tuple[str, ...]) -> str:
        assert row_ids == ("table-2/row-3", "table-2/row-4")
        assert "Total revenues | $ | 19 | $ | 15" in prompt
        return '{"row_id":"table-2/row-4"}'

    result = run_model_selection(inventory, SYNTHETIC_SOURCE, model, shortlist=True)
    assert result["shortlist"] == [
        {"table_id": "table-2", "row_id": "table-2/row-3"},
        {"table_id": "table-2", "row_id": "table-2/row-4"},
    ]
    assert [fact["normalized_amount"] for fact in result["observations"]] == ["15000000", "19000000"]
    assert result["observations"] == run_rules(inventory, SYNTHETIC_SOURCE)["observations"]


def test_empty_shortlist_abstains_without_calling_the_model() -> None:
    fixture = Path(__file__).with_name("fixtures") / "revenue-selection-absent.html"

    def model(prompt: str, row_ids: tuple[str, ...]) -> str:
        pytest.fail("An empty shortlist should not produce a model request.")

    result = run_model_selection(filing_inventory(fixture.read_bytes()), SYNTHETIC_SOURCE, model, shortlist=True)
    assert (result["shortlist"], result["selected"], result["stop"], result["observations"]) == (
        [], None, "no_candidate", [],
    )


@pytest.mark.parametrize(("response", "stop"), [
    ('{"row_id":null}', "model_abstained"),
    ('{"row_id":"table-2/row-1"}', "unsupported_scope"),
    ('{"row_id":"table-1/row-80"}', "invalid_response"),
    ('[["row_id",null]]', "invalid_response"),
    ('{"row_id":"table-1/row-3","row_id":null}', "invalid_response"),
])
def test_model_abstentions_invalid_ids_and_distractors_stop_differently(response: str, stop: str) -> None:
    fixture = Path(__file__).with_name("fixtures") / "revenue-selection-absent.html"
    result = run_model_selection(filing_inventory(fixture.read_bytes()), SYNTHETIC_SOURCE, lambda *_: response)
    assert result["stop"] == stop
    assert result["observations"] == []


def test_all_visible_rows_reach_the_model_and_cross_batch_nominations_are_compared() -> None:
    filler = b"<tr><td>" + ("\u20ac" * 1100).encode() + b"</td></tr>"
    original = (
        b"<table><tr><td>First nomination</td></tr>" + filler * 4 + b"</table>"
        b"<table><tr><td>Second nomination</td></tr></table><table></table>"
    )

    def model(prompt: str, row_ids: tuple[str, ...]) -> str:
        assert len(SYSTEM_PROMPT.encode()) + len(prompt.encode()) <= PROMPT_BYTE_LIMIT
        row = next((key for key in ("table-2/row-1", "table-1/row-1") if key in row_ids), None)
        return json.dumps({"row_id": row})

    result = run_model_selection(filing_inventory(original), SYNTHETIC_SOURCE, model)
    assert result["coverage"] == {"visible_tables": 3, "submitted_tables": 3, "visible_rows": 6, "submitted_rows": 6}
    assert result["batches"][-1]["stage"] == "comparison-1"
    assert result["batches"][-1]["row_ids"] == ["table-1/row-1", "table-2/row-1"]
    assert result["selected"] == {"table_id": "table-2", "row_id": "table-2/row-1"}
    assert result["observations"] == []


def test_a_failed_batch_prevents_accepting_a_nomination_from_another_batch() -> None:
    fixture = Path(__file__).with_name("fixtures") / "revenue-selection-distractor.html"
    original = fixture.read_bytes() + b"<table><tr><td>" + b"x" * 9000 + b"</td></tr></table>"

    def model(_: str, row_ids: tuple[str, ...]) -> str:
        if "table-2/row-4" in row_ids:
            return '{"row_id":"table-2/row-4"}'
        return "unparseable"

    result = run_model_selection(filing_inventory(original), SYNTHETIC_SOURCE, model)
    assert result["stop"] == "invalid_response"
    assert result["selected"] is None
    assert result["observations"] == []
    assert {batch["outcome"] for batch in result["batches"]} == {"selected", "invalid_response"}


def test_json_escaping_does_not_exceed_the_prompt_budget() -> None:
    original = (
        b"<h2>" + b"\x01" * 600 + b"</h2><table><tr><td>" + b"\x01" * 850 + b"</td></tr></table>"
    )

    def model(prompt: str, row_ids: tuple[str, ...]) -> str:
        assert row_ids == ("table-1/row-1",)
        assert len(SYSTEM_PROMPT.encode()) + len(prompt.encode()) <= PROMPT_BYTE_LIMIT
        return '{"row_id":null}'

    result = run_model_selection(filing_inventory(original), SYNTHETIC_SOURCE, model)
    assert result["stop"] == "model_abstained"
    assert result["coverage"]["submitted_rows"] == 1
