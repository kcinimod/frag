"""One-pass revenue retrieval over a content-addressed local catalogue view."""

import hashlib
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, replace
from time import perf_counter_ns
from typing import Any, Literal
from urllib.parse import quote

from frag import store as source_store
from frag.citations import citation_lines, citation_text, has_citable_amount, revenue_cell_citation
from frag.dated_revenue import ORIGINAL_EVIDENCE_PARSERS, legacy_comparison
from frag.dated_revenue import PARSER_VERSION as DATED_PARSER_VERSION
from frag.growth import calculate_growth, disclosure_citations, note_citation_id
from frag.lookup import METRIC, resolve_request
from frag.store import SourceError, SourceNotFound, SourceStore, StoreMissing

INDEX_VERSION = "collection-index-v2"
LEGACY_LOOKUP_VERSION = "annual-revenue-search-v1"
LOOKUP_SEARCH_VERSION = "annual-revenue-search-v2"
RECORD_VERSION = "collection-run-v1"
LEGACY_GROWTH_VERSION = "revenue-growth-search-v1"
LEGACY_BOUNDED_VERSION = "bounded-revenue-search-v1"
PREVIOUS_GROWTH_VERSION = "revenue-growth-search-v2"
PREVIOUS_BOUNDED_VERSION = "bounded-revenue-search-v2"
GROWTH_SEARCH_VERSION = "revenue-growth-search-v3"
GROWTH_CONTEXT_LIMIT = 16
BOUNDED_SEARCH_VERSION = "bounded-revenue-search-v3"
GROWTH_SEARCH_VERSIONS = (LEGACY_GROWTH_VERSION, PREVIOUS_GROWTH_VERSION, GROWTH_SEARCH_VERSION)
BOUNDED_SEARCH_VERSIONS = (LEGACY_BOUNDED_VERSION, PREVIOUS_BOUNDED_VERSION, BOUNDED_SEARCH_VERSION)
DEFAULT_MAX_CALLS = 4
DEFAULT_MAX_SECONDS = 1.0
LOOKUP_CLARIFICATION = "Ask for annual reported consolidated revenue for one fiscal year."
MICROSOFT = "microsoft corporation"
MICROSOFT_ALIASES = {"microsoft", "microsoft corp", "msft", "0000789019", "789019"}


def _fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _normalize_company_name(value: str) -> str:
    return " ".join(value.casefold().split()).removesuffix(".")


def _company_key(value: str) -> str:
    name = _normalize_company_name(value)
    return MICROSOFT if name in MICROSOFT_ALIASES else name


def _words(text: str) -> set[str]:
    return set(re.findall(r"[^\W_]+", text.casefold()))


def _source_identity(source: dict[str, Any]) -> dict[str, Any]:
    keys = ("source_id", "source_hash", "company", "accession", "form", "filing_date",
            "source_url", "parser_version", "evidence_version")
    return {key: source[key] for key in keys} | {"provenance": source["provenance"]["kind"]}


@dataclass(frozen=True)
class IndexedFact:
    fact: dict[str, Any]
    source: dict[str, Any]
    terms: set[str]

    @property
    def company(self) -> str:
        return _company_key(self.fact["company"] or self.source["company"] or "")

    @property
    def fingerprint(self) -> str:
        return _fingerprint({"fact": self.fact, "source": self.source})


@dataclass(frozen=True)
class CollectionIndex:
    manifest: dict[str, Any]
    companies: dict[str, str]
    facts: tuple[IndexedFact, ...]
    comparisons: dict[str, dict[str, Any]]
    store: SourceStore
    legacy_dated_comparison: bool = False

    @classmethod
    def build(
        cls, store: SourceStore, source_ids: set[str] | None = None, *, legacy_dated_comparison: bool = False,
        legacy_original_comparison: bool = False,
    ) -> "CollectionIndex":
        try:
            sources = store.inspect_sources(source_ids)
        except StoreMissing:
            if source_ids:
                raise
            sources = []
        companies: dict[str, str] = {}
        parents: dict[str, Any] = {}
        entries: dict[str, IndexedFact] = {}
        comparisons = {}
        inputs = []
        for source in sources:
            identity = _source_identity(source)
            if identity["source_id"] != "sha256:" + identity["source_hash"]:
                raise SourceError("Collection source identifier does not match its preserved hash.")
            inputs.append(identity | {"evidence_hash": _fingerprint(source["facts"])})
            parser = identity["parser_version"]
            legacy = ((legacy_dated_comparison and parser == DATED_PARSER_VERSION)
                      or (legacy_original_comparison and parser in ORIGINAL_EVIDENCE_PARSERS))
            comparison = legacy_comparison() if legacy else source["comparison"]
            comparisons[identity["source_id"]] = {
                "comparison": comparison,
                "fact_ids": comparison.get("fact_ids", [fact["fact_id"] for fact in source["facts"]]),
            }
            # A verified observation can supply the company when ingestion omitted metadata.
            names = [source["company"], *(fact["company"] for fact in source["facts"])]
            for name in filter(None, names):
                key = _company_key(name)
                display = "Microsoft Corporation" if key == MICROSOFT else name
                companies.setdefault(key, display)
            for fact in source["facts"]:
                locators = fact["locators"]
                table = locators["table"]
                parent_id = fact["parent_table_id"]
                if (fact["source_id"] != identity["source_id"]
                        or parent_id != f'{identity["source_id"]}#table-{table["table"]}'):
                    raise SourceError("Collection fact has an invalid source or parent reference.")
                parent = {
                    "source_id": identity["source_id"],
                    "table": table,
                    "statement_heading": locators["statement_heading"],
                    "annual_header": locators["annual_header"],
                    "unit_header": locators["unit_header"],
                }
                if parents.setdefault(parent_id, parent) != parent:
                    raise SourceError("Collection facts disagree on their parent table context.")
                terms = _words(" ".join((
                    fact["company"] or identity["company"] or "", "income statement",
                    fact["metric"], fact["scope"], fact["metric_label"], fact["basis"],
                    f'FY{fact["reporting_period"]["fiscal_year"]}',
                    *(note["title"] + " " + note.get("interpretation", "") for note in fact["applicable_notes"]),
                )))
                entry = IndexedFact(fact, identity, terms)
                existing = entries.setdefault(fact["fact_id"], entry)
                if existing != entry:
                    raise SourceError("Collection contains conflicting records for one fact identifier.")

        manifest = {
            "index_version": INDEX_VERSION,
            "extraction_version": source_store.RESULT_VERSION,
            "sources": inputs,
            "parents": parents,
            "fact_ids": sorted(entries),
            "comparison_hash": _fingerprint(comparisons),
        }
        return cls({"snapshot_id": "sha256:" + _fingerprint(manifest), **manifest},
                   companies, tuple(entries[key] for key in sorted(entries)), comparisons, store,
                   legacy_dated_comparison)


def _resolve(index: CollectionIndex, question: str) -> tuple[dict[str, Any] | None, str]:
    if len(question) > 300:
        return None, "Enter a question of 300 characters or fewer."
    aliases = {_normalize_company_name(name): key for key, name in index.companies.items()}
    if MICROSOFT in index.companies:
        aliases.update({name: MICROSOFT for name in MICROSOFT_ALIASES})
    if not aliases:
        return None, "Preserve a filing with a company name before searching the collection."
    normalized = " ".join(question.casefold().replace("\u2019", "'").split())
    alternatives = "|".join(re.escape(alias) for alias in sorted(aliases, key=lambda alias: (-len(alias), alias)))
    company_pattern = re.compile(
        rf"(?<!\w)(?:(?:for|of) )?(?:\(({alternatives})\)|({alternatives})\.?(?:'s)?)(?!\w)"
    )
    company_keys = {aliases[match[1] or match[2]] for match in company_pattern.finditer(normalized)}
    if len(company_keys) != 1:
        return None, "Name one company from the preserved collection."
    company_key = company_keys.pop()
    ordinary_question = re.sub(r"\s+([?.])$", r"\1", company_pattern.sub(" ", normalized).strip())
    request = resolve_request(ordinary_question)
    if request is None:
        return None, LOOKUP_CLARIFICATION + " For growth, name an earlier and a later fiscal year in order."
    return {**request, "company": index.companies[company_key], "company_key": company_key}, ""


def _ineligible(entry: IndexedFact) -> list[str]:
    fact = entry.fact
    exclusions = []
    if fact["metric"] != METRIC or fact["scope"] != "consolidated" or fact.get("value_kind", "actual") != "actual":
        exclusions.append("metric_or_scope")
    if fact["status"] != "verified" or entry.source["provenance"] == "synthetic":
        exclusions.append("unverified")
    locators = fact["locators"]
    if not has_citable_amount(fact) or not all(
        locators.get(key) for key in ("metric_label", "year_header", "unit_header")
    ):
        exclusions.append("incomplete_evidence")
    return exclusions


def _citation(entry: IndexedFact, item: dict[str, Any] | None = None) -> dict[str, Any]:
    source_id = entry.source["source_id"]
    fact_id = entry.fact["fact_id"]
    components = "/".join(quote(part, safe="") for part in (source_id, fact_id, entry.fingerprint))
    if item is None:
        item = revenue_cell_citation(entry.fact, "revenue")
    elif "context_locators" not in item:
        components += "/" + quote(item["id"], safe="") + "/" + _fingerprint(item)
    return {
        **item,
        "source_id": source_id,
        "source_hash": entry.source["source_hash"],
        "href": "/api/collection/citations/" + components,
    }


def _parent_citation(fact: dict[str, Any]) -> dict[str, Any]:
    locators = fact["locators"]
    return {
        "id": f'statement-table-{locators["table"]["table"]}',
        "title": "Consolidated income statement context",
        "locator": locators["table"],
        "table_locators": {key: locators[key] for key in ("statement_heading", "annual_header", "unit_header")},
    }


def collection_excerpt(
    store: SourceStore, source_id: str, fact_id: str, fingerprint: str,
    citation_id: str | None = None, citation_hash: str | None = None,
) -> str:
    source, original = store.inspect_with_original(source_id)
    identity = _source_identity(source)
    for fact in source["facts"]:
        entry = IndexedFact(fact, identity, set())
        if (fact["fact_id"] == fact_id and fact["source_id"] == source_id
                and fact["reporting_period"]["kind"] == "annual" and not _ineligible(entry)
                and entry.fingerprint == fingerprint):
            if citation_id is None:
                return citation_text(original, source["source_hash"], _citation(entry))
            comparison = source["comparison"]
            parent = _parent_citation(fact)
            item = (parent if citation_id == parent["id"]
                    else disclosure_citations([fact], comparison).get(citation_id))
            if item and _fingerprint(item) == citation_hash:
                return citation_text(original, source["source_hash"], item)
    raise SourceNotFound("The pinned revenue citation is unavailable in this store.")


def _observation_signature(entry: IndexedFact) -> str:
    return _fingerprint({key: entry.fact[key] for key in (
        "reporting_period", "normalized_amount", "currency", "basis",
    )})


@dataclass(frozen=True)
class SearchAction:
    snapshot_id: str
    company_key: str
    fiscal_year: int


@dataclass(frozen=True)
class SearchPairAction:
    snapshot_id: str
    company_key: str
    prior_year: int
    current_year: int


@dataclass(frozen=True)
class GetParentAction:
    snapshot_id: str
    fact_id: str
    parent_id: str


@dataclass(frozen=True)
class GetSourceAction:
    snapshot_id: str
    source_id: str
    fact_ids: tuple[str, ...]
    citation_ids: tuple[str, ...]


@dataclass(frozen=True)
class CalculateAction:
    snapshot_id: str
    source_id: str
    prior_year: int
    current_year: int
    fact_ids: tuple[str, ...]


@dataclass(frozen=True)
class RecoveryBudget:
    max_calls: int = DEFAULT_MAX_CALLS
    max_seconds: float = DEFAULT_MAX_SECONDS

    def __post_init__(self) -> None:
        if type(self.max_calls) is not int or self.max_calls < 0:
            raise SourceError("The bounded call limit must be a nonnegative integer.")
        if type(self.max_seconds) not in (int, float) or not 0 <= self.max_seconds < float("inf"):
            raise SourceError("The bounded time limit must be finite and nonnegative.")


class _PinnedCitations:
    def __init__(self, store: SourceStore, *, legacy_dated_comparison: bool = False) -> None:
        self.store = store
        self.original_lines: dict[str, list[str] | None] = {}
        self.legacy_dated_comparison = legacy_dated_comparison
        self.legacy_dated_sources: set[str] = set()

    def valid_ids(self, source_id: str, citations: dict[str, dict[str, Any]]) -> list[str]:
        if not citations:
            return []
        if source_id not in self.original_lines:
            self.original_lines[source_id] = None
            try:
                source, original = self.store.inspect_with_original(source_id)
                if source["source_id"] == source_id == "sha256:" + source["source_hash"]:
                    self.original_lines[source_id] = original.decode("utf-8-sig").split("\n")
                    if self.legacy_dated_comparison and source["parser_version"] == DATED_PARSER_VERSION:
                        self.legacy_dated_sources.add(source_id)
            except (SourceError, OSError, UnicodeError):
                pass
        lines = self.original_lines[source_id]
        if lines is None:
            return []
        valid = []
        for citation_id, citation in citations.items():
            if source_id in self.legacy_dated_sources and "table_locators" in citation:
                # The former heading reader rejected the archived one-line Apple statement.
                continue
            try:
                citation_lines(lines, source_id.removeprefix("sha256:"), citation)
            except (SourceError, KeyError, TypeError):
                continue
            valid.append(citation_id)
        return valid


class _GrowthActions:
    def __init__(
        self, index: CollectionIndex, request: dict[str, Any], eligible: list[IndexedFact],
        budget: RecoveryBudget, elapsed: Callable[[], int], citations: _PinnedCitations,
    ) -> None:
        self.index = index
        self.request = request
        self.eligible = {entry.fact["fact_id"]: entry for entry in eligible}
        self.budget = budget
        self.elapsed = elapsed
        self.actions: list[dict[str, Any]] = []
        self.elapsed_ns: list[int] = []
        self.limit: str | None = None
        self.context_stalled = False
        self.citations = citations

    def _within_time(self) -> bool:
        elapsed = self.elapsed()
        self.elapsed_ns.append(elapsed)
        if elapsed >= self.budget.max_seconds * 1_000_000_000:
            self.limit = "time"
        return self.limit is None

    def _start(self) -> bool:
        if len(self.actions) >= self.budget.max_calls:
            self.limit = "calls"
            return False
        return self._within_time()

    def _finish(
        self, operation: str,
        action: SearchAction | SearchPairAction | GetParentAction | GetSourceAction | CalculateAction,
        result: dict[str, Any],
    ) -> bool:
        accepted = self._within_time()
        self.actions.append({
            "operation": operation, "arguments": asdict(action),
            "result": result, "accepted": accepted,
        })
        return accepted

    def search(self, action: SearchAction, selected: list[IndexedFact]) -> list[IndexedFact]:
        selected_years = {entry.fact["reporting_period"]["fiscal_year"] for entry in selected}
        years = {self.request["prior_year"], self.request["current_year"]}
        if (action.snapshot_id != self.index.manifest["snapshot_id"]
                or action.company_key != self.request["company_key"]
                or action.fiscal_year not in years - selected_years):
            raise SourceError("The bounded search does not match the missing fiscal year in the pinned request.")
        if not self._start():
            return []
        matches = [
            entry for entry in self.eligible.values()
            if entry.fact["reporting_period"]["fiscal_year"] == action.fiscal_year
        ]
        accepted = self._finish("search", action, {"fact_ids": [entry.fact["fact_id"] for entry in matches]})
        return matches if accepted else []

    def search_pair(self, action: SearchPairAction) -> list[IndexedFact]:
        years = (action.prior_year, action.current_year)
        if (action.snapshot_id != self.index.manifest["snapshot_id"]
                or action.company_key != self.request["company_key"]
                or years != (self.request["prior_year"], self.request["current_year"])):
            raise SourceError("The pair search does not match the pinned request.")
        if not self._start():
            return []
        matches = []
        for source_id, entries in _facts_by_source(self.eligible.values()).items():
            verification = self.index.comparisons[source_id]
            if (verification["comparison"]["status"] == "compatible"
                    and {entry.fact["reporting_period"]["fiscal_year"] for entry in entries} == set(years)
                    and {entry.fact["fact_id"] for entry in entries} == set(verification["fact_ids"])):
                matches.extend(entries)
        accepted = self._finish("search", action, {"fact_ids": [entry.fact["fact_id"] for entry in matches]})
        return matches if accepted else []

    def get_parent(self, action: GetParentAction) -> bool:
        entry = self.eligible.get(action.fact_id)
        parent = self.index.manifest["parents"].get(action.parent_id)
        if (action.snapshot_id != self.index.manifest["snapshot_id"] or entry is None or parent is None
                or action.parent_id != entry.fact["parent_table_id"]
                or parent["source_id"] != entry.source["source_id"]):
            raise SourceError("The parent action does not match a table reference in the pinned request.")
        if not self._start():
            return False
        found = self.citations.valid_ids(parent["source_id"], {action.parent_id: _parent_citation(entry.fact)})
        accepted = self._finish("get_parent", action, {"context_ids": found})
        self.context_stalled = accepted and not found
        return accepted and bool(found)

    def get_source(self, action: GetSourceAction) -> list[str]:
        entries = [self.eligible[fact_id] for fact_id in action.fact_ids if fact_id in self.eligible]
        if (action.snapshot_id != self.index.manifest["snapshot_id"] or not entries
                or action.fact_ids != _calculation_ids([entry.fact for entry in entries])
                or any(entry.source["source_id"] != action.source_id for entry in entries)):
            raise SourceError("The source action does not match eligible facts in the pinned request.")
        citations = disclosure_citations([entry.fact for entry in entries],
                                         self.index.comparisons[action.source_id]["comparison"])
        if len(set(action.citation_ids)) != len(action.citation_ids) or not set(action.citation_ids) <= citations.keys():
            raise SourceError("The source action requires known disclosure references from the pinned source.")
        if not self._start():
            return []
        found = self.citations.valid_ids(action.source_id, {key: citations[key] for key in action.citation_ids})
        accepted = self._finish("get_source", action, {"context_ids": found})
        self.context_stalled = accepted and not found
        return found if accepted else []

    def calculate(
        self, action: CalculateAction, facts: list[dict[str, Any]], selected_comparison: dict[str, Any],
    ) -> dict[str, Any] | None:
        comparison = self.index.comparisons.get(action.source_id)
        operands = [self.eligible[fact_id] for fact_id in action.fact_ids if fact_id in self.eligible]
        if (action.snapshot_id != self.index.manifest["snapshot_id"]
                or (action.prior_year, action.current_year) != (self.request["prior_year"], self.request["current_year"])
                or {fact["reporting_period"]["fiscal_year"] for fact in facts} != {action.prior_year, action.current_year}
                or action.fact_ids != _calculation_ids(facts)
                or comparison is None or set(action.fact_ids) != set(comparison["fact_ids"])
                or any(entry.source["source_id"] != action.source_id for entry in operands)):
            raise SourceError("The bounded calculation does not match eligible evidence for the pinned request.")
        if not self._start():
            return None
        evidence = operands[0].source | {"facts": facts, "comparison": selected_comparison}
        growth = calculate_growth(evidence, action.prior_year, action.current_year)
        result = {key: growth[key] for key in ("status", "percent", "absolute_change", "trace", "issues")}
        return growth if self._finish("calculate", action, result) else None


def _calculation_ids(facts: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(fact["fact_id"] for fact in sorted(facts, key=lambda fact: (
        fact["reporting_period"]["fiscal_year"], fact["fact_id"],
    )))


def _facts_by_source(entries: Iterable[IndexedFact]) -> dict[str, list[IndexedFact]]:
    sources: dict[str, list[IndexedFact]] = {}
    for entry in entries:
        sources.setdefault(entry.source["source_id"], []).append(entry)
    return sources


def _recover_context(
    actions: _GrowthActions, entries: list[IndexedFact], missing: list[dict[str, Any]], space: int,
) -> list[dict[str, Any]]:
    if not space or not missing or actions.limit or actions.context_stalled:
        return []
    snapshot_id = actions.index.manifest["snapshot_id"]
    parents = {entry.fact["parent_table_id"]: entry for entry in entries}
    recovered: list[dict[str, Any]] = []
    for item in (item for item in missing if item["kind"] == "parent"):
        action = GetParentAction(snapshot_id, parents[item["id"]].fact["fact_id"], item["id"])
        if not actions.get_parent(action):
            return recovered
        recovered.append(item)
        if len(recovered) == space:
            return recovered
    references = [item for item in missing if item["kind"] in ("note", "disclosure")]
    if references:
        action_source = GetSourceAction(
            snapshot_id, entries[0].source["source_id"], _calculation_ids([operand.fact for operand in entries]),
            tuple(item["id"] for item in references),
        )
        found = actions.get_source(action_source)
        recovered.extend(item for item in references if item["id"] in found)
    if recovered:
        recovered.extend(item for item in missing if item["kind"] == "comparison")
    return recovered[:space]


def _answer_growth(
    index: CollectionIndex, request: dict[str, Any], selected: list[IndexedFact], context_limit: int,
    actions: _GrowthActions | None = None, *, initial_context_limit: int | None = None,
    citations: _PinnedCitations | None, retain_partial_context: bool,
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    prior, current = request["prior_year"], request["current_year"]
    fact_ids = [entry.fact["fact_id"] for entry in selected]
    context = [{"kind": "fact", "id": entry.fact["fact_id"], "source_id": entry.source["source_id"],
                "value": {key: value for key, value in entry.fact.items() if key != "applicable_notes"}}
               for entry in selected]
    observations = [{"fact": item["value"], "citation": _citation(entry)}
                    for entry, item in zip(selected, context, strict=True)]
    context_citations: list[dict[str, Any]] = []
    supported_comparisons: list[dict[str, Any]] = []
    sources = _facts_by_source(selected)

    issues = [
        {"code": "missing_fiscal_year", "fiscal_year": year,
         "detail": f"Selected evidence lacks verified FY{year} revenue."}
        for year in (prior, current)
        if not any(entry.fact["reporting_period"]["fiscal_year"] == year for entry in selected)
    ]
    partial = bool(issues)
    missing_years = {issue["fiscal_year"] for issue in issues}
    recover_partial = actions is not None and partial and not any(
        entry.fact["reporting_period"]["fiscal_year"] in missing_years
        for entry in actions.eligible.values()
    )
    calculations: list[tuple[str, dict[str, Any]]] = []
    deferred = False
    if not partial or retain_partial_context:
        def has_both_years(entries: list[IndexedFact]) -> bool:
            return {entry.fact["reporting_period"]["fiscal_year"] for entry in entries} == {prior, current}

        pairs = [entries for entries in sources.values() if has_both_years(entries)]
        if not pairs and not partial:
            issues.append({"code": "incompatible", "detail": "A verified pair from one filing is required."})
        for entries in sorted(sources.values(), key=lambda entries: not has_both_years(entries)):
            entry = entries[0]
            source_id = entry.source["source_id"]
            verification = index.comparisons[source_id]
            comparison = verification["comparison"]
            notes = {note_citation_id(note): note for operand in entries for note in operand.fact["applicable_notes"]}
            disclosures = {} if partial else {item["id"]: item for item in comparison.get("evidence", [])}
            comparison_context = {"kind": "comparison", "id": source_id, "source_id": source_id, "value": {
                key: value for key, value in comparison.items() if key != "evidence"
            } | {"fact_ids": verification["fact_ids"]}}
            required = [] if partial else [comparison_context]
            parent_owners = {operand.fact["parent_table_id"]: operand for operand in entries}
            if citations is not None:
                required.extend({"kind": "parent", "id": parent_id, "source_id": source_id,
                                 "value": index.manifest["parents"][parent_id]} for parent_id in parent_owners)
            required.extend(
                {"kind": kind, "id": key, "source_id": source_id, "value": value}
                for kind, items in (("note", notes), ("disclosure", disclosures)) for key, value in items.items()
            )
            first_limit = initial_context_limit if initial_context_limit is not None else context_limit
            offered = max(0, first_limit - len(context))
            retained = required[:offered]
            if citations is not None:
                pointers = disclosure_citations([operand.fact for operand in entries], comparison)
                pointers.update({key: _parent_citation(owner.fact) for key, owner in parent_owners.items()})
                valid = set(citations.valid_ids(source_id, {
                    item["id"]: pointers[item["id"]] for item in retained if item["kind"] != "comparison"
                }))
                retained = [item for item in retained if item["kind"] == "comparison" or item["id"] in valid]
            paired = has_both_years(entries)
            if actions and citations is not None and (paired or recover_partial):
                retained.extend(_recover_context(actions, entries, required[offered:],
                                                 context_limit - len(context) - len(retained)))
            context.extend(retained)
            retained_ids = {item["id"] for item in retained}
            facts = [
                operand.fact | {"applicable_notes": [
                    note for note in operand.fact["applicable_notes"] if note_citation_id(note) in retained_ids
                ]}
                for operand in entries
            ]
            selected_comparison = comparison_context["value"] | {"evidence": [
                item["value"] for item in retained if item["kind"] == "disclosure"
            ]}
            note_owners: dict[str, IndexedFact] = {}
            for operand in entries:
                for note in operand.fact["applicable_notes"]:
                    note_owners.setdefault(note_citation_id(note), operand)
            selected_citations = [
                _citation(note_owners.get(citation_id, entry), citation)
                for citation_id, citation in disclosure_citations(facts, selected_comparison).items()
            ]
            selected_citations.extend(
                _citation(parent_owners[item["id"]], _parent_citation(parent_owners[item["id"]].fact))
                for item in retained if item["kind"] == "parent"
            )
            context_citations.extend(selected_citations)
            complete_pair = (paired and len(retained) == len(required)
                             and comparison["status"] == "compatible"
                             and set(verification["fact_ids"]) == {operand.fact["fact_id"] for operand in entries})
            caveats = (comparison.get("scope_caveats", []) if complete_pair else list(dict.fromkeys(
                item["value"]["scope_caveat"] for item in retained if "scope_caveat" in item["value"]
            )))
            if complete_pair or caveats:
                supported_comparisons.append({
                    "source_id": source_id, "basis": comparison.get("basis") if complete_pair else None,
                    "scope_caveats": caveats,
                })
            if (paired or partial) and len(retained) < len(required):
                issues.append({"code": "missing_context", "source_id": source_id,
                               "requirements": [item["id"] for item in required if item["id"] not in retained_ids],
                               "detail": ("The context limit omitted required comparison evidence or applicable notes."
                                          if citations is None else
                                          "Selected evidence lacks required statement or comparison context.")})
                continue
            if not paired:
                continue
            if set(verification["fact_ids"]) != {operand.fact["fact_id"] for operand in entries}:
                issues.append({"code": "incompatible", "source_id": source_id,
                               "detail": "The selected observations do not match the filing's verified pair."})
                continue
            if actions is not None and actions.context_stalled:
                deferred = True
                issues.append({"code": "calculation_deferred", "detail": "Evidence recovery returned no new context."})
                break
            if actions is None:
                evidence = entry.source | {"facts": facts, "comparison": selected_comparison}
                growth = calculate_growth(evidence, prior, current)
            else:
                action = CalculateAction(index.manifest["snapshot_id"], source_id, prior, current,
                                         _calculation_ids(facts))
                calculated = actions.calculate(action, facts, selected_comparison)
                if calculated is None:
                    deferred = True
                    issues.append({"code": "calculation_deferred", "detail": "The calculation budget was exhausted."})
                    break
                growth = calculated
            if growth["status"] == "unavailable":
                issues.extend(issue | {"source_id": source_id} for issue in growth["issues"])
                continue
            by_role = {operand["role"]: next(item for item in entries if item.fact["fact_id"] == operand["fact_id"])
                       for operand in growth["operands"]}
            growth["citations"] = [
                _citation(by_role[citation["id"]], citation) for citation in growth["citations"]
                if citation["id"] in by_role
            ] + selected_citations
            signature = _fingerprint({
                "observations": sorted(_observation_signature(operand) for operand in entries),
                "comparison_basis": growth["comparison_basis"],
            })
            calculations.append((signature, growth))

    if not deferred and len({signature for signature, _ in calculations}) == 1:
        return calculations[0][1] | {"stop_reason": "sufficient_evidence"}, fact_ids, context
    if calculations and not deferred:
        issues.insert(0, {"code": "incompatible", "detail": "Selected filing pairs use conflicting amounts or reporting bases."})
    growth = {
        "status": "evidence_unavailable", "percent": None, "absolute_change": None,
        "message": "The selected evidence cannot support reported consolidated revenue growth.",
        "stop_reason": issues[0]["code"], "issues": issues,
        "observations": observations,
        "citations": context_citations,
    }
    if retain_partial_context:
        growth["comparisons"] = supported_comparisons
    return growth, fact_ids, context


def _answer_bounded_growth(
    index: CollectionIndex, request: dict[str, Any], initial: list[IndexedFact], context_limit: int,
    actions: _GrowthActions, *, initial_context_limit: int | None, citations: _PinnedCitations | None,
    retain_partial_context: bool,
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    answer, ids, context = _answer_growth(index, request, initial, context_limit, actions,
                                         initial_context_limit=initial_context_limit, citations=citations,
                                         retain_partial_context=retain_partial_context)
    missing = [issue["fiscal_year"] for issue in answer["issues"] if issue["code"] == "missing_fiscal_year"]
    selected: list[IndexedFact] = []
    if len(missing) == 1 and context_limit >= 2 and not actions.context_stalled:
        action = SearchAction(index.manifest["snapshot_id"], request["company_key"], missing[0])
        matches = actions.search(action, initial)
        if matches:
            recovered_sources = {entry.source["source_id"] for entry in matches}
            ranked_by_source = _facts_by_source(actions.eligible.values())
            source_order = dict.fromkeys(entry.source["source_id"] for entry in initial + matches)
            paired = [entry for source_id in source_order if source_id in recovered_sources
                      and len({entry.fact["reporting_period"]["fiscal_year"]
                               for entry in ranked_by_source[source_id]}) == 2
                      for entry in ranked_by_source[source_id]]
            # Preserve both fiscal years in the partial context even across different sources.
            selected = paired or [initial[0], matches[0], *initial[1:], *matches[1:]]
    elif (retain_partial_context and not actions.context_stalled and answer["stop_reason"] == "incompatible"
          and actions.eligible.keys() - set(ids)
          and not any(comparison["basis"] for comparison in answer["comparisons"])):
        selected = actions.search_pair(SearchPairAction(
            index.manifest["snapshot_id"], request["company_key"], request["prior_year"], request["current_year"],
        ))
    if selected:
        answer, ids, context = _answer_growth(index, request, selected[:context_limit], context_limit, actions,
                                             initial_context_limit=initial_context_limit, citations=citations,
                                             retain_partial_context=retain_partial_context)
    if actions.limit:
        answer.update(stop_reason="budget_exhausted", budget_limit=actions.limit)
    elif answer["stop_reason"] != "sufficient_evidence":
        answer["stop_reason"] = "no_progress"
    return answer, ids, context


def ask_collection(
    index: CollectionIndex, question: str, *, record: dict[str, Any] | None = None,
    context_limit: int = GROWTH_CONTEXT_LIMIT,
    initial_fact_limit: int | None = None, initial_context_limit: int | None = None,
    mode: Literal["one-pass", "bounded"] = "one-pass",
    budget: RecoveryBudget | None = None,
) -> dict[str, Any]:
    started = perf_counter_ns()
    return _ask_collection(index, question, record, context_limit, initial_fact_limit, mode,
                           budget or RecoveryBudget(), lambda: perf_counter_ns() - started,
                           initial_context_limit=initial_context_limit)


def _ask_collection(
    index: CollectionIndex, question: str, record: dict[str, Any] | None,
    context_limit: int, initial_fact_limit: int | None, mode: str,
    budget: RecoveryBudget, elapsed: Callable[[], int], *,
    initial_context_limit: int | None = None, search_version: str | None = None,
) -> dict[str, Any]:
    if type(context_limit) is not int or context_limit < 1:
        raise SourceError("The collection context limit must be a positive integer.")
    if initial_fact_limit is not None and (type(initial_fact_limit) is not int
                                           or not 1 <= initial_fact_limit <= context_limit):
        raise SourceError("The initial fact limit must be between one and the collection context limit.")
    if initial_context_limit is not None and (type(initial_context_limit) is not int
                                              or not 1 <= initial_context_limit <= context_limit):
        raise SourceError("The initial context limit must be between one and the collection context limit.")
    if mode not in ("one-pass", "bounded"):
        raise SourceError("Choose one-pass or bounded collection retrieval.")
    request, clarification = _resolve(index, question)
    if index.manifest["index_version"] == "collection-index-v1":
        if request and request["operation"] == "growth":
            request = None
            clarification = LOOKUP_CLARIFICATION
        elif clarification.startswith(LOOKUP_CLARIFICATION):
            clarification = LOOKUP_CLARIFICATION
    result: dict[str, Any] = {"snapshot_id": index.manifest["snapshot_id"], "request": request}
    ranked = []
    selected: list[str] = []
    context: list[dict[str, Any]] | None = None
    lookup_notes: list[str] = []
    actions = None
    initial: list[IndexedFact] = []
    if request is None:
        result.update(status="clarify", message=clarification)
    else:
        growth = request["operation"] == "growth"
        years = (request["prior_year"], request["current_year"]) if growth else (request["fiscal_year"],)
        words = _words(question)
        for entry in index.facts:
            fact = entry.fact
            reasons = _ineligible(entry)
            if entry.company != request["company_key"]:
                reasons.append("different_company")
            period = fact["reporting_period"]
            if period["kind"] != "annual" or period["fiscal_year"] not in years:
                reasons.append("different_reporting_period")
            ranked.append((
                {
                    "fact_id": fact["fact_id"], "source_id": fact["source_id"],
                    "parent_table_id": fact["parent_table_id"], "company": fact["company"],
                    "reporting_period": period, "basis": fact["basis"],
                    "raw_amount": fact["raw_amount"], "currency": fact["currency"],
                    "scale": fact["scale"], "status": fact["status"],
                    "value_locator": fact["locators"]["value"],
                    "keyword_score": len(words & entry.terms), "exclusions": reasons,
                },
                entry,
            ))
        ranked.sort(key=lambda item: (
            bool(item[0]["exclusions"]), -item[0]["keyword_score"],
            item[1].fact["comparative"], item[0]["fact_id"],
        ))
        eligible = [entry for candidate, entry in ranked if not candidate["exclusions"]]
        if growth:
            pinned_citations = _PinnedCitations(index.store, legacy_dated_comparison=index.legacy_dated_comparison)
            citations = None if search_version in (LEGACY_GROWTH_VERSION, LEGACY_BOUNDED_VERSION) else pinned_citations
            retain_partial_context = search_version in (None, GROWTH_SEARCH_VERSION, BOUNDED_SEARCH_VERSION)
            initial = eligible[:min(initial_fact_limit or context_limit, initial_context_limit or context_limit)]
            if mode == "bounded":
                actions = _GrowthActions(index, request, eligible, budget, elapsed, pinned_citations)
                answer, selected, context = _answer_bounded_growth(
                    index, request, initial, context_limit, actions,
                    initial_context_limit=initial_context_limit, citations=citations,
                    retain_partial_context=retain_partial_context,
                )
            else:
                answer, selected, context = _answer_growth(index, request, initial, context_limit,
                                                           initial_context_limit=initial_context_limit, citations=citations,
                                                           retain_partial_context=retain_partial_context)
            result.update(answer)
        elif not eligible:
            result.update(status="evidence_unavailable", message=(
                f'No verified annual consolidated revenue for {request["company"]} FY{request["fiscal_year"]}.'
            ))
        else:
            bases = {_observation_signature(entry) for entry in eligible}
            if len(bases) > 1:
                selected = [entry.fact["fact_id"] for entry in eligible]
                result.update(status="conflicting_evidence", message=(
                    "Verified observations disagree on the amount, reporting period, or basis."
                ), alternatives=[{"fact": entry.fact, "citation": _citation(entry)} for entry in eligible])
            else:
                entry = eligible[0]
                selected = [entry.fact["fact_id"]]
                result.update(status="answered", fact=entry.fact, source=entry.source,
                              citations=[_citation(entry)])
                if search_version in (None, LOOKUP_SEARCH_VERSION, BOUNDED_SEARCH_VERSION):
                    notes = disclosure_citations([entry.fact], {})
                    lookup_notes = _PinnedCitations(index.store).valid_ids(entry.source["source_id"], notes)
                    result["citations"].extend(_citation(entry, notes[key]) for key in lookup_notes)
                    if missing_notes := notes.keys() - set(lookup_notes):
                        result["unresolved_requirements"] = sorted(missing_notes)
    if record is not None:
        record.update(
            record_version=RECORD_VERSION,
            search_version=LEGACY_LOOKUP_VERSION if search_version == LEGACY_LOOKUP_VERSION else LOOKUP_SEARCH_VERSION,
            question=question,
            snapshot=index.manifest, ranked_candidates=[candidate for candidate, _ in ranked],
            selected_evidence_ids=selected, outcome=result,
        )
        if lookup_notes:
            record["selected_note_ids"] = lookup_notes
        if context is not None:
            version = search_version if search_version in GROWTH_SEARCH_VERSIONS else GROWTH_SEARCH_VERSION
            record.update(search_version=version, context_limit=context_limit, selected_context=context)
            if initial_fact_limit is not None:
                record["initial_fact_limit"] = initial_fact_limit
        if mode == "bounded":
            version = search_version if search_version in BOUNDED_SEARCH_VERSIONS else BOUNDED_SEARCH_VERSION
            record.update(search_version=version,
                          context_limit=context_limit,
                          initial_fact_limit=initial_fact_limit, budget=asdict(budget),
                          initial_evidence_ids=[entry.fact["fact_id"] for entry in initial],
                          actions=actions.actions if actions else [], elapsed_ns=actions.elapsed_ns if actions else [])
        if initial_context_limit is not None:
            record["initial_context_limit"] = initial_context_limit
    return result


def replay_collection(store: SourceStore, record: object) -> dict[str, Any]:
    if (not isinstance(record, dict) or record.get("record_version") != RECORD_VERSION
            or record.get("search_version") not in (LEGACY_LOOKUP_VERSION, LOOKUP_SEARCH_VERSION,
                                                    *GROWTH_SEARCH_VERSIONS, *BOUNDED_SEARCH_VERSIONS)
            or not isinstance(record.get("question"), str)):
        raise SourceError("Unsupported collection validation record.")
    limit = record.get("context_limit", GROWTH_CONTEXT_LIMIT)
    manifest = record.get("snapshot")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("sources"), list):
        raise SourceError("The collection validation record must identify its source snapshot.")
    source_ids = set()
    for source in manifest["sources"]:
        if not isinstance(source, dict) or not isinstance(source.get("source_id"), str):
            raise SourceError("The collection validation record contains an invalid source identity.")
        source_ids.add(source["source_id"])
    index = CollectionIndex.build(store, source_ids)
    if manifest.get("index_version") == "collection-index-v1" and record["search_version"] == LEGACY_LOOKUP_VERSION:
        legacy_manifest = {
            key: value for key, value in index.manifest.items() if key not in ("snapshot_id", "comparison_hash")
        }
        legacy_manifest["index_version"] = "collection-index-v1"
        index = replace(index, manifest={"snapshot_id": "sha256:" + _fingerprint(legacy_manifest), **legacy_manifest})
    elif _fingerprint(index.manifest) != _fingerprint(manifest):
        index = CollectionIndex.build(store, source_ids, legacy_original_comparison=True)
        if _fingerprint(index.manifest) != _fingerprint(manifest):
            index = CollectionIndex.build(store, source_ids, legacy_dated_comparison=True,
                                          legacy_original_comparison=True)
    if _fingerprint(index.manifest) != _fingerprint(manifest):
        raise SourceError("The saved collection snapshot does not match the reproduced index or versions.")
    reproduced: dict[str, Any] = {}
    initial_fact_limit = record.get("initial_fact_limit")
    initial_context_limit = record.get("initial_context_limit")
    version = record["search_version"]
    if version in BOUNDED_SEARCH_VERSIONS:
        budget_data = record.get("budget")
        checkpoints = record.get("elapsed_ns")
        if (not isinstance(budget_data, dict) or set(budget_data) != {"max_calls", "max_seconds"}
                or not isinstance(checkpoints, list)
                or any(type(value) is not int or value < 0 for value in checkpoints)
                or checkpoints != sorted(checkpoints)):
            raise SourceError("The saved collection budget or elapsed time checkpoints are invalid.")
        times = iter(checkpoints)

        def elapsed() -> int:
            try:
                value: int = next(times)
                return value
            except StopIteration as exc:
                raise SourceError("The saved collection validation record is missing an elapsed time checkpoint.") from exc

        budget = RecoveryBudget(budget_data["max_calls"], budget_data["max_seconds"])
        result = _ask_collection(index, record["question"], reproduced, limit, initial_fact_limit, "bounded", budget,
                                 elapsed, initial_context_limit=initial_context_limit, search_version=version)
    else:
        result = _ask_collection(index, record["question"], reproduced, limit, initial_fact_limit, "one-pass",
                                 RecoveryBudget(), lambda: 0, initial_context_limit=initial_context_limit,
                                 search_version=version)
    if _fingerprint(reproduced) != _fingerprint(record):
        raise SourceError("The saved collection validation record does not match the replayed run.")
    return result
