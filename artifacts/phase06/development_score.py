"""Score the Phase 6 development gate against the original reviewed evidence."""

import argparse
import gzip
from hashlib import sha256
import json
from pathlib import Path
from statistics import median
import sys
from typing import Any
from zipfile import ZipFile

PHASE = Path(__file__).resolve().parent
PHASE05 = PHASE.with_name("phase05")
sys.path[:0] = [str(PHASE.parents[1] / "src"), str(PHASE05)]

from holdout_score import classify, growth_presentation
from acceptance_score import MODES, audit_reference, observation_matches
from score import checked_span, position, visible, within
from observations import measure as measure_observations
from revenue_score import score_case


def opened_presentation(case_id: str, label: dict[str, Any]) -> dict[str, Any]:
    label = {**label, "years": list(map(str, label["years"]))}
    if case_id == "P5-02":
        label["period_weeks"] = [52, 53]
    presentation = growth_presentation(label)
    # Render the reviewed comparison disclosures using the Phase 6 answer format.
    caveats = {
        "P5-02": ["SRS results are included from the acquisition date in 2024."],
        "P5-05": ["Both periods use the filing's continuing-operations basis after retrospective "
                  "presentation of discontinued operations."],
        "P5-08": ["Reported net operating revenues reflect bottling refranchising."],
        "P5-11": ["Reported growth includes the effect of the Coyote divestiture in 2024."],
        "P5-13": ["FY2024 includes Splunk revenue from the acquisition date.",
                  "Supplemental pro forma results use the combination period described in Note 4."],
    }
    presentation["scope_caveats"].extend(caveats.get(case_id, []))
    return {**label, "presentation": presentation}


def opened_observations(
    filing: dict[str, Any], original: bytes, review: dict[str, Any], evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    observations = list(review["facts"].values())
    provisional = review.get("provisional_observation")
    if provisional:
        observations.append(provisional)
    statement = review["locators"]["statement"]
    heading = review["locators"]["statement_title_and_units"]
    checked_span(original, statement)
    lines = original.split(b"\n")
    rows = []
    for expected in observations:
        cell = expected["locators"]["statement_cell"]
        checked_span(original, cell)
        matches = [fact for fact in evidence["facts"] if observation_matches(fact, expected, lines)
                   and fact["source_id"] == f'sha256:{filing["sha256"]}'
                   and within(position(lines, fact["locators"]["table"]), statement)
                   and within(position(lines, fact["locators"]["year_header"]), review["locators"]["period_header"])]
        fact = matches[0] if len(matches) == 1 else None
        rows.append({
            "accession": filing["accession"], "original": filing["original_filename"],
            "sha256": filing["sha256"], "statement": visible(checked_span(original, heading)),
            "statement_locator": statement, "statement_row": review["statement_row"],
            "cell_locator": cell, "expected": expected,
            "extraction_matched": fact is not None,
            "expected_verification_status": "provisional" if expected is provisional else "verified",
            "observed": {key: fact[key] for key in (
                "fact_id", "status", "raw_amount", "normalized_amount", "reporting_period",
                "currency", "scale", "locators", "unresolved_requirements",
            )} if fact else None,
        })
    return rows


def summarize_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    numeric = [row for row in cases if row["numeric_answer_emitted"]]
    latency = [row["elapsed_ms"] for row in cases]
    return {
        "accuracy": [sum(row["answer_accurate"] for row in cases),
                     sum(row["expected_outcome"] == "answerable" for row in cases)],
        "supported_answers": sum(row["end_to_end_complete"] for row in numeric),
        "citation_support_emitted": [sum(row["citations_supported"] for row in numeric), len(numeric)],
        "grounded_abstentions": sum(row["grounded_abstention"] and row["end_to_end_complete"] for row in cases),
        "coverage": [len(numeric), len(cases)],
        "end_to_end": [sum(row["end_to_end_complete"] for row in cases), len(cases)],
        "offline_replay": [sum(row["offline_replay_matched"] for row in cases), len(cases)],
        "planner_calls": sum(row["model_request_sent"] for row in cases),
        "latency_ms": {"min": min(latency), "median": median(latency), "max": max(latency)},
    }


def stop_details(run: dict[str, Any], stages: dict[str, Any]) -> dict[str, Any]:
    result = run["result"]
    reasons = [issue["code"] for issue in result.get("issues", [])]
    if result.get("reason"):
        reasons.append(result["reason"])
    stage = stages["first_failure_stage"]
    if stage == "complete" and reasons:
        stage = {
            "absent": "statement_period_inventory",
            "incompatible": "comparison_compatibility",
            "unverified": "verification" if any(stages["observations_extracted"].values()) else "extraction",
        }.get(reasons[0], "abstention")
    return {"stage": stage, "reasons": reasons}


def score_pass(
    mode: str, live: dict[str, Any], replay: dict[str, Any], baseline: dict[str, Any],
    baseline_live: dict[str, Any], labels: dict[str, Any], originals: dict[str, tuple[bytes, str]],
) -> dict[str, Any]:
    historical = {row["case_id"]: row for row in baseline[mode]["cases"]}
    cases, baseline_cases = [], []
    for live_row, replay_row, baseline_row in zip(live["cases"], replay["cases"], baseline_live["cases"], strict=True):
        case = live_row["case"]
        case_id, key = case["case_id"], case["source_id"]
        original, original_hash = originals[key]
        run, repeated, baseline_run = live_row[mode], replay_row[mode], baseline_row[mode]
        evidence = live["sources"][key]["evidence"]
        label, review = labels["cases"][case_id], labels["sources"][key]
        scored = score_case(run, repeated, evidence, label, review, original, original_hash)
        # A reviewed provisional observation can establish extraction, even when it cannot support an answer.
        stage_review = review
        if provisional := review.get("provisional_observation"):
            stage_review = {**review, "facts": {**review["facts"], str(provisional["fiscal_year"]): provisional}}
        stages = classify(run, evidence, stage_review, original, label, scored)
        baseline_scored = historical[case_id]
        baseline_evidence = baseline_live["sources"][key]["evidence"]
        baseline_stages = classify(baseline_run, baseline_evidence, stage_review, original, label, baseline_scored)
        if "first_failure_stage" in baseline_scored:
            baseline_stages["first_failure_stage"] = baseline_scored["first_failure_stage"]
        baseline_cases.append({**baseline_scored, "elapsed_ms": baseline_run["elapsed_ms"],
                               "model_request_sent": baseline_stages["model_request_sent"]})
        cases.append({
            **case, **scored, **stages,
            "elapsed_ms": run["elapsed_ms"], "opened_citations": len(run["citations"]),
            "stop": stop_details(run, stages),
            "baseline_completed": baseline_scored["end_to_end_complete"],
            "baseline_status": baseline_scored["status"],
            "baseline_stop": stop_details(baseline_run, baseline_stages),
            "baseline_elapsed_ms": baseline_run["elapsed_ms"],
        })
    return {"metrics": summarize_cases(cases), "baseline_metrics": summarize_cases(baseline_cases), "cases": cases}


def memory_peaks(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "peak_working_set_mib": {name: max(row["peak_working_set_mib"][name] for row in report["cases"])
                                 for name in ("runner", "planner")},
        "peak_device_vram_mib": max(row["peak_device_vram_mib"] for row in report["cases"]),
    }


def score_cohort(
    cohort: str, work: Path, manifest: dict[str, Any], labels: dict[str, Any],
    originals: dict[str, tuple[bytes, str]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    live_bytes = (work / f"{cohort}-live.json").read_bytes()
    replay_bytes = (work / f"{cohort}-replay/report.json").read_bytes()
    live, replay = json.loads(live_bytes), json.loads(replay_bytes)
    if (replay.get("live_sha256") != sha256(live_bytes).hexdigest() or live["freeze"] != replay["freeze"]
            or any([row["case"] for row in report["cases"]] != manifest["cases"]
                   or report["sources"].keys() != originals.keys() for report in (live, replay))
            or any(source["evidence"] != replay["sources"][key]["evidence"]
                   for key, source in live["sources"].items())):
        raise ValueError(f"{cohort} reports do not bind to the original inputs and replay")
    baseline_path = PHASE / f"{cohort}-score.json"
    baseline = json.loads(baseline_path.read_bytes())
    baseline_live = json.loads(gzip.decompress((PHASE / f"{cohort}-live.json.gz").read_bytes()))
    if [row["case"] for row in baseline_live["cases"]] != manifest["cases"]:
        raise ValueError(f"{cohort} cases differ from the baseline")
    report = {
        "settings": live["freeze"], "live_sha256": sha256(live_bytes).hexdigest(),
        "replay_sha256": sha256(replay_bytes).hexdigest(), "baseline_score_sha256": sha256(baseline_path.read_bytes()).hexdigest(),
        **memory_peaks(live), "baseline_memory_peaks": memory_peaks(baseline_live),
        **{mode: score_pass(mode, live, replay, baseline, baseline_live, labels, originals) for mode in MODES},
    }
    return report, live["sources"]


def score_opened(work: Path, expected_path: Path) -> dict[str, Any]:
    receipt_path = PHASE05 / "sec-holdout-receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    runner_path = work / "opened-inputs.zip"
    for role, path in (("runner", runner_path), ("scorer", expected_path)):
        if sha256(path.read_bytes()).hexdigest() != receipt[f"{role}_bundle"]["sha256"]:
            raise ValueError(f"Opened {role} archive differs from the custody receipt")
    with ZipFile(runner_path) as runner, ZipFile(expected_path) as scorer:
        manifest = json.loads(runner.read("manifest.json"))
        labels = json.loads(scorer.read("expected.json"))
        originals = {filing["source_id"]: (runner.read(filing["path"]), filing["sha256"])
                     for filing in manifest["sources"]}
    labels["cases"] = {key: opened_presentation(key, label) for key, label in labels["cases"].items()}
    for filing in manifest["sources"]:
        key = filing["source_id"]
        audit_reference(originals[key][0], filing, labels["sources"][key])
    report, sources = score_cohort("opened", work, manifest, labels, originals)
    observations = []
    for filing in manifest["sources"]:
        key = filing["source_id"]
        observations.extend(opened_observations(filing, originals[key][0], labels["sources"][key], sources[key]["evidence"]))
    report["observations"] = observations
    report["reviewed_observations"] = len(observations)
    report["extraction_matches"] = sum(row["extraction_matched"] for row in observations)
    report["verified_facts"] = sum(row["observed"] is not None and row["observed"]["status"] == "verified"
                                   for row in observations)
    report["reference_sha256"] = receipt["scorer_bundle"]["sha256"]
    return report


def score_earlier(work: Path) -> dict[str, Any]:
    manifest = json.loads((PHASE05 / "inputs.json").read_bytes())
    reference = (PHASE05 / "expected.json").read_bytes()
    frozen = json.loads((PHASE / "earlier-freeze.json").read_bytes())
    if sha256(reference).hexdigest() != frozen["reference_sha256"]:
        raise ValueError("Earlier reference differs from the baseline")
    labels = json.loads(reference)
    presentation = json.loads((PHASE05 / "acceptance-text.json").read_bytes())
    originals = {}
    for filing in manifest["sources"]:
        key = filing["source_id"]
        original = gzip.decompress((PHASE.parents[1] / filing["archive"]).read_bytes())
        audit_reference(original, filing, labels["sources"][key])
        originals[key] = original, filing["sha256"]
    for case_id, label in labels["cases"].items():
        label["presentation"] = presentation.get(case_id, {})
    report, sources = score_cohort("earlier", work, manifest, labels, originals)
    report["observations"] = measure_observations(
        [(filing, originals[filing["source_id"]][0]) for filing in manifest["sources"]], labels["sources"], sources,
    )
    report["reference_sha256"] = frozen["reference_sha256"]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path)
    parser.add_argument("expected", type=Path)
    args = parser.parse_args()
    opened = score_opened(args.work, args.expected)
    earlier = score_earlier(args.work)
    passed = (opened["reviewed_observations"] == opened["extraction_matches"] == 19
              and all(row["observed"]["status"] == row["expected_verification_status"] for row in opened["observations"])
              and all(opened[mode]["metrics"]["end_to_end"] == [15, 15]
                      and opened[mode]["metrics"]["supported_answers"] == 12
                      and opened[mode]["metrics"]["grounded_abstentions"] == 3
                      and earlier[mode]["metrics"]["offline_replay"] == [15, 15]
                      and all(row["end_to_end_complete"] or (row["case_id"] == "aapl-2024-present" and row["incomplete"])
                              for row in earlier[mode]["cases"]) for mode in MODES))
    report = {"passed": passed, "opened": opened, "earlier": earlier,
              "scorer_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
              "case_scorer_sha256": sha256((PHASE / "revenue_score.py").read_bytes()).hexdigest()}
    with (args.work / "gate-score.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    for cohort in ("opened", "earlier"):
        for mode in MODES:
            print(cohort, mode, report[cohort][mode]["metrics"])
    return int(not passed)


if __name__ == "__main__":
    raise SystemExit(main())
