# Bounded speed-limit × grid-resolution experiment

This is a generated technical experiment package, intended for eventual
repository publication after review. It is not a manuscript or an independently
written PhD application writing sample. AI-assisted tools were used for code,
tests, numerical analysis and documentation. See the repository's
[research-authorship and AI-assistance statement](../../README.md#research-authorship).
Review of the new scientific conclusions remains pending.

Open [report.html](report.html) or [report.md](report.md). The HTML embeds its
styles and figure; it requires no network. Visual review remains pending:
local-file browser inspection was blocked. Structural/data checks are not a
visual review. Actual test results are recorded in [verification.json](verification.json).

## Fixed design

The analysis checkpoint is `a205e42312762e45ef99df4b1ae19fdd83ce4193`. It contains
all nine measurement-robustness files, including `test_analysis.py` and generated
technical reports. No new experiment changes are automatically committed.

[protocol.json](protocol.json) is the complete numerical overlay on
`release/frozen_baseline_config.json`. Together with `config_for()` in
[experiment.py](experiment.py), it reproducibly defines every case configuration.
The protocol records the fixed runtime, checkpoint, six cases and stage gates.
The driver writes the exact configurations and solver decks into the private
session and records their hashes in provenance.

- Stage 1: fresh original-grid 100 and 200 m/s cases.
- Stage 2, only after the pair and fine preflight pass: original-grid 50 m/s and
  fine-grid 50, 100 and 200 m/s. Six new cases total; no extra stationary or
  calibration runs.
- Common policy declared before production: desired CFL 0.5, global maximum
  step 0.1 s, initial step 0.02 s and source-motion cap 0.1 s. The archived policy
  used desired CFL 0.75 and global maximum step 2 s. CFL acceptance stays 1.0
  with the existing formatted-log tolerance. All other existing checks remain.
- Original 227 × 453 cells; fine 454 × 906 over the identical domain. Using a
  nominal 15 m target alone would give 905 Y cells, so the driver uses explicit
  doubled dimensions and the existing cell-integration routine.
- The terrain/source nodal grids remain at 15 m. Their files and motion history
  are byte-identical across resolutions. Four-node source padding remains 60 m;
  artificial-geometry dimensions are not rescaled with solver cells. This is
  refinement of the water grid over the same representation of the terrain.
- Monitors remain at their original physical bounds, using per-time-step fgmax
  cell maxima and the existing observed/natural-land/artificial-mask eligibility
  with the 0.1 m reporting threshold. No sparse-frame proxy is used.

Any numerical failure stops expansion. A terminal case is never automatically
repeated; accepted cases may be reused only after verifying their input,
runtime and output seals. Existing claims are not removed. The archived failed
200 m/s case is excluded permanently from accepted comparisons.

## Public-only commands (repository root)

Measurement-analysis regeneration and its preserved tests, using the standard
library and Git:

```sh
python3 -B analysis/measurement_robustness/analyze.py --starting-commit bc478443109c7bb2620bd3ffb05c5e2cefb1aeca --output-dir /tmp/lituya-measurement-review
python3 -B -m unittest discover -s analysis/measurement_robustness -p 'test_*.py' -v
python3 -B -m unittest discover -s experiments/speed-limit-grid-resolution -p 'test_*.py' -v
```

The new tests use small fixtures and published records, not private inputs or
the solver. No tests are made optional by treating failures as skips.

Regenerate the new reports and figure from published `results.json`, in an
environment with the existing pinned `environment/requirements.txt` packages:

```sh
python3 -B experiments/speed-limit-grid-resolution/report.py --from-records
```

This reproduces reporting, not the underlying simulations. CSVs preserve the
saved numbers without display rounding. Decimal arithmetic is used for reported
differences and percentages. No uncertainty estimates are inferred.

## Private-input execution and acceptance checks (repository root)

Prerequisites: the seven original reference files named by
`required_private_inputs.json`, the sealed baseline archive, and the existing
Docker image named in `protocol.json`. The launcher checks image identity and
uses `--pull never`, network isolation and read-only repository/reference/archive
mounts. It never builds a replacement image. It creates only an empty,
Git-ignored reference mount directory inside the checkout; no reference bytes
are copied there.

For this local project, define this shell helper once from the experiment
repository root:

```sh
LITUYA_PRIVATE_ROOT=/Users/veramaygoldsmith/Downloads/project_for_git/Lituya_Cap_Comparison
LITUYA_EXPERIMENT_SESSION="$LITUYA_PRIVATE_ROOT/comparison_runs/speed_grid_a205e423"
experiment() {
  python3 -B experiments/speed-limit-grid-resolution/launch.py "$@" \
    --private-root "$LITUYA_PRIVATE_ROOT" --session "$LITUYA_EXPERIMENT_SESSION"
}
```

Execute in order. The driver enforces stage gates and refuses a rerun of a failed
or interrupted case. Inspect any error; do not delete its claim or retune controls.

```sh
experiment preflight --grid original
experiment run --case original_100
experiment run --case original_200
experiment preflight --grid fine
experiment run --case original_050
experiment run --case fine_050
experiment run --case fine_100
experiment run --case fine_200
experiment check
experiment report
```

`preflight` verifies runtime, all seven reference hashes, prepared inputs and the
original archive seal; it starts no solver. `run` performs one permitted case,
then invokes unchanged `simulation.time_steps.audit`, `simulation.validate` and
monitor-deck checks, plus the stricter declared global-step ceiling.
`check` reads recorded case status and verifies evidence seals, without rerunning
the solver or altering saved results. `report` checks raw-output, prepared-input
and generated-deck hashes, collects compact public results and creates reports.
Large fields, logs and private geometry remain in the private session.

## Deliverables and traceability

- `experiment.py`: preparation, matching-deck checks, staged execution and
  experiment-specific acceptance/seal checks. Existing acceptance code and all
  existing tracked tests remain unchanged.
- `launch.py`, `protocol.json`: fixed-environment launcher and reproducible
  configurations/policy.
- `test_experiment.py`: permanent focused tests, alongside the preserved
  `analysis/measurement_robustness/test_analysis.py`.
- `report.py`: permanent report/figure generator, including attribution and
  review-status wording in the template.
- `results.json`, `results.csv`, `comparisons.csv`, `case_status.csv`: compact
  records, all required comparisons and a complete status table. Failed cases
  have blank accepted metrics, not zero values.
- `report.md`, `report.html`, `runup_vs_speed_limit.png`: intended publication
  deliverables; review is pending.
- `provenance.json`, `verification.json`, `file_manifest.json`: input/runtime and
  evidence hashes, execution identity, actual test/check results, and the
  intended public files with Git inclusion status.

Git normalized CRLF line endings in the three checkpointed measurement-analysis
CSVs to LF. Their numeric content is unchanged; the previous generation's
provenance hashes describe the pre-normalization bytes. This is recorded rather
than rewriting the checkpoint or changing its calculations. New experiment
CSVs use LF explicitly.

## Completed verification

All six new cases reached 420 s and passed all five acceptance categories:
field validity, CFL/time steps, the declared global time-step ceiling,
monitoring-deck/coverage consistency, and input consistency. The final read-only
evidence check verified all six case seals. The archived failed 200 m/s case
remains excluded. There are no failed or unattempted new cases.

The root-level public test commands above collect and run **20 measurement-analysis
tests** and **23 experiment tests**, respectively, with zero failures or skips.
The measurement result is retained from the verified checkpoint; those files
remain byte-identical. The experiment tests include the generated CSV/Markdown/
HTML comparisons and hashes. An earlier related existing-test run is retained
separately in `verification.json`: 98 passed, one explicitly identified
reference-data test skipped. It is not represented as a fresh full-suite run.

Public-only report regeneration was executed in the existing pinned environment
with no private inputs or raw-output mounts. All eight report/data/provenance
files reproduced byte for byte. The figure was visually inspected. The HTML's
11 tables, embedded figure and links passed structural/data checks; browser
visual review and print-layout review remain pending.

`checks.json` in each private prepared-input directory retains archived
physical-source preparation metadata. The authoritative resolution-specific
dimensions, integrated cell arrays, masks, gauge beds and monitoring geometry
are recorded in `preflight_original.json` and `preflight_fine.json`, copied into
the public `results.json`. No archived metadata is treated as a new solver-grid
validation result.
