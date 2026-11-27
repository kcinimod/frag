# Phase 6 evidence scoring revision

Issue [#51](https://github.com/kcinimod/frag/issues/51) adds
`phase06-evidence-v2` for scoring retained results against the sealed independent
references. The [#44 acceptance record](SEC_ACCEPTANCE.md) remains the
historical decision.

| Retained measurement | Cold | Warm |
| --- | ---: | ---: |
| Supported numeric answers | 0/12 | 0/12 |
| Grounded abstentions | 0/3 | 0/3 |
| Supported citations | 1 | 1 |
| Supported companions | 0 | 0 |
| Incomplete findings | 8 cases | 8 cases |
| Recorded exact replay matches | 15/15 | 15/15 |

The corrected score still fails the gate in both passes. The shared
observation audit matches 3/21 extracted observations and 0/21 reusable
verifications. Both passes stop at request resolution for seven cases,
extraction for six, and verification for two.

- **P6-13, Netflix FY2021 absence.** The enclosing heading element opens
  the independently reviewed consolidated statement heading. The period
  inventory citation earns credit in both passes. The required verified
  FY2024 companion is missing, so the result stops at verification.
- **P6-14, NVIDIA FY2018.** The result stops at extraction. Its evidence
  gap is incomplete because it never establishes the displayed observation
  and the independently reviewed reason it remains provisional.

`supported_citation_ids` and `supported_companions` record evidence credit.
`findings` records blocking errors and `incomplete_findings` records missing
required support. The per-case observation flags and coverage totals use
the same audited observation rows. To accept disclosure citations that
include additional visible text, the independent review can supply a
hash-checked enclosing `citation_locator` alongside the narrower note
`locator`.

## Reproduce on Windows

The commands and digest below describe the #51 checkout at `edd0d79`.
The [#52 continuation scorer](EXACT_REPLAY.md) requires the complete replay
payloads and rejects the retained status-only matches.

Run from the repository root with the pinned Python environment and both
archives from [scorer custody](SEC_HOLDOUT.md).

```powershell
$custody = '../FRAG-SEC-Holdout-43'
$out = "build/phase06-scoring-v2-$([guid]::NewGuid()).json"
New-Item -ItemType Directory -Force build | Out-Null
.venv/Scripts/python.exe artifacts/phase06/fresh_score_v2.py `
    artifacts/phase06/fresh-freeze.json "$custody/runner/inputs.zip" `
    "$custody/scorer/expected.zip" artifacts/phase06/fresh-live.json.gz `
    artifacts/phase06/fresh-replay.json.gz $out
if ($LASTEXITCODE -ne 2) { throw 'Expected the retained gate to fail.' }
```

The score records the inputs and scoring dependency digests. The reproduced
full score SHA-256 is
`8cc02ecc519036bf5d029675b3cbd6a547c78eb8bac583720b86874c1eeb6358`.
Exact replay
counts come from the retained runner's status records. Rescoring does not
rerun production or independently repeat offline replay.

The [synthetic controls](../../tests/test_phase06_scoring_revision.py)
exercise heading anchors, wrong year and note citations, unsupported
context, independent companion credit, the reviewed verification reason,
and first stops when intake reports a verification with the wrong
original locator.

```powershell
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_phase06_scoring_revision.py
```
