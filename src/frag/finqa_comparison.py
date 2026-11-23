"""Run and replay the paired FinQA evidence comparison on official dev IDs."""

import argparse
import gzip
import json
import re
import sys
from collections import Counter
from dataclasses import asdict
from functools import partial
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Sequence

from frag import finqa, finqa_scoring, local_model
from frag.finqa_program import Excerpt
from frag.finqa_resources import MODEL, RUNTIME_ARGS, RUNTIME_SHA256, measure

ANNOTATED = finqa.MODE
RETRIEVED = "retrieved_evidence"
MODES = (ANNOTATED, RETRIEVED)
WORDS = re.compile(r"[^\W_]+", re.UNICODE)
STOP_WORDS = frozenset(
    "a an and are as at be by did do does for from had has have how in is it of on or that "
    "the their to was were what when where which who will with would".split()
)
Planner = Callable[[dict[str, Any]], str]


def _keywords(text: str) -> set[str]:
    return set(WORDS.findall(text.casefold())) - STOP_WORDS


def _retrieve(question: str, passages: list[str], table: list[list[str]]) -> tuple[list[Excerpt], list[dict[str, Any]]]:
    candidates = [
        *(Excerpt(f"text_{index}", passage) for index, passage in enumerate(passages)),
        *(Excerpt(f"table_{index}", tuple(cells)) for index, cells in enumerate(table[1:], 1)),
    ]
    terms = _keywords(question)
    ranked = []
    for excerpt in candidates:
        source = excerpt.source
        matched = sorted(terms & _keywords(source if isinstance(source, str) else " ".join(source)))
        ranked.append((excerpt, matched))
    # Stable sort keeps passage order, then table row order, among ties.
    ranked.sort(key=lambda entry: -len(entry[1]))
    excerpts = [excerpt for excerpt, matches in ranked if matches]
    if any(excerpt.id.startswith("table_") for excerpt in excerpts):
        excerpts.insert(0, Excerpt("table_0", tuple(table[0])))
    return excerpts, [{"id": excerpt.id, "matched_terms": matches} for excerpt, matches in ranked]


def _evidence(row: dict[str, Any], mode: str) -> tuple[list[Excerpt], list[dict[str, Any]]]:
    if mode == ANNOTATED:
        excerpts = finqa._annotated_excerpts(row)
        return excerpts, [{"id": excerpt.id} for excerpt in excerpts]
    return _retrieve(row["qa"]["question"], row["pre_text"] + row["post_text"], row["table"])


def _evidence_losses(case: dict[str, Any]) -> dict[str, list[str]]:
    eligible = {excerpt["id"] for excerpt in case["source_excerpts"]}
    omitted = set(case["omitted_excerpt_ids"])
    return {
        "ranking": [locator for locator in case["annotated_ids"] if locator not in eligible],
        "context": [locator for locator in case["annotated_ids"] if locator in omitted],
    }


def _case(row: dict[str, Any], mode: str, planner: Planner) -> dict[str, Any]:
    started = perf_counter()
    excerpts, ranking = _evidence(row, mode)
    case = finqa._run_case(row, excerpts, model=MODEL["alias"], planner=planner)
    return {**case, "ranking": ranking, "annotated_evidence_omitted": _evidence_losses(case),
            "elapsed_seconds": round(perf_counter() - started, 3)}


def _configuration() -> dict[str, Any]:
    request, _, _ = finqa._planner_input("", [], MODEL["alias"])
    return {
        "model": MODEL, "runtime_arguments": RUNTIME_ARGS, "runtime_sha256": RUNTIME_SHA256,
        "runtime_fingerprint": local_model.RUNTIME_FINGERPRINT, "timeout_seconds": local_model.TIMEOUT_SECONDS,
        "request_template": request, "context_bytes": finqa.CONTEXT_BYTES, "demonstration_ids": [],
        "retrieval": "distinct question keyword overlap, positive rows and passages, stable source-order ties",
        "quality_targets": None,
        "implementation_digests": {
            name: finqa._digest(Path(__file__).with_name(name).read_text(encoding="utf-8-sig"))
            for name in ("finqa.py", "finqa_comparison.py", "finqa_program.py", "finqa_resources.py", "finqa_scoring.py")
        },
    }


def _dev_rows(cache: Path, ids: list[str]) -> list[dict[str, Any]]:
    dev = finqa._load_split(cache, "dev.json")
    if (not isinstance(ids, list) or not ids or not all(isinstance(item, str) for item in ids)
            or len(set(ids)) != len(ids) or any(question_id not in dev for question_id in ids)):
        raise ValueError("Provide unique question IDs from the official dev split")
    return [dev[question_id] for question_id in ids]


def _stage(case: dict[str, Any]) -> str:
    status = str(case["outcome"]["status"])
    if status == "executed":
        return "correct" if case["internal_answer_match"] else "answer_mismatch"
    return status


def _summary(modes: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    cases = []
    for annotated, retrieved in zip(modes[ANNOTATED], modes[RETRIEVED], strict=True):
        left, right = annotated["internal_answer_match"], retrieved["internal_answer_match"]
        transition = {(True, True): "both_correct", (True, False): "retrieval_regression",
                      (False, True): "retrieval_improvement", (False, False): "both_incorrect"}[left, right]
        cases.append({"id": annotated["id"], ANNOTATED: _stage(annotated), RETRIEVED: _stage(retrieved),
                      "answer_transition": transition,
                      "retrieved_annotated_evidence_omitted": retrieved["annotated_evidence_omitted"]})
    counts = Counter(case["answer_transition"] for case in cases)
    return {"cases": cases, "answer_transitions": dict(counts),
            "modes": {mode: finqa._summary(mode_cases) for mode, mode_cases in modes.items()}}


def run(
    cache: Path, ids: list[str], *, planner: Planner | None = None, model_directory: Path | None = None,
) -> dict[str, Any]:
    """Compare the same dev IDs with a supplied planner or the pinned Windows runtime."""
    rows = _dev_rows(cache, ids)
    configuration = _configuration()
    modes: dict[str, list[dict[str, Any]]] = {}
    measurements = {}
    for mode in MODES:
        def evaluate(row: dict[str, Any], port: int | None = None) -> dict[str, Any]:
            propose = planner or partial(local_model.propose_lookup, expected_model=MODEL["alias"], port=port)
            return _case(row, mode, propose)

        if model_directory is None:
            modes[mode] = [evaluate(row) for row in rows]
        else:
            if planner is not None:
                raise ValueError("Resource measurement uses the pinned planner")
            modes[mode], measurements[mode] = measure(model_directory, rows, evaluate)
    return {
        "version": 1, "split": "dev", "upstream": finqa._provenance(), "cohort_ids": ids,
        "configuration": configuration, "modes": modes, "measurements": measurements,
        "summary": _summary(modes),
    }


def _verify_case(case: dict[str, Any], row: dict[str, Any], mode: str) -> None:
    excerpts, ranking = _evidence(row, mode)
    qa = row["qa"]
    if (case["id"] != row["id"] or case["source_page"] != row["filename"]
            or case["question"] != qa["question"] or case["annotated_ids"] != list(qa["gold_inds"])
            or case["reference"] != {"execution_answer": qa["exe_ans"], "program": qa["program"]}
            or finqa._digest(case["source_excerpts"]) != finqa._digest([asdict(excerpt) for excerpt in excerpts])
            or case["ranking"] != ranking or case["annotated_evidence_omitted"] != _evidence_losses(case)):
        raise ValueError(f'{case["id"]} {mode} differs from the pinned question, evidence or references')
    finqa._replay_case(case, excerpts, MODEL["alias"])


def _score(cache: Path, rows: list[dict[str, Any]], record: dict[str, Any]) -> dict[str, Any]:
    return {
        mode: finqa_scoring.score_cases(
            cache / "evaluate.py", finqa.SCORER_SHA256, {case["id"]: case for case in record["modes"][mode]}, rows,
        )
        for mode in MODES
    }


def replay(cache: Path, record: dict[str, Any]) -> dict[str, Any]:
    """Rebuild evidence ranking, requests, outcomes and any saved upstream scores offline."""
    if (record["version"] != 1 or record["split"] != "dev" or record["upstream"] != finqa._provenance()
            or finqa._digest(record["configuration"]) != finqa._digest(_configuration())):
        raise ValueError("Comparison record differs from the frozen protocol")
    rows = _dev_rows(cache, record["cohort_ids"])
    if set(record["modes"]) != set(MODES) or set(record["measurements"]) not in (set(), set(MODES)):
        raise ValueError("Comparison record needs both evidence modes")
    for mode in MODES:
        cases = record["modes"][mode]
        if len(cases) != len(rows):
            raise ValueError("Comparison record needs one outcome per cohort ID in each mode")
        for row, case in zip(rows, cases, strict=True):
            _verify_case(case, row, mode)
        if mode in record["measurements"]:
            _verify_case(record["measurements"][mode]["cold_case"], rows[0], mode)
    summary = _summary(record["modes"])
    if summary != record["summary"]:
        raise ValueError("Comparison record summary differs from replay")
    if "scores" in record and finqa._digest(_score(cache, rows, record)) != finqa._digest(record["scores"]):
        raise ValueError("Comparison record scores differ from the upstream scorer")
    return summary


def _read_record(path: Path) -> dict[str, Any]:
    encoded = path.read_bytes()
    record: dict[str, Any] = json.loads(gzip.decompress(encoded) if path.suffix == ".gz" else encoded)
    return record


def _write_record(path: Path, record: dict[str, Any]) -> None:
    encoded = (json.dumps(record, indent=2, allow_nan=False) + "\n").encode("utf-8")
    with path.open("xb") as output:
        output.write(gzip.compress(encoded, mtime=0) if path.suffix == ".gz" else encoded)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    compare = commands.add_parser("run", help="Measure both evidence modes on the Windows dev cohort")
    compare.add_argument("cache", type=Path)
    compare.add_argument("record", type=Path)
    compare.add_argument("--cohort", type=Path, required=True)
    compare.add_argument("--model-directory", type=Path, default=Path(".frag-model"))
    offline = commands.add_parser("replay", help="Verify a saved comparison without calling the planner")
    offline.add_argument("cache", type=Path)
    offline.add_argument("record", type=Path)
    score = commands.add_parser("score", help="Score a saved comparison offline with the pinned evaluator")
    score.add_argument("cache", type=Path)
    score.add_argument("record", type=Path)
    score.add_argument("report", type=Path, help="New copy of the comparison with upstream scores")
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            if args.record.exists():
                raise ValueError("Choose a new comparison record path")
            ids = json.loads(args.cohort.read_bytes())
            record = run(args.cache, ids, model_directory=args.model_directory)
            _write_record(args.record, record)
            summary = record["summary"]
        else:
            record = _read_record(args.record)
            summary = replay(args.cache, record)
            if args.command == "score":
                if args.report.exists():
                    raise ValueError("Choose a new comparison report path")
                record["scores"] = _score(args.cache, _dev_rows(args.cache, record["cohort_ids"]), record)
                _write_record(args.report, record)
                summary = {mode: result["summary"] for mode, result in record["scores"].items()}
    except (OSError, ValueError, KeyError, IndexError, TypeError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
