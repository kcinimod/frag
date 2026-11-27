"""Recheck the fresh cohort in scorer custody before releasing runner inputs."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile


PHASE = Path("artifacts/phase06")
RECEIPT = PHASE / "continuation-holdout-receipt.json"


def verify_custody(repo: Path, production: str, evaluation: str, custody: Path, runner: Path) -> None:
    receipt_bytes = (runner / RECEIPT).read_bytes()
    receipt = json.loads(receipt_bytes)
    for name in ("development_gate_record", "development_layout_inventory"):
        evidence = (runner / receipt[f"{name}_path"]).read_bytes()
        if sha256(evidence).hexdigest() != receipt[f"{name}_sha256"]:
            raise ValueError(f"Development evidence differs from the sealed {name}.")
    if json.loads((runner / receipt["development_gate_record_path"]).read_bytes())["passed"] is not True:
        raise ValueError("The opened-cohort development gate did not pass.")
    # The preparation audit includes the earlier SEC reserves and opened #44
    # inventories. Require the final candidate's evidence and references to
    # match the audited snapshot, apart from #54's own custody records.
    subprocess.run(
        ["git", "-C", str(repo), "diff", "--exit-code", "--name-only",
         receipt["preparation_base"], production, "--", "src", "tests", "artifacts",
         ":(exclude)artifacts/phase06/CONTINUATION_HOLDOUT.md",
         ":(exclude)artifacts/phase06/README.md", f":(exclude){RECEIPT.as_posix()}"],
        check=True,
    )
    inputs = (custody / receipt["runner_bundle"]["path"]).resolve(strict=True)
    expected = (custody / receipt["scorer_bundle"]["path"]).resolve(strict=True)
    if any(path.is_relative_to(runner.resolve()) for path in (inputs, expected)):
        raise ValueError("Both custody bundles must remain outside the runner workspace during the audit.")
    if sha256(expected.read_bytes()).hexdigest() != receipt["scorer_bundle"]["sha256"]:
        raise ValueError("The independent scoring archive differs from its seal.")
    with ZipFile(expected) as archive:
        program = archive.read("verify.py")
    if sha256(program).hexdigest() != receipt["audit_sha256"]["verify.py"]:
        raise ValueError("The custody verifier differs from its seal.")
    namespace: dict = {"__name__": "sealed_custody_verifier"}
    exec(compile(program, "verify.py", "exec"), namespace)
    namespace["verify"](receipt, inputs, expected)
    record = {
        "passed": True,
        "cohort": receipt["cohort"],
        "production_revision": production,
        "evaluation_revision": evaluation,
        "development_inventory_revision": receipt["preparation_base"],
        "receipt_sha256": sha256(receipt_bytes).hexdigest(),
        **{name: receipt[name] for name in (
            "case_count", "issuer_count", "original_count", "lineage_accession_count",
            "observation_count", "statement_layout_count", "new_statement_layout_count",
        )},
        "overlapping_issuer_families": 0,
        "overlapping_originals": 0,
    }
    with (runner / "continuation-audit.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(record, stream, indent=2, sort_keys=True)
        stream.write("\n")


if __name__ == "__main__":
    repo_arg, production_arg, evaluation_arg, custody_arg, runner_arg = sys.argv[1:]
    verify_custody(Path(repo_arg), production_arg, evaluation_arg, Path(custody_arg), Path(runner_arg))
