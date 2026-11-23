"""Run the paired FinQA public test comparison with durable per-question checkpoints."""

import argparse
import json
import socket
import sqlite3
import subprocess
import sys
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager, nullcontext
from functools import partial
from pathlib import Path
from typing import Any

from frag import finqa, finqa_comparison as comparison, finqa_resources as resources, local_model

# Canonical configuration digest from the measured #20 dev comparison.
FROZEN_CONFIGURATION = "08e91acf34301782adffdb4aaf272c4f85b3f78beebf6d4448a76762e9cd3998"


@contextmanager
def _local_planner(directory: Path) -> Iterator[comparison.Planner]:
    executable = directory / "runtime" / "llama-server.exe"
    weights = directory / resources.MODEL["filename"]
    resources._verify_runtime(directory, executable)
    resources._check_digest(weights, resources.MODEL["sha256"])
    with socket.socket() as listener:
        listener.bind((local_model.HOST, 0))
        port = int(listener.getsockname()[1])
    settings = [
        str(executable.resolve()), "--log-disable", "--model", str(weights.resolve()),
        "--alias", resources.MODEL["alias"], "--host", local_model.HOST, "--port", str(port),
        *resources.RUNTIME_ARGS,
    ]
    process = subprocess.Popen(settings, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        resources._wait_until_ready(process, port)
        propose = partial(local_model.propose_lookup, expected_model=resources.MODEL["alias"], port=port)

        def evaluate(request: dict[str, Any]) -> str:
            if process.poll() is not None:
                raise RuntimeError(f"FinQA local server stopped (exit status {process.returncode})")
            return propose(request)

        yield evaluate
    finally:
        process.terminate()
        process.wait(timeout=10)


def _protocol(rows: dict[str, dict[str, Any]], runtime_verified: bool) -> dict[str, Any]:
    configuration = comparison._configuration()
    if finqa._digest(configuration) != FROZEN_CONFIGURATION:
        raise ValueError("Current planner or executor differs from the frozen dev configuration")
    if not rows:
        raise ValueError("The pinned public test split is empty")
    return {
        "version": 1, "split": "test", "upstream": finqa._provenance(), "cohort_ids": list(rows),
        "configuration": configuration, "configuration_sha256": FROZEN_CONFIGURATION,
        "runtime_verified": runtime_verified,
    }


def _summary(protocol: dict[str, Any], modes: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    indexed = {mode: {case["id"]: case for case in cases} for mode, cases in modes.items()}
    paired_ids = [case_id for case_id in protocol["cohort_ids"] if all(case_id in cases for cases in indexed.values())]
    pairs = comparison._summary({
        mode: [cases[case_id] for case_id in paired_ids] for mode, cases in indexed.items()
    })
    coverage = {
        mode: {"completed": len(cases), "expected": len(protocol["cohort_ids"])}
        for mode, cases in modes.items()
    }
    pairs.update(
        modes={mode: finqa._summary(cases) for mode, cases in modes.items()},
        coverage=coverage,
        paired_questions=len(paired_ids),
        elapsed_case_seconds={mode: round(sum(case["elapsed_seconds"] for case in cases), 3)
                              for mode, cases in modes.items()},
    )
    return pairs


def _snapshot(connection: sqlite3.Connection, protocol: dict[str, Any]) -> dict[str, Any]:
    saved: dict[str, dict[str, Any]] = {mode: {} for mode in comparison.MODES}
    ids = set(protocol["cohort_ids"])
    for mode, case_id, payload in connection.execute("SELECT mode, question_id, payload FROM outcome"):
        case = json.loads(payload)
        if mode not in saved or case_id not in ids or case["id"] != case_id:
            raise ValueError("Checkpoint contains an outcome outside the pinned protocol")
        saved[mode][case_id] = case
    modes = {
        mode: [cases[case_id] for case_id in protocol["cohort_ids"] if case_id in cases]
        for mode, cases in saved.items()
    }
    return {**protocol, "modes": modes, "summary": _summary(protocol, modes)}


def run(
    cache: Path, checkpoint: Path, *, model_directory: Path | None = None, planner: comparison.Planner | None = None,
) -> dict[str, Any]:
    """Resume both modes from the same checkpoint in official question order."""
    if (planner is None) == (model_directory is None):
        raise ValueError("Supply either the verified model directory or a test planner")
    rows = finqa._load_split(cache, "test.json")
    protocol = _protocol(rows, model_directory is not None)
    identity = finqa._digest(protocol)
    with closing(sqlite3.connect(checkpoint, timeout=0)) as connection:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE IF NOT EXISTS protocol (id INTEGER PRIMARY KEY CHECK (id = 1), "
                               "identity TEXT NOT NULL, payload TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS outcome (mode TEXT NOT NULL, question_id TEXT NOT NULL, "
                               "payload TEXT NOT NULL, PRIMARY KEY (mode, question_id))")
            connection.execute("INSERT OR IGNORE INTO protocol VALUES (1, ?, ?)", (identity, json.dumps(protocol)))
            saved_identity, saved = connection.execute("SELECT identity, payload FROM protocol").fetchone()
            if saved_identity != identity or finqa._digest(json.loads(saved)) != identity:
                raise ValueError("Checkpoint differs from the frozen public test protocol")
        for mode in comparison.MODES:
            present = {case_id for (case_id,) in connection.execute(
                "SELECT question_id FROM outcome WHERE mode = ?", (mode,),
            )}
            pending = rows.keys() - present
            if not pending:
                continue
            source = _local_planner(model_directory) if model_directory is not None else nullcontext(planner)
            with source as propose:
                assert propose is not None
                for case_id in rows:
                    if case_id not in pending:
                        continue
                    with connection:
                        # Take the write lock before inference to avoid duplicate work on concurrent resume.
                        connection.execute("BEGIN IMMEDIATE")
                        if connection.execute(
                            "SELECT 1 FROM outcome WHERE mode = ? AND question_id = ?", (mode, case_id),
                        ).fetchone():
                            continue
                        case = comparison._case(rows[case_id], mode, propose)
                        connection.execute("INSERT INTO outcome VALUES (?, ?, ?)", (
                            mode, case_id, json.dumps(case, allow_nan=False),
                        ))
        return _snapshot(connection, protocol)


def _checkpoint_snapshot(cache: Path, checkpoint: Path) -> dict[str, Any]:
    rows = finqa._load_split(cache, "test.json")
    with closing(sqlite3.connect(checkpoint.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        identity, payload = connection.execute("SELECT identity, payload FROM protocol").fetchone()
        protocol = json.loads(payload)
        if identity != finqa._digest(protocol) or identity != finqa._digest(_protocol(rows, protocol["runtime_verified"])):
            raise ValueError("Checkpoint differs from the frozen public test protocol")
        return _snapshot(connection, protocol)


def _verify_record(cache: Path, record: dict[str, Any]) -> list[dict[str, Any]]:
    rows = finqa._load_split(cache, "test.json")
    if type(record["runtime_verified"]) is not bool:
        raise ValueError("Public test record has an invalid runtime verification flag")
    protocol = _protocol(rows, record["runtime_verified"])
    if finqa._digest(protocol) != finqa._digest({key: record[key] for key in protocol}):
        raise ValueError("Record differs from the frozen public test protocol")
    modes = record["modes"]
    if set(modes) != set(comparison.MODES):
        raise ValueError("Public test record needs both evidence modes")
    for mode in comparison.MODES:
        cases = modes[mode]
        if [case["id"] for case in cases] != list(rows):
            raise ValueError(f"{mode} needs one outcome per public test ID in official order")
        for row, case in zip(rows.values(), cases, strict=True):
            comparison._verify_case(case, row, mode)
    if record["summary"] != _summary(protocol, modes):
        raise ValueError("Public test record summary differs from replay")
    return list(rows.values())


def _score(cache: Path, rows: list[dict[str, Any]], record: dict[str, Any]) -> dict[str, Any]:
    scores = comparison._score(cache, rows, record)
    parity_verified = all(result["summary"]["parity"] == "verified" for result in scores.values())
    label = "official_upstream" if record["runtime_verified"] and parity_verified else "internal"
    for result in scores.values():
        result["summary"]["score_label"] = label
    return scores


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    evaluate = commands.add_parser("run", help="Run or resume the paired public test evaluation")
    inspect = commands.add_parser("status", help="Inspect checkpoint coverage and paired internal results")
    score = commands.add_parser("score", help="Score a complete checkpoint offline and save a replayable report")
    replay = commands.add_parser("replay", help="Verify the full report offline without starting the model")
    for command in (evaluate, inspect, score, replay):
        command.add_argument("cache", type=Path)
    for command in (evaluate, inspect, score):
        command.add_argument("checkpoint", type=Path)
    for command in (score, replay):
        command.add_argument("report", type=Path)
    evaluate.add_argument("--model-directory", type=Path, default=Path(".frag-model"))
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            record = run(args.cache, args.checkpoint, model_directory=args.model_directory)
        elif args.command == "replay":
            record = comparison._read_record(args.report)
        else:
            record = _checkpoint_snapshot(args.cache, args.checkpoint)
        summary = {key: value for key, value in record["summary"].items() if key != "cases"}
        if args.command in {"score", "replay"}:
            rows = _verify_record(args.cache, record)
            scores = _score(args.cache, rows, record)
            if args.command == "score":
                record["scores"] = scores
                comparison._write_record(args.report, record)
            elif finqa._digest(record["scores"]) != finqa._digest(scores):
                raise ValueError("Public test record scores differ from the pinned upstream scorer")
            summary["scores"] = {mode: result["summary"] for mode, result in scores.items()}
        print(json.dumps(summary))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
