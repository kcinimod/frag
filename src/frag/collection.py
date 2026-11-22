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
from frag.citations import citation_text, has_citable_amount, revenue_cell_citation
from frag.growth import calculate_growth, disclosure_citations, note_citation_id
from frag.lookup import METRIC, resolve_request
from frag.store import SourceError, SourceNotFound, SourceStore, StoreMissing

INDEX_VERSION = "collection-index-v2"
SEARCH_VERSION = "annual-revenue-search-v1"
RECORD_VERSION = "collection-run-v1"
GROWTH_SEARCH_VERSION = "revenue-growth-search-v1"
GROWTH_CONTEXT_LIMIT = 16
BOUNDED_SEARCH_VERSION = "bounded-revenue-search-v1"
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

    @classmethod
    def build(cls, store: SourceStore, source_ids: set[str] | None = None) -> "CollectionIndex":
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
            comparisons[identity["source_id"]] = {
                "comparison": source["comparison"],
                "fact_ids": [fact["fact_id"] for fact in source["facts"]],
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
                    *(note["title"] + " " + note["interpretation"] for note in fact["applicable_notes"]),
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
                   companies, tuple(entries[key] for key in sorted(entries)), comparisons)


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
            item = disclosure_citations([fact], comparison).get(citation_id)
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


class _GrowthActions:
    def __init__(
        self, index: CollectionIndex, request: dict[str, Any], eligible: list[IndexedFact],
        budget: RecoveryBudget, elapsed: Callable[[], int],
    ) -> None:
        self.index = index
        self.request = request
        self.eligible = {entry.fact["fact_id"]: entry for entry in eligible}
        self.budget = budget
        self.elapsed = elapsed
        self.actions: list[dict[str, Any]] = []
        self.elapsed_ns: list[int] = []
        self.limit: str | None = None

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

    def _finish(self, operation: str, action: SearchAction | CalculateAction, result: dict[str, Any]) -> bool:
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

    def calculate(self, action: CalculateAction) -> dict[str, Any] | None:
        comparison = self.index.comparisons.get(action.source_id)
        operands = [self.eligible[fact_id] for fact_id in action.fact_ids if fact_id in self.eligible]
        facts = [entry.fact for entry in operands]
        if (action.snapshot_id != self.index.manifest["snapshot_id"]
                or (action.prior_year, action.current_year) != (self.request["prior_year"], self.request["current_year"])
                or {fact["reporting_period"]["fiscal_year"] for fact in facts} != {action.prior_year, action.current_year}
                or action.fact_ids != _calculation_ids(facts)
                or comparison is None or set(action.fact_ids) != set(comparison["fact_ids"])
                or any(entry.source["source_id"] != action.source_id for entry in operands)):
            raise SourceError("The bounded calculation does not match eligible evidence for the pinned request.")
        if not self._start():
            return None
        evidence = operands[0].source | {"facts": facts, "comparison": comparison["comparison"]}
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


def _answer_growth(
    index: CollectionIndex, request: dict[str, Any], selected: list[IndexedFact], context_limit: int,
    actions: _GrowthActions | None = None,
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    prior, current = request["prior_year"], request["current_year"]
    fact_ids = [entry.fact["fact_id"] for entry in selected]
    context = [{"kind": "fact", "id": entry.fact["fact_id"], "source_id": entry.source["source_id"],
                "value": {key: value for key, value in entry.fact.items() if key != "applicable_notes"}}
               for entry in selected]
    observations = [{"fact": item["value"], "citation": _citation(entry)}
                    for entry, item in zip(selected, context, strict=True)]
    context_citations: list[dict[str, Any]] = []
    sources = _facts_by_source(selected)

    issues = [
        {"code": "missing_fiscal_year", "fiscal_year": year,
         "detail": f"Selected evidence lacks verified FY{year} revenue."}
        for year in (prior, current)
        if not any(entry.fact["reporting_period"]["fiscal_year"] == year for entry in selected)
    ]
    calculations: list[tuple[str, dict[str, Any]]] = []
    deferred = False
    if not issues:
        def has_both_years(entries: list[IndexedFact]) -> bool:
            return {entry.fact["reporting_period"]["fiscal_year"] for entry in entries} == {prior, current}

        pairs = [entries for entries in sources.values() if has_both_years(entries)]
        if not pairs:
            issues.append({"code": "incompatible", "detail": "A verified pair from one filing is required."})
        for entries in sorted(sources.values(), key=lambda entries: not has_both_years(entries)):
            entry = entries[0]
            source_id = entry.source["source_id"]
            verification = index.comparisons[source_id]
            comparison = verification["comparison"]
            notes = {note_citation_id(note): note for operand in entries for note in operand.fact["applicable_notes"]}
            disclosures = {item["id"]: item for item in comparison.get("evidence", [])}
            comparison_context = {"kind": "comparison", "id": source_id, "source_id": source_id, "value": {
                key: value for key, value in comparison.items() if key != "evidence"
            } | {"fact_ids": verification["fact_ids"]}}
            required = [comparison_context, *(
                {"kind": kind, "id": key, "source_id": source_id, "value": value}
                for kind, items in (("note", notes), ("disclosure", disclosures)) for key, value in items.items()
            )]
            retained = required[:context_limit - len(context)]
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
            context_citations.extend(selected_citations)
            if not has_both_years(entries):
                continue
            if len(retained) < len(required):
                issues.append({"code": "missing_context", "source_id": source_id,
                               "requirements": [item["id"] for item in required[len(retained):]],
                               "detail": "The context limit omitted required comparison evidence or applicable notes."})
                continue
            if set(verification["fact_ids"]) != {operand.fact["fact_id"] for operand in entries}:
                issues.append({"code": "incompatible", "source_id": source_id,
                               "detail": "The selected observations do not match the filing's verified pair."})
                continue
            if actions is None:
                evidence = entry.source | {"facts": facts, "comparison": selected_comparison}
                growth = calculate_growth(evidence, prior, current)
            else:
                action = CalculateAction(index.manifest["snapshot_id"], source_id, prior, current,
                                         _calculation_ids(facts))
                calculated = actions.calculate(action)
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
    return growth, fact_ids, context


def _answer_bounded_growth(
    index: CollectionIndex, request: dict[str, Any], initial: list[IndexedFact], context_limit: int,
    actions: _GrowthActions,
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    answer, ids, context = _answer_growth(index, request, initial, context_limit, actions)
    missing = [issue["fiscal_year"] for issue in answer["issues"] if issue["code"] == "missing_fiscal_year"]
    if len(missing) == 1 and context_limit >= 2:
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
            answer, ids, context = _answer_growth(index, request, selected[:context_limit], context_limit, actions)
    if actions.limit:
        answer.update(stop_reason="budget_exhausted", budget_limit=actions.limit)
    elif answer["stop_reason"] != "sufficient_evidence":
        answer["stop_reason"] = "no_progress"
    return answer, ids, context


def ask_collection(
    index: CollectionIndex, question: str, *, record: dict[str, Any] | None = None,
    context_limit: int = GROWTH_CONTEXT_LIMIT,
    initial_fact_limit: int | None = None, mode: Literal["one-pass", "bounded"] = "one-pass",
    budget: RecoveryBudget | None = None,
) -> dict[str, Any]:
    started = perf_counter_ns()
    return _ask_collection(index, question, record, context_limit, initial_fact_limit, mode,
                           budget or RecoveryBudget(), lambda: perf_counter_ns() - started)


def _ask_collection(
    index: CollectionIndex, question: str, record: dict[str, Any] | None,
    context_limit: int, initial_fact_limit: int | None, mode: str,
    budget: RecoveryBudget, elapsed: Callable[[], int],
) -> dict[str, Any]:
    if type(context_limit) is not int or context_limit < 1:
        raise SourceError("The collection context limit must be a positive integer.")
    if initial_fact_limit is not None and (type(initial_fact_limit) is not int
                                           or not 1 <= initial_fact_limit <= context_limit):
        raise SourceError("The initial fact limit must be between one and the collection context limit.")
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
            initial = eligible[:initial_fact_limit or context_limit]
            if mode == "bounded":
                actions = _GrowthActions(index, request, eligible, budget, elapsed)
                answer, selected, context = _answer_bounded_growth(index, request, initial, context_limit, actions)
            else:
                answer, selected, context = _answer_growth(index, request, initial, context_limit)
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
    if record is not None:
        record.update(
            record_version=RECORD_VERSION, search_version=SEARCH_VERSION, question=question,
            snapshot=index.manifest, ranked_candidates=[candidate for candidate, _ in ranked],
            selected_evidence_ids=selected, outcome=result,
        )
        if context is not None:
            record.update(search_version=GROWTH_SEARCH_VERSION, context_limit=context_limit,
                          selected_context=context)
            if initial_fact_limit is not None:
                record["initial_fact_limit"] = initial_fact_limit
        if mode == "bounded":
            record.update(search_version=BOUNDED_SEARCH_VERSION, context_limit=context_limit,
                          initial_fact_limit=initial_fact_limit, budget=asdict(budget),
                          initial_evidence_ids=[entry.fact["fact_id"] for entry in initial],
                          actions=actions.actions if actions else [], elapsed_ns=actions.elapsed_ns if actions else [])
    return result


def replay_collection(store: SourceStore, record: object) -> dict[str, Any]:
    if (not isinstance(record, dict) or record.get("record_version") != RECORD_VERSION
            or record.get("search_version") not in (SEARCH_VERSION, GROWTH_SEARCH_VERSION, BOUNDED_SEARCH_VERSION)
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
    if manifest.get("index_version") == "collection-index-v1" and record["search_version"] == SEARCH_VERSION:
        legacy = {key: value for key, value in index.manifest.items() if key not in ("snapshot_id", "comparison_hash")}
        legacy["index_version"] = "collection-index-v1"
        index = replace(index, manifest={"snapshot_id": "sha256:" + _fingerprint(legacy), **legacy})
    if _fingerprint(index.manifest) != _fingerprint(manifest):
        raise SourceError("The saved collection snapshot does not match the reproduced index or versions.")
    reproduced: dict[str, Any] = {}
    initial_fact_limit = record.get("initial_fact_limit")
    if record["search_version"] == BOUNDED_SEARCH_VERSION:
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
        result = _ask_collection(index, record["question"], reproduced, limit, initial_fact_limit, "bounded", budget, elapsed)
    else:
        result = ask_collection(index, record["question"], record=reproduced, context_limit=limit,
                                initial_fact_limit=initial_fact_limit)
    if _fingerprint(reproduced) != _fingerprint(record):
        raise SourceError("The saved collection validation record does not match the replayed run.")
    return result
