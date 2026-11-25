"""Score both passes of the sealed Phase 5 acceptance evaluation."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from statistics import median
import sys
from typing import Any
from zipfile import ZipFile

from acceptance_score import (
    MODES, observation_matches, score_case, unpack_report,
)

GENERIC_CAVEAT = "Growth uses reported consolidated amounts, including any effects of exchange rates or acquisitions."
GENERIC_BASIS = "Consecutive annual consolidated revenue amounts from the same statement and reporting basis."


def growth_presentation(label: dict[str, Any]) -> dict[str, Any]:
    caveats = [GENERIC_CAVEAT]
    weeks = label.get("period_weeks") or []
    if len(weeks) == 2 and weeks[0] != weeks[1]:
        prior, current = label["years"]
        caveats.append(f"FY{prior} spans {weeks[0]} weeks and FY{current} spans {weeks[1]} weeks. "
                       "Growth uses the fiscal years as reported.")
    return {"comparison_basis": GENERIC_BASIS, "scope_caveats": caveats}


def evidence_gap(text: str, year: str, present: dict[str, Any], evidence: dict[str, Any]) -> bool:
    if not text.startswith(f"FY{year} revenue evidence gap. "):
        return False
    candidates = [fact for fact in evidence.get("facts", []) if
                  str(fact.get("reporting_period", {}).get("fiscal_year")) == year]
    if any(fact.get("status") == "verified" for fact in candidates) or len(candidates) > 1:
        return False
    explanations = {
        "The available evidence did not establish the statement periods or a revenue observation.": not candidates,
        "The statement shows this year, but extraction did not produce a revenue observation.": not candidates and year in present,
        "The extracted observation could not be verified.": bool(candidates),
    }
    for explanation, valid in explanations.items():
        prefix = f"FY{year} revenue evidence gap. {explanation}"
        if valid and (text == prefix or text.startswith(prefix + " ")):
            # Accept only claims about the workflow's evidence requirements.
            # Parser diagnostics which assert a filing fact require independent review.
            allowed = {
                "The applicable filing disclosures need verification.",
                "Expected exactly one table headed Income Statements.",
                "Expected one visible consolidated income statement.",
                "Expected one total revenue row in the consolidated statement.",
                "Expected a full fiscal year-end date in the statement.",
                "Expected one shared fiscal year-end above the revenue row.",
                "Expected one inline XBRL observation in the revenue cell.",
                "The selected filing layout requires an inline XBRL tag for numeric revenue.",
                "Source identity verification.",
                "Statement issuer verification.",
            }
            remainder = text[len(prefix):].strip()
            while remainder:
                phrase = next((item for item in allowed if remainder == item or remainder.startswith(item + " ")), None)
                if phrase is None:
                    return False
                remainder = remainder[len(phrase):].strip()
            return True
    return False


def truthful_gap(result: dict[str, Any], label: dict[str, Any], reference: dict[str, Any],
                 evidence: dict[str, Any]) -> bool:
    years = label["years"]
    if label["kind"] == "lookup":
        return (result.get("status") == "evidence_unavailable" and result.get("reason") == "unverified"
                and evidence_gap(result.get("message", ""), years[0], reference["facts"], evidence))
    issues = result.get("issues", [])
    roles = dict(zip(("prior", "current"), years, strict=True))
    return result.get("status") == "unavailable" and bool(issues) and all(
        item.get("code") == "unverified" and item.get("role") in roles
        and str(item.get("fiscal_year")) == roles[item["role"]]
        and evidence_gap(item.get("detail", ""), roles[item["role"]], reference["facts"], evidence)
        for item in issues
    )


def classify(run: dict[str, Any], evidence: dict[str, Any], expected: dict[str, Any],
             original: bytes, label: dict[str, Any], scored: dict[str, Any]) -> dict[str, Any]:
    record = run.get("record") or {}
    lines = original.split(b"\n")
    requested = {year: expected["facts"][year] for year in label["years"] if year in expected["facts"]}
    extracted = {
        year: [fact for fact in evidence.get("facts", []) if observation_matches(fact, fact_ref, lines)]
        for year, fact_ref in requested.items()
    }
    verified = {year: [fact["fact_id"] for fact in facts if fact.get("status") == "verified"]
                for year, facts in extracted.items()}
    eligible = [fact["fact_id"] for fact in record.get("evidence", [])]
    model_request = record.get("model_request") is not None
    proposal = record.get("proposed_plan") is not None
    findings = scored["findings"]
    if findings == ["offline_replay_mismatch"]:
        stage = "offline_replay"
    elif scored["end_to_end_complete"]:
        stage = "complete"
    elif scored["numeric_answer_emitted"]:
        stage = "execution" if "wrong_answer" in findings else "presentation"
    elif scored["status"] == "clarify":
        stage = "request_resolution"
    elif any(not facts for facts in extracted.values()):
        stage = "extraction"
    elif any(not ids for ids in verified.values()):
        stage = "verification"
    elif any(not set(ids).intersection(eligible) for ids in verified.values()):
        stage = "retrieval"
    elif model_request:
        stage = "execution" if proposal and scored["status"] != "invalid_plan" else "planning"
    elif scored["status"] == "unavailable":
        stage = "comparison_or_abstention"
    else:
        stage = "context_assembly"
    return {
        "first_failure_stage": stage,
        "observations_extracted": {year: bool(facts) for year, facts in extracted.items()},
        "observations_verified": {year: bool(ids) for year, ids in verified.items()},
        "eligible_fact_ids": eligible, "model_request_sent": model_request, "proposal_returned": proposal,
        "validation_status": record.get("validation_status"),
        "intake_diagnostics": [item["code"] for item in evidence.get("diagnostics", [])],
        "open_requirements": evidence.get("unresolved_requirements", []),
    }


def score_pass(mode: str, live: dict[str, Any], replay: dict[str, Any], manifest: dict[str, Any],
               labels: dict[str, Any], originals: dict[str, bytes], freeze: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for case, live_row, replay_row in zip(manifest["cases"], live["cases"], replay["cases"], strict=True):
        key, case_id = case["source_id"], case["case_id"]
        run, repeated = live_row[mode], replay_row[mode]
        evidence = live["sources"][key]["evidence"]
        label = dict(labels["cases"][case_id])
        label["years"] = list(map(str, label["years"]))
        reference, original = labels["sources"][key], originals[key]
        label["presentation"] = growth_presentation(label)
        scored = score_case(run, repeated, evidence, label, reference, original, sha256(original).hexdigest())
        if (label["outcome"] in {"answerable", "present_unverifiable"}
                and truthful_gap(run["result"], label, reference, evidence)):
            findings = scored["findings"]
            if "contradicted_abstention" in findings:
                findings.remove("contradicted_abstention")
                if label["outcome"] == "present_unverifiable" and scored["citations_supported"] and not findings:
                    scored["grounded_abstention"] = scored["end_to_end_complete"] = True
        rows.append({"case_id": case_id, **scored, **classify(run, evidence, reference, original, label, scored)})
    numeric = [row for row in rows if row["numeric_answer_emitted"]]
    supported = sum(row["end_to_end_complete"] for row in numeric)
    grounded = sum(row["grounded_abstention"] and row["end_to_end_complete"] for row in rows)
    latency = [row[mode]["elapsed_ms"] for row in live["cases"] if "elapsed_ms" in row[mode]]
    thresholds = freeze["thresholds_per_pass"]
    return {
        "accepted": supported >= thresholds["supported_answers"] and grounded >= thresholds["grounded_abstentions"]
        and not any(row["findings"] for row in rows),
        "metrics": {
            "accuracy": [sum(row["answer_accurate"] for row in rows),
                         sum(row["expected_outcome"] == "answerable" for row in rows)],
            "supported_answers": supported,
            "citation_support_emitted": [sum(row["citations_supported"] for row in numeric), len(numeric)],
            "grounded_abstentions": grounded, "coverage": [len(numeric), len(rows)],
            "end_to_end": [sum(row["end_to_end_complete"] for row in rows), len(rows)],
            "offline_replay": [sum(row["offline_replay_matched"] for row in rows), len(rows)],
        },
        "latency_ms": {"min": min(latency), "median": median(latency), "max": max(latency)} if latency else None,
        "stages": dict(Counter(row["first_failure_stage"] for row in rows)),
        "findings": dict(Counter(code for row in rows for code in row["findings"])),
        "cases": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("freeze", "runner", "scorer", "live", "replay", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    frozen_bytes = args.freeze.read_bytes()
    freeze = json.loads(frozen_bytes)
    for name, expected in freeze["scoring_files"].items():
        if sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() != expected:
            parser.error("Scorer code differs from the freeze.")
    receipt = freeze["receipt"]
    archive_hashes = {}
    for role in ("runner", "scorer"):
        value = sha256(getattr(args, role).read_bytes()).hexdigest()
        if value != receipt[f"{role}_bundle"]["sha256"]:
            parser.error(f"{role.title()} archive differs from the custody receipt.")
        archive_hashes[role] = value
    live_bytes, replay_bytes = [unpack_report(path.read_bytes()) for path in (args.live, args.replay)]
    live, replay = json.loads(live_bytes), json.loads(replay_bytes)
    live_hash = sha256(live_bytes).hexdigest()
    with ZipFile(args.runner) as runner, ZipFile(args.scorer) as scorer:
        raw_manifest = runner.read("manifest.json")
        manifest = json.loads(raw_manifest)
        binding = {"freeze_sha256": sha256(frozen_bytes).hexdigest(), "runner_sha256": archive_hashes["runner"],
                   "manifest_sha256": sha256(raw_manifest).hexdigest()}
        if (replay.get("live_sha256") != live_hash
                or any(report["freeze"] != freeze or report["binding"] != binding
                       or [row["case"] for row in report["cases"]] != manifest["cases"] for report in (live, replay))
                or live["sources"].keys() != replay["sources"].keys()
                or live["sources"].keys() != {source["source_id"] for source in manifest["sources"]}
                or any(row["evidence"] != replay["sources"][key]["evidence"] for key, row in live["sources"].items())):
            parser.error("Reports, reingested evidence or cases differ from the freeze.")
        # The custody verifier independently reopens the source and expected spans.
        sys.argv = ["verify.py", str(Path(__file__).with_name("sec-holdout-receipt.json")),
                    str(args.runner), str(args.scorer)]
        try:
            exec(compile(scorer.read("verify.py"), "verify.py", "exec"), {"__name__": "__main__"})
        except SystemExit as error:
            if error.code not in (0, None):
                raise
        labels = json.loads(scorer.read("expected.json"))
        originals = {source["source_id"]: runner.read(source["path"]) for source in manifest["sources"]}
    report = {
        "binding": binding, "scorer_bundle_sha256": archive_hashes["scorer"],
        "live_sha256": live_hash, "replay_sha256": sha256(replay_bytes).hexdigest(),
        "peak_working_set_mib": {key: max(row["peak_working_set_mib"][key] for row in live["cases"])
                                 for key in ("runner", "planner")},
        "peak_device_vram_mib": max(row["peak_device_vram_mib"] for row in live["cases"]),
        "thresholds_per_pass": freeze["thresholds_per_pass"],
        **{mode: score_pass(mode, live, replay, manifest, labels, originals, freeze) for mode in MODES},
    }
    report["accepted"] = all(report[mode]["accepted"] for mode in MODES)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({mode: report[mode]["metrics"] for mode in MODES}))
    return int(not report["accepted"])


if __name__ == "__main__":
    raise SystemExit(main())
