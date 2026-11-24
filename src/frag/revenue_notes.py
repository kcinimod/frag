"""Locate accounting-policy evidence for the reported consolidated revenue lookup."""

import re
from typing import Any

from frag.income_html import (
    ACCOUNTING_POLICIES_HEADING, BASIS_NOTE_HEADING, EvidenceText, StatementHTML, TextBlock, original_span,
)

NOTES_HEADING = "notes to consolidated financial statements"
NOTE_HEADING = re.compile(r"note\s+(\d+)\s*[.\-–—:]\s*\w", re.I)
CONSOLIDATION = re.compile(r"(?:principles|basis) of consolidation", re.I)
REVENUE = re.compile(r"revenue(?: recognition)?", re.I)
CONSOLIDATED_ACCOUNTS = re.compile(r"\bconsolidated financial statements(?: of [^.]+)? include the accounts\b", re.I)
ELIMINATIONS = re.compile(
    r"(?:^|\. )intercompany (?:balances|accounts) and transactions"
    r"(?: between consolidated entities)? (?:are|have been) eliminated\b", re.I,
)
NET_REVENUE = re.compile(
    r"\b(?:revenue (?:also )?excludes[^.]*\btaxes|net of sales taxes|taxes are excluded from revenues?)\b",
    re.I,
)
RECOGNITION = re.compile(r"\b(?:recogniz\w+|measured)\b", re.I)
REVENUE_TERMS = re.compile(r"\b(?:revenues?|net sales)\b", re.I)
BASIS_QUALIFICATION = re.compile(
    r"\b(?:restat\w*|recast\w*|different (?:accounting )?basis)\b", re.I,
)
UNRELIABLE_AMOUNT = re.compile(
    r"\b(?:pending correction|misstat\w*|until corrected|should not be (?:used|relied on)"
    r"|correction of an error)\b", re.I,
)
UNCHANGED_CONSOLIDATED_REVENUE = re.compile(
    r"\b(?:did not (?:affect|change)|had no effect on) (?:reported )?consolidated revenues?\b", re.I,
)


def accounting_policy_notes(
    document: StatementHTML, lines: list[str], *, after: tuple[int, int], includes_fees: bool,
) -> list[dict[str, Any]]:
    # Use the body of the notes after the statement, bounded by the next numbered note.
    blocks = [block for block in document.blocks if block.position > after]
    sections = [i for i, block in enumerate(blocks[:-1])
                if block.text.casefold() == NOTES_HEADING
                and re.match(r"note\s+1\b", blocks[i + 1].text, re.I)
                and "policies" in blocks[i + 1].text.casefold()]
    if len(sections) != 1:
        return []
    start = sections[0] + 2
    # A later disclosure may qualify the amounts or basis established by these policies.
    if _unresolved_revenue_basis(blocks[start:]):
        return []
    end = next((i for i in range(start, len(blocks)) if NOTE_HEADING.match(blocks[i].text)), None)
    if end is None:
        return []
    policy = blocks[start:end]
    consolidation = _unique_heading(policy, CONSOLIDATION)
    revenue = _unique_heading(policy, REVENUE)
    if consolidation is None or revenue is None:
        return []
    scope = policy[consolidation + 1].text
    if not (CONSOLIDATED_ACCOUNTS.search(scope) and ELIMINATIONS.search(scope)):
        return []

    scope_end, revenue_end = consolidation + 1, revenue + 1
    if includes_fees:
        scope_end += 1
        if (len(policy) <= max(scope_end, revenue + 4)
                or policy[revenue + 1].text.casefold() != "net sales"
                or policy[revenue + 3].text.casefold() != "membership fee revenue"
                or "membership and other income" not in policy[revenue + 4].text.casefold()
                or "fiscal year ending" not in policy[scope_end].text.casefold()):
            return []
        revenue_end = revenue + 4
    revenue_policy = " ".join(block.text for block in policy[revenue + 1:revenue_end + 1])
    if not (NET_REVENUE.search(revenue_policy) and RECOGNITION.search(revenue_policy)):
        return []
    # A following policy heading provides a visible boundary for the consolidation text.
    if len(policy) > scope_end + 1 and policy[scope_end + 1].text.casefold() == "use of estimates":
        scope_end += 1
    evidence = [
        _note(lines, "consolidation", policy[consolidation], policy[scope_end].end),
        _note(lines, "revenue", policy[revenue], policy[revenue_end].end),
    ]
    return [note for note in evidence if note is not None]


def dated_policy_notes(
    document: StatementHTML, lines: list[str], *, after: tuple[int, int], issuer: str,
) -> tuple[list[dict[str, Any]], dict[int, int]]:
    blocks = [block for block in document.blocks if block.position > after]
    basis = _unique_heading(blocks, BASIS_NOTE_HEADING)
    policies = _unique_heading(blocks, ACCOUNTING_POLICIES_HEADING)
    if basis is None or policies is None or basis >= policies or _unresolved_revenue_basis(blocks[basis:]):
        return [], {}
    scope = blocks[basis + 1].text
    accounts = re.search(r"\bour consolidated financial statements include the accounts of (.+?) and our\b",
                         scope, re.I)
    registered_name = " ".join(issuer.rstrip(".").casefold().split())
    short_name = re.sub(r"\s+(?:corporation|corp|incorporated|inc)$", "", registered_name)
    if (accounts is None or accounts[1].casefold() not in {registered_name, short_name}
            or not re.search(r"\bwe have eliminated intercompany accounts and transactions\b", scope, re.I)):
        return [], {}
    weeks: dict[int, int] = {}
    for years, duration in re.findall(
        r"\b(20\d{2}(?: and 20\d{2})?) (?:was|were) (?:a )?(52|53)-week fiscal years?\b", scope, re.I,
    ):
        for year in re.findall(r"\d{4}", years):
            if int(year) in weeks:
                return [], {}
            weeks[int(year)] = int(duration)
    policy = blocks[policies + 1:]
    revenue = _unique_heading(policy, REVENUE)
    if (revenue != 0 or len(policy) < 4
            or not re.search(r"\brecognize net product revenue\b.*\btransfer of control\b", policy[1].text, re.I)
            or not re.match(r"We measure revenue\b", policy[2].text, re.I)
            or not re.search(r"\bpayments to our customers through cooperative advertising programs\b",
                             policy[3].text, re.I)
            or not re.search(r"\breduction in revenue\b", policy[3].text, re.I)):
        return [], {}
    evidence = [
        _note(lines, "consolidation", blocks[basis], blocks[policies].position),
        _note(lines, "revenue", policy[0], policy[3].end, number=2),
    ]
    return [note for note in evidence if note is not None], weeks


def _unresolved_revenue_basis(blocks: list[TextBlock]) -> bool:
    return any(REVENUE_TERMS.search(sentence) and (
                   UNRELIABLE_AMOUNT.search(sentence)
                   or (BASIS_QUALIFICATION.search(sentence) and not UNCHANGED_CONSOLIDATED_REVENUE.search(sentence))
               )
               for block in blocks for sentence in re.split(r"(?<=[.!?])\s+", block.text))


def _unique_heading(blocks: list[TextBlock], pattern: re.Pattern[str]) -> int | None:
    matches = [i for i, block in enumerate(blocks[:-1]) if pattern.fullmatch(block.text)]
    return matches[0] if len(matches) == 1 else None


def _note(
    lines: list[str], topic: str, start: TextBlock, end: tuple[int, int] | None, *, number: int = 1,
) -> dict[str, Any] | None:
    if end is None:
        return None
    locator = {"start": start.locator(), "end_exclusive": EvidenceText(end).locator()}
    try:
        original_span(lines, locator["start"], locator["end_exclusive"])
    except ValueError:
        return None
    return {"number": number, "id": f"note-{number}-{topic}", "title": start.text, "locator": locator}
