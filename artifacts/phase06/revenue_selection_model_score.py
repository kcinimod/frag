"""Replay model selections offline and score them against the independent #54 review."""

import argparse
from dataclasses import asdict
import gzip
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys
from typing import Any
from zipfile import ZipFile

from revenue_selection_baseline import ROOT, block_sockets, json_bytes, read_sealed
from revenue_selection_model import CONTROLS, STRATEGIES, filing_source, select_revenue

from frag.revenue_model_selection import SYSTEM_PROMPT, InvalidModelResponse, ModelUnavailable
from frag.revenue_selection import FilingInventory, filing_inventory
from frag.store import SourceMetadata


def replay(
    inventory: FilingInventory, source: dict[str, Any], saved: dict[str, Any], strategy: str,
) -> None:
    if inventory.original_sha256 != saved["original_sha256"]:
        raise ValueError("The original changed since the model run.")
    pending = iter(saved.get("batches", []))

    def recorded_model(prompt: str, row_ids: tuple[str, ...]) -> str:
        batch = next(pending, None)
        if (batch is None or sha256(prompt.encode()).hexdigest() != batch["prompt_sha256"]
                or list(row_ids) != batch["row_ids"]):
            raise RuntimeError("A replay prompt differs from the recorded batch.")
        if "response" in batch:
            return str(batch["response"])
        if batch["outcome"] == "invalid_response":
            raise InvalidModelResponse(batch["error"])
        raise ModelUnavailable(batch["error"])

    result = select_revenue(strategy, inventory, source, recorded_model)
    if next(pending, None) is not None:
        raise ValueError("The replay did not consume every model batch.")
    for key, value in result.items():
        expected = saved[key]
        if key == "batches":
            value, expected = (
                [{key: item for key, item in batch.items() if key != "elapsed_ms"} for batch in batches]
                for batches in (value, expected)
            )
        if value != expected:
            raise ValueError(f"Model selection replay differs in {key} for {inventory.original_sha256}.")


def initial_batches(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [batch for batch in record.get("batches", []) if batch["stage"] == "inventory"]


def submitted_rows(record: dict[str, Any]) -> set[str]:
    return {row_id for batch in initial_batches(record) for row_id in batch["row_ids"]}


def paired_outcomes(
    strategy: str, record: dict[str, Any], target: dict[str, str] | None,
    expected_years: list[int], exact_years: list[int], *, full_model_rows: set[str],
) -> dict[str, Any]:
    shortlist = record.get("shortlist", record.get("candidates"))
    batches = initial_batches(record)
    survived = target in shortlist if target is not None and shortlist is not None else None
    submitted = target["row_id"] in submitted_rows(record) if target and strategy != "rules_alone" else None
    omitted_table_rows = None
    if target and strategy == "rules_shortlisted_model":
        table_prefix = f'{target["table_id"]}/'
        omitted_table_rows = sum(
            row_id.startswith(table_prefix) for row_id in full_model_rows - submitted_rows(record)
        )
    selected = record["selected"]
    stop = record["stop"]
    missed_years = sorted(set(expected_years) - set(exact_years))
    if target is None:
        if selected is not None:
            selection = "wrong_row"
            cause = "rules_choice" if strategy == "rules_alone" else "model_choice"
        else:
            selection = "abstained" if stop in {"no_candidate", "model_abstained"} else stop
            cause = None if selection == "abstained" else stop
    elif target == selected:
        selection = "reviewed_row"
        cause = "deterministic_validation" if missed_years else None
    elif survived is False or submitted is False:
        selection = "shortlist_excluded" if survived is False else "target_not_submitted"
        cause = "candidate_representation"
    else:
        selection = "wrong_row" if selected else stop
        if stop in {"input_limit", "invalid_response", "model_unavailable"}:
            cause = stop
        elif omitted_table_rows:
            cause = "shortlisted_context_or_model_choice"
        else:
            cause = "rules_choice" if strategy == "rules_alone" else "model_choice"
    return {
        "selected": selected, "selection_outcome": selection,
        "shortlist": shortlist, "reviewed_target_shortlisted": survived,
        "reviewed_target_submitted": submitted,
        "reviewed_table_rows_omitted": omitted_table_rows,
        "reviewed_target_nominated": (
            any(target == batch.get("selected") for batch in batches)
            if target is not None and strategy != "rules_alone" else None
        ),
        "extraction": {
            "outcome": "not_run" if selected is None else stop or "verified",
            "observation_count": len(record["observations"]),
            "expected_fiscal_years": expected_years, "exact_fiscal_years": exact_years,
            "missed_fiscal_years": missed_years,
        },
        "miss_cause": cause,
    }


def control_exact_years(label: str, records: list[dict[str, Any]]) -> list[int]:
    if label == "absent":
        return []
    # Raw amount, physical amount cell and physical year cell in the synthetic distractor.
    expected = {2023: ("15", 5, 3), 2024: ("19", 3, 2)}
    matches = []
    for fact in records:
        period = fact["reporting_period"]
        year = period["fiscal_year"]
        locators = fact["locators"]
        value, header, units = (locators[key] for key in ("value", "year_header", "unit_header"))
        if (expected.get(year) == (fact["raw_amount"], value["cell"], header["cell"])
                and fact["normalized_amount"] == f"{fact['raw_amount']}000000"
                and (value["table"], value["line"]) == (2, 10)
                and (header["table"], header["line"]) == (2, 7)
                and (units["table"], units["line"], units["cell"]) == (2, 8, 1)
                and (period["kind"], period["start"], period["end"]) == ("annual", f"{year}-01-01", f"{year}-12-31")
                and (fact["currency"], fact["scale"], fact["scope"]) == ("USD", 1_000_000, "consolidated")):
            matches.append(year)
    return [year for year in sorted(expected) if matches.count(year) == 1]


def verification_years(facts: list[dict[str, Any]], audited: list[dict[str, Any]]) -> dict[str, list[int]]:
    verified = [row["observed"] for row in audited if row["reusable_verification_matched"]]
    return {
        "verified_exact_fiscal_years": sorted(fact["reporting_period"]["fiscal_year"] for fact in verified),
        "incorrect_verified_fiscal_years": sorted(
            fact["reporting_period"]["fiscal_year"] for fact in facts
            if fact["status"] == "verified" and fact not in verified
        ),
    }


def score(runner_path: Path, expected_path: Path, run_path: Path) -> dict[str, Any]:
    from fresh_score import audit_observations
    from sec_holdout_score import position, within

    runner_payload = read_sealed(runner_path, "runner")
    expected_payload = read_sealed(expected_path, "scorer")
    run_payload = run_path.read_bytes()
    report = json.loads(gzip.decompress(run_payload))
    paired = report["strategy"] == "paired"
    if report["strategy"] not in {"paired", "model_alone"} or report["runner_sha256"] != sha256(runner_payload).hexdigest():
        raise ValueError("The run must bind a supported strategy to the sealed runner.")
    if report["batching"]["system_prompt"] != SYSTEM_PROMPT or report["controls"].keys() != CONTROLS.keys():
        raise ValueError("The model run must preserve the system prompt and both synthetic controls.")
    def replay_case(
        inventory: FilingInventory, source: dict[str, Any], case: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        records = case["strategies"] if paired else {"model_alone": case}
        if paired and records.keys() != set(STRATEGIES):
            raise ValueError("Each paired case must include all three strategies.")
        for strategy, record in records.items():
            replay(inventory, source, record, strategy)
        return records

    controls = {}
    for label, record in report["controls"].items():
        original = (ROOT / "tests" / "fixtures" / f"revenue-selection-{label}.html").read_bytes()
        source = {**asdict(SourceMetadata(company="Example Corporation")), "provenance": {"kind": "synthetic"}}
        records = replay_case(filing_inventory(original), source, record)
        if paired:
            row_id = CONTROLS[label]
            target = {"row_id": row_id, "table_id": row_id.split("/")[0]} if row_id else None
            full_model_rows = submitted_rows(records["model_alone"])
            controls[label] = {
                "reviewed_target": target,
                "strategies": {
                    strategy: paired_outcomes(
                        strategy, result, target, [2023, 2024] if row_id else [],
                        control_exact_years(label, result["observations"]),
                        full_model_rows=full_model_rows,
                    ) for strategy, result in records.items()
                },
            }
            continue
        controls[label] = {
            "stop": record["stop"], "selected": record["selected"], "observation_count": len(record["observations"]),
            "expected_row_id": CONTROLS[label],
        }
    results = {}
    with ZipFile(BytesIO(runner_payload)) as runner, ZipFile(BytesIO(expected_payload)) as scorer:
        manifest = json.loads(runner.read("manifest.json"))
        expected = json.loads(scorer.read("expected.json"))
        if not report["cohort"] == expected["cohort"] == manifest["cohort"]:
            raise ValueError("The run, runner archive, and review cohorts differ.")
        if report["filings"].keys() != {filing["source_id"] for filing in manifest["sources"]}:
            raise ValueError("The run must include exactly the original filings in the sealed manifest.")
        for filing in manifest["sources"]:
            source_id = filing["source_id"]
            original = runner.read(filing["path"])
            review = expected["sources"][source_id]
            record = report["filings"][source_id]
            inventory = filing_inventory(original)
            if inventory.original_sha256 != filing["sha256"]:
                raise ValueError(f"The original differs from the sealed manifest for {source_id}.")
            records = replay_case(inventory, filing_source(filing), record)
            lines = original.split(b"\n")
            locators = review["locators"]
            targets = [
                {"table_id": table["table_id"], "row_id": row["row_id"]}
                for table in inventory.record()
                if within(position(lines, table["locator"]), locators["statement"])
                for row in table["rows"]
                if within(position(lines, row["locator"]), locators["revenue_row"])
            ]
            target = targets[0] if len(targets) == 1 else None
            if paired:
                if target is None:
                    raise ValueError(f"The independent review must resolve one inventory row for {source_id}.")
                full_model_rows = submitted_rows(records["model_alone"])
                strategies = {}
                for strategy, result in records.items():
                    audited = audit_observations(original, filing, review, {"facts": result["observations"]})
                    years = sorted(row["expected"]["fiscal_year"] for row in audited)
                    exact = sorted(row["expected"]["fiscal_year"] for row in audited if row["extraction_matched"])
                    outcomes = paired_outcomes(strategy, result, target, years, exact, full_model_rows=full_model_rows)
                    outcomes["extraction"].update(verification_years(result["observations"], audited))
                    strategies[strategy] = outcomes
                results[source_id] = {"issuer": filing["issuer"], "reviewed_target": target, "strategies": strategies}
                continue
            audited = audit_observations(original, filing, review, {"facts": record["observations"]})
            inventory_batches = initial_batches(record)
            results[source_id] = {
                "issuer": filing["issuer"], "stop": record["stop"], "selected": record["selected"],
                "reviewed_target": target,
                "reviewed_target_covered": target is not None and any(
                    target["row_id"] in batch["row_ids"] for batch in inventory_batches
                ),
                "reviewed_target_nominated": target is not None and any(
                    target == batch.get("selected") for batch in inventory_batches
                ),
                "reviewed_target_selected": target is not None and target == record["selected"],
                "observations_reviewed": len(audited),
                "exact_fiscal_years": sorted(row["expected"]["fiscal_year"] for row in audited if row["extraction_matched"]),
                **verification_years(record["observations"], audited),
            }
    common = {
        "run_sha256": sha256(run_payload).hexdigest(),
        "independent_review_sha256": sha256(expected_payload).hexdigest(),
        "replayed_cases": len(results) + len(controls),
        "filings": results, "controls": controls,
    }
    if paired:
        return {
            **common, "observations_reviewed": sum(
                len(case["strategies"]["rules_alone"]["extraction"]["expected_fiscal_years"]) for case in results.values()
            ),
            "strategies": {
                strategy: {
                    "reviewed_rows_selected": sum(
                        case["strategies"][strategy]["selection_outcome"] == "reviewed_row" for case in results.values()
                    ),
                    **{
                        label: sum(len(case["strategies"][strategy]["extraction"][field]) for case in results.values())
                        for label, field in (
                            ("exact_observations", "exact_fiscal_years"),
                            ("verified_exact_observations", "verified_exact_fiscal_years"),
                            ("incorrect_verified_observations", "incorrect_verified_fiscal_years"),
                        )
                    },
                } for strategy in STRATEGIES
            },
        }
    return {
        **common,
        "observations_reviewed": sum(row["observations_reviewed"] for row in results.values()),
        "exact_observations": sum(len(row["exact_fiscal_years"]) for row in results.values()),
        "verified_exact_observations": sum(len(row["verified_exact_fiscal_years"]) for row in results.values()),
        "incorrect_verified_observations": sum(len(row["incorrect_verified_fiscal_years"]) for row in results.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runner", type=Path)
    parser.add_argument("expected", type=Path)
    parser.add_argument("run_record", type=Path)
    parser.add_argument("score_record", type=Path)
    args = parser.parse_args()
    sys.addaudithook(block_sockets)
    result = score(args.runner, args.expected, args.run_record)
    args.score_record.parent.mkdir(parents=True, exist_ok=True)
    with args.score_record.open("xb") as output:
        output.write(json_bytes(result))
    print(f"Replayed {result['replayed_cases']} cases.")
    for strategy, metrics in result.get("strategies", {"model_alone": result}).items():
        print(f"{strategy}: {metrics['exact_observations']}/{result['observations_reviewed']} exact observations.")


if __name__ == "__main__":
    main()
