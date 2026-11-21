"""One-pass revenue retrieval over a content-addressed local catalogue view."""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from frag import store as source_store
from frag.citations import citation_text, has_citable_amount, revenue_cell_citation
from frag.lookup import METRIC, resolve_request
from frag.store import SourceError, SourceNotFound, SourceStore, StoreMissing

INDEX_VERSION = "collection-index-v1"
SEARCH_VERSION = "annual-revenue-search-v1"
RECORD_VERSION = "collection-run-v1"
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
        inputs = []
        for source in sources:
            identity = _source_identity(source)
            if identity["source_id"] != "sha256:" + identity["source_hash"]:
                raise SourceError("Collection source identifier does not match its preserved hash.")
            inputs.append(identity | {"evidence_hash": _fingerprint(source["facts"])})
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
        }
        return cls({"snapshot_id": "sha256:" + _fingerprint(manifest), **manifest},
                   companies, tuple(entries[key] for key in sorted(entries)))


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
    if request is None or request["operation"] != "lookup":
        return None, "Ask for annual reported consolidated revenue for one fiscal year."
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


def _citation(entry: IndexedFact) -> dict[str, Any]:
    source_id = entry.source["source_id"]
    fact_id = entry.fact["fact_id"]
    components = "/".join(quote(part, safe="") for part in (source_id, fact_id, entry.fingerprint))
    return {
        **revenue_cell_citation(entry.fact, "revenue"),
        "source_id": source_id,
        "source_hash": entry.source["source_hash"],
        "href": "/api/collection/citations/" + components,
    }


def collection_excerpt(store: SourceStore, source_id: str, fact_id: str, fingerprint: str) -> str:
    source, original = store.inspect_with_original(source_id)
    identity = _source_identity(source)
    for fact in source["facts"]:
        entry = IndexedFact(fact, identity, set())
        if (fact["fact_id"] == fact_id and fact["source_id"] == source_id
                and fact["reporting_period"]["kind"] == "annual" and not _ineligible(entry)
                and entry.fingerprint == fingerprint):
            return citation_text(original, source["source_hash"], _citation(entry))
    raise SourceNotFound("The pinned revenue citation is unavailable in this store.")


def ask_collection(
    index: CollectionIndex, question: str, *, record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request, clarification = _resolve(index, question)
    result: dict[str, Any] = {"snapshot_id": index.manifest["snapshot_id"], "request": request}
    ranked = []
    selected: list[str] = []
    if request is None:
        result.update(status="clarify", message=clarification)
    else:
        words = _words(question)
        for entry in index.facts:
            fact = entry.fact
            reasons = _ineligible(entry)
            if entry.company != request["company_key"]:
                reasons.append("different_company")
            period = fact["reporting_period"]
            if period["kind"] != "annual" or period["fiscal_year"] != request["fiscal_year"]:
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
        if not eligible:
            result.update(status="evidence_unavailable", message=(
                f'No verified annual consolidated revenue for {request["company"]} FY{request["fiscal_year"]}.'
            ))
        else:
            bases = {
                _fingerprint({key: entry.fact[key] for key in (
                    "reporting_period", "normalized_amount", "currency", "basis",
                )})
                for entry in eligible
            }
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
    return result


def replay_collection(store: SourceStore, record: object) -> dict[str, Any]:
    if (not isinstance(record, dict) or record.get("record_version") != RECORD_VERSION
            or record.get("search_version") != SEARCH_VERSION or not isinstance(record.get("question"), str)):
        raise SourceError("Unsupported collection validation record.")
    manifest = record.get("snapshot")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("sources"), list):
        raise SourceError("The collection validation record must identify its source snapshot.")
    source_ids = set()
    for source in manifest["sources"]:
        if not isinstance(source, dict) or not isinstance(source.get("source_id"), str):
            raise SourceError("The collection validation record contains an invalid source identity.")
        source_ids.add(source["source_id"])
    index = CollectionIndex.build(store, source_ids)
    if _fingerprint(index.manifest) != _fingerprint(manifest):
        raise SourceError("The saved collection snapshot does not match the reproduced index or versions.")
    reproduced: dict[str, Any] = {}
    result = ask_collection(index, record["question"], record=reproduced)
    if _fingerprint(reproduced) != _fingerprint(record):
        raise SourceError("The saved collection validation record does not match the replayed run.")
    return result
