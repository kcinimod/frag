"""Locate accounting-policy evidence for the reported consolidated revenue lookup."""

import re
from typing import Any

from frag.income_html import (
    ACCOUNTING_POLICIES_HEADING, BASIS_NOTE_HEADING, EvidenceText, StatementHTML, TextBlock, original_span,
)

NOTES_HEADING = "notes to consolidated financial statements"
NOTE_HEADING = re.compile(r"note\s+(\d+)(?:\s*[.\-–—:]\s*\w|$)", re.I)
CONSOLIDATION = re.compile(r"(?:principles|basis) of consolidation", re.I)
REVENUE = re.compile(r"revenue(?: recognition)?", re.I)
CONSOLIDATED_ACCOUNTS = re.compile(r"\bconsolidated financial statements(?: of [^.]+)? include the accounts\b", re.I)
ELIMINATIONS = re.compile(
    r"(?:^|\. )intercompany (?:balances|accounts) and transactions"
    r"(?: between consolidated entities)? (?:are|have been) eliminated\b", re.I,
)
NET_REVENUE = re.compile(
    r"\b(?:revenue (?:also )?excludes[^.]*\btaxes|net of sales (?:and other )?taxes|taxes are excluded from revenues?)\b",
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
EXPLICIT_REVENUE_YEAR = re.compile(
    r"^(?:(?:reported )?(?:consolidated )?(?:revenues?|net sales) for (?:fiscal(?: year)? |FY\s*)(20\d{2})\s"
    r"(?:was|were|is|are)\b|for (?:fiscal(?: year)? |FY\s*)(20\d{2}), see the consolidated revenue\b)", re.I,
)
RECAST_ASSURANCE = re.compile(
    r"^(?:this (?=did not|had no effect)|(?:this|the) (?:recast|restatement|reclassification)\b)", re.I,
)
AMOUNT_REFERENCE = re.compile(r"^(?:(?:the|this|that) (?:amount|figure)|it)\b", re.I)
COMPARISON_QUALIFICATION = re.compile(
    r"\bconsolidated (?:revenues?|net sales)\b[^.!?]*\b"
    r"(?:not (?:directly )?comparable|cannot be (?:directly )?compared)\b", re.I,
)
NUMBERED_BASIS = re.compile(r"1\.\s*Basis of Presentation", re.I)
NUMBERED_POLICIES = re.compile(r"2\.\s*Summary of Significant Accounting Policies", re.I)
NUMBERED_ACQUISITIONS = re.compile(r"(\d+)\.\s*Acquisitions", re.I)
NUMBERED_NOTE = re.compile(r"\d+\.\s*[A-Z]")
FISCAL_WEEK_COUNTS = re.compile(
    r"\b(fiscal 20\d{2}(?:(?:,\s*|\s+and\s+)(?:and\s+)?fiscal 20\d{2})*) "
    r"(?:was|were) (?:each |a )?(52|53)-week fiscal years?\b", re.I,
)


def comparison_disclosures(
    document: StatementHTML, lines: list[str], *, after: tuple[int, int], years: set[int],
) -> list[dict[str, Any]]:
    """Locate explicit qualifications of comparability for the selected annual periods."""
    disclosures: list[dict[str, Any]] = []
    for block in document.blocks:
        if block.position <= after:
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", block.text):
            if not COMPARISON_QUALIFICATION.search(sentence):
                continue
            mentioned_years = {int(year) for year in re.findall(r"\b(?:19|20)\d{2}\b", sentence)}
            if mentioned_years and years.isdisjoint(mentioned_years):
                continue
            locator = _disclosure_locator(lines, block, block.end)
            if locator:
                disclosures.append({
                    "id": f"comparison_qualification_{len(disclosures) + 1}",
                    "interpretation": "The disclosure qualifies the comparability of reported consolidated revenue.",
                    "locator": locator,
                })
            break
    return disclosures


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
    basis_gaps = _revenue_basis_gaps(blocks[start:])
    if basis_gaps is None or basis_gaps:
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
) -> tuple[list[dict[str, Any]], dict[int, int], set[int]]:
    blocks = [block for block in document.blocks if block.position > after]
    basis = _unique_heading(blocks, BASIS_NOTE_HEADING)
    policies = _unique_heading(blocks, ACCOUNTING_POLICIES_HEADING)
    if basis is None or policies is None or basis >= policies:
        return [], {}, set()
    qualified_years = _revenue_basis_gaps(blocks[basis:])
    if qualified_years is None:
        return [], {}, set()
    scope = blocks[basis + 1].text
    accounts = re.search(r"\bour consolidated financial statements include the accounts of (.+?) and our\b",
                         scope, re.I)
    registered_name = " ".join(issuer.rstrip(".").casefold().split())
    short_name = re.sub(r"\s+(?:corporation|corp|incorporated|inc)$", "", registered_name)
    if (accounts is None or accounts[1].casefold() not in {registered_name, short_name}
            or not re.search(r"\bwe have eliminated intercompany accounts and transactions\b", scope, re.I)):
        return [], {}, set()
    weeks: dict[int, int] = {}
    for years, duration in re.findall(
        r"\b(20\d{2}(?: and 20\d{2})?) (?:was|were) (?:a )?(52|53)-week fiscal years?\b", scope, re.I,
    ):
        for year in re.findall(r"\d{4}", years):
            if int(year) in weeks:
                return [], {}, set()
            weeks[int(year)] = int(duration)
    policy = blocks[policies + 1:]
    revenue = _unique_heading(policy, REVENUE)
    if (revenue != 0 or len(policy) < 4
            or not re.search(r"\brecognize net product revenue\b.*\btransfer of control\b", policy[1].text, re.I)
            or not re.match(r"We measure revenue\b", policy[2].text, re.I)
            or not re.search(r"\bpayments to our customers through cooperative advertising programs\b",
                             policy[3].text, re.I)
            or not re.search(r"\breduction in revenue\b", policy[3].text, re.I)):
        return [], {}, set()
    evidence = [
        _note(lines, "consolidation", blocks[basis], blocks[policies].position),
        _note(lines, "revenue", policy[0], policy[3].end, number=2),
    ]
    return [note for note in evidence if note is not None], weeks, qualified_years


def cross_section_policy_notes(
    document: StatementHTML, lines: list[str], *, after: tuple[int, int], years: set[int],
) -> tuple[list[dict[str, Any]], list[str], set[int]] | None:
    """Resolve policy evidence for split note titles and cross-referenced revenue notes."""
    blocks = [block for block in document.blocks if block.position > after]
    sections = [i for i, block in enumerate(blocks[:-1]) if block.text.casefold() == NOTES_HEADING
                and re.match(r"note 1\b", blocks[i + 1].text, re.I)]
    if not sections:
        return None
    if len(sections) != 1:
        return [], [], set()
    heading = sections[0] + 1
    split_title = blocks[heading].text.casefold() == "note 1"
    cross_referenced = re.fullmatch(
        r"note 1:\s*business and summary of significant accounting policies", blocks[heading].text, re.I,
    )
    if not split_title and not cross_referenced:
        return None
    qualified_years = _revenue_basis_gaps(blocks[heading:])
    if qualified_years is None:
        return [], [], set()
    end = next((i for i in range(heading + 1, len(blocks)) if NOTE_HEADING.match(blocks[i].text)), None)
    if end is None:
        return [], [], set()
    policy = blocks[heading + 1:end]
    if split_title:
        if not policy or policy[0].text.casefold() != "summary of significant accounting policies":
            return [], [], set()
        notes = _split_policy_note(lines, policy)
        return notes, [], qualified_years
    notes = _cross_referenced_revenue_notes(lines, policy, blocks[end:], years)
    return notes, ["Reported net operating revenues reflect bottling refranchising."] if notes else [], qualified_years


def _split_policy_note(lines: list[str], policy: list[TextBlock]) -> list[dict[str, Any]]:
    basis = _unique_heading(policy, re.compile(r"Basis of Presentation", re.I))
    revenue = _unique_heading(policy, REVENUE)
    if basis is None or revenue is None or revenue + 2 >= len(policy):
        return []
    scope, recognition, promotions = policy[basis + 1], policy[revenue + 1], policy[revenue + 2]
    if not (
        re.search(r"consolidated financial statements include the company and its controlled subsidiaries", scope.text, re.I)
        and re.search(r"intercompany transactions are eliminated", scope.text, re.I)
        and re.search(r"revenue is recognized .* when .* transfer\b", recognition.text, re.I)
        and NET_REVENUE.search(recognition.text)
        and re.search(r"sales are recorded net of trade promotion spending", promotions.text, re.I)
    ):
        return []
    return _complete_notes(
        _note(lines, "consolidation", policy[basis], scope.end),
        _note(lines, "revenue", policy[revenue], promotions.end),
    )


def _cross_referenced_revenue_notes(
    lines: list[str], policy: list[TextBlock], rest: list[TextBlock], years: set[int],
) -> list[dict[str, Any]]:
    consolidation = _unique_heading(policy, CONSOLIDATION)
    recognition = _unique_heading(policy, REVENUE)
    if consolidation is None or recognition is None or consolidation >= recognition:
        return []
    scope = policy[consolidation + 1:recognition]
    primary_beneficiary = [block for block in scope if re.search(
        r"for which we were determined to be the primary beneficiary\. As a result, we have consolidated", block.text, re.I,
    )]
    eliminations = [block for block in scope if re.search(
        r"we eliminate from our financial results all significant intercompany transactions", block.text, re.I,
    )]
    reference = re.search(r"\bRefer to Note (\d+)\.", policy[recognition + 1].text, re.I)
    if len(primary_beneficiary) != 1 or len(eliminations) != 1 or reference is None:
        return []
    revenue_number = int(reference[1])
    revenue = _unique_heading(rest, re.compile(rf"note {revenue_number}:\s*net operating revenues", re.I))
    changes = _unique_heading(rest, re.compile(r"NOTE 2:\s*ACQUISITIONS AND DIVESTITURES", re.I))
    if revenue is None or changes is None or changes >= revenue:
        return []
    changes_end = next(i for i in range(changes + 1, revenue + 1) if NOTE_HEADING.match(rest[i].text))
    revenue_end = next((i for i in range(revenue + 1, len(rest)) if NOTE_HEADING.match(rest[i].text)), len(rest))
    policies = [block for block in rest[revenue + 1:revenue_end] if re.match(
        r"Revenue is recognized when performance obligations .* are satisfied\.", block.text, re.I,
    ) and re.search(r"upon transfer of control .* revenue is recognized", block.text, re.I)]
    divestitures = [block for block in rest[changes + 1:changes_end] if re.search(
        r"\bcompany refranchised its bottling operations\b", block.text, re.I,
    ) and any(re.search(rf"\b{year}\b", block.text) for year in years)]
    if len(policies) != 1 or not divestitures:
        return []
    return _complete_notes(
        _note(lines, "consolidation", policy[consolidation], eliminations[0].end),
        _note(lines, "revenue", rest[revenue], policies[0].end, number=revenue_number),
        _note(lines, "refranchising", divestitures[0], divestitures[-1].end, number=2,
              title="Bottling refranchising"),
    )


def _complete_notes(*notes: dict[str, Any] | None) -> list[dict[str, Any]]:
    evidence = [note for note in notes if note is not None]
    return evidence if len(evidence) == len(notes) else []


def numbered_policy_notes(
    document: StatementHTML, lines: list[str], *, after: tuple[int, int],
) -> tuple[list[dict[str, Any]], dict[int, int], set[int]]:
    blocks = [block for block in document.blocks if block.position > after]
    basis = _unique_heading(blocks, NUMBERED_BASIS)
    policies = _unique_heading(blocks, NUMBERED_POLICIES)
    if basis is None or basis == 0 or policies is None or basis >= policies:
        return [], {}, set()
    qualified_years = _revenue_basis_gaps(blocks[basis:])
    scope = blocks[basis + 1].text
    if (qualified_years is None or blocks[basis - 1].text.casefold() != NOTES_HEADING
            or not re.search(r"consolidated financial statements include our accounts and those of our subsidiaries",
                             scope, re.I)
            or not re.search(r"\ball intercompany accounts and transactions have been eliminated\b", scope, re.I)):
        return [], {}, set()
    weeks: dict[int, int] = {}
    for years, duration in FISCAL_WEEK_COUNTS.findall(scope):
        for year in re.findall(r"20\d{2}", years):
            if int(year) in weeks:
                return [], {}, set()
            weeks[int(year)] = int(duration)

    policy = _numbered_note_body(blocks, policies)
    recognition = [
        (heading, paragraph) for heading, paragraph in zip(policy, policy[1:])
        if re.match(r"\([a-z]\)\s*Revenue Recognition\b", heading.text, re.I)
        and re.match(r"We recognize revenue upon transfer of control\b.*\bconsideration we expect to receive",
                     paragraph.text, re.I)
    ]
    if len(recognition) != 1:
        return [], {}, set()
    heading, paragraph = recognition[0]
    evidence = [
        _note(lines, "consolidation", blocks[basis], blocks[policies].position),
        _note(lines, "revenue", heading, paragraph.end, number=2),
    ]
    return [note for note in evidence if note is not None], weeks, qualified_years


def acquisition_revenue_notes(
    document: StatementHTML, lines: list[str], *, after: tuple[int, int], year: int,
) -> tuple[list[dict[str, Any]], list[str]] | None:
    """Gather acquisition evidence or report that relevant disclosures could not be resolved."""
    blocks = [block for block in document.blocks if block.position > after]
    headings = [(index, match) for index, block in enumerate(blocks)
                if (match := NUMBERED_ACQUISITIONS.fullmatch(block.text))]
    if not headings:
        return [], []
    if len(headings) != 1:
        return None
    acquisition, heading = headings[0]
    number = int(heading[1])
    evidence = []
    caveats = []
    relevant = False
    for block in _numbered_note_body(blocks, acquisition):
        if str(year) in block.text and re.search(r"\b(?:revenue|pro forma financial information)\b", block.text, re.I):
            relevant = True
        contribution = re.fullmatch(
            rf"Our Consolidated Statements of Operations for fiscal {year} includes? revenue of .+?"
            r" attributable to ([\w][\w .,&'-]*?) since the date of acquisition\.", block.text, re.I,
        )
        if contribution:
            note = _note(lines, "acquisition-revenue", block, block.end, number=number)
            if note:
                evidence.append(dict(note, title="Acquisition revenue in the consolidated statement"))
                caveats.append(f"FY{year} includes {contribution[1]} revenue from the acquisition date.")
        elif re.search(r"\bunaudited pro forma financial information\b.*\bas though the acquisition\b",
                       block.text, re.I) and re.search(
            rf"\bpro forma financial information for fiscal {year}\b", block.text, re.I,
        ):
            note = _note(lines, "pro-forma-revenue", block, block.end, number=number)
            if note:
                evidence.append(dict(note, title="Supplemental pro forma reporting basis"))
    if {note["id"] for note in evidence} == {
        f"note-{number}-acquisition-revenue", f"note-{number}-pro-forma-revenue",
    } and len(evidence) == 2:
        return evidence, [
            *caveats, f"Supplemental pro forma results use the combination period described in Note {number}.",
        ]
    return None if relevant else ([], [])


def _numbered_note_body(blocks: list[TextBlock], heading: int) -> list[TextBlock]:
    end = next((index for index in range(heading + 1, len(blocks)) if NUMBERED_NOTE.match(blocks[index].text)),
               len(blocks))
    return blocks[heading + 1:end]


def _revenue_basis_gaps(blocks: list[TextBlock]) -> set[int] | None:
    """Return explicitly qualified years, or None for a qualification of unclear scope."""
    qualified_years: set[int] = set()
    for block in blocks:
        sentences = re.split(r"(?<=[.!?])\s+", block.text)
        for sentence, following in zip(sentences, [*sentences[1:], ""], strict=True):
            if not REVENUE_TERMS.search(sentence):
                continue
            unreliable = UNRELIABLE_AMOUNT.search(sentence) or (
                AMOUNT_REFERENCE.match(following) and UNRELIABLE_AMOUNT.search(following)
            )
            qualified = BASIS_QUALIFICATION.search(sentence)
            assurance = UNCHANGED_CONSOLIDATED_REVENUE.search(sentence) or (
                RECAST_ASSURANCE.match(following) and UNCHANGED_CONSOLIDATED_REVENUE.search(following)
            )
            if unreliable or (qualified and not assurance):
                year = EXPLICIT_REVENUE_YEAR.match(sentence)
                if year is None:
                    return None
                qualified_years.add(int(year[1] or year[2]))
    return qualified_years


def _unique_heading(blocks: list[TextBlock], pattern: re.Pattern[str]) -> int | None:
    matches = [i for i, block in enumerate(blocks[:-1]) if pattern.fullmatch(block.text)]
    return matches[0] if len(matches) == 1 else None


def _note(
    lines: list[str], topic: str, start: TextBlock, end: tuple[int, int] | None, *,
    number: int = 1, title: str | None = None,
) -> dict[str, Any] | None:
    locator = _disclosure_locator(lines, start, end)
    if locator is None:
        return None
    return {"number": number, "id": f"note-{number}-{topic}", "title": title or start.text, "locator": locator}


def _disclosure_locator(
    lines: list[str], start: TextBlock, end: tuple[int, int] | None,
) -> dict[str, Any] | None:
    if end is None:
        return None
    locator = {"start": start.locator(), "end_exclusive": EvidenceText(end).locator()}
    try:
        original_span(lines, locator["start"], locator["end_exclusive"])
    except ValueError:
        return None
    return locator
