# Local verification of the completed experiment

Generated technical verification record, 25 October 2026. Implementation,
testing and this record were prepared with AI assistance. See the repository's
[research-authorship and AI-assistance statement](../../README.md#research-authorship).
Human scientific review remains pending. This is not an independently written
application writing sample. The intended scientific report remains
[report.html](report.html); its PDF review copy is unchanged.

## Outcome

No issues were detected in the experiment's configurations, saved results or
reported numerical findings by these checks. All six runs passed fresh acceptance
checks against their logs, saved fields, monitoring outputs and gauges. No solver
was launched, and no targeted simulation rerun is indicated by this verification.

| Case | Grid cells | Rechecked status | Expanded monitored run-up (m) | Maximum printed CFL |
| --- | --- | --- | ---: | ---: |
| original_050 | 227 × 453 | Passed | 317.07672 | 0.283 |
| original_100 | 227 × 453 | Passed | 449.32707 | 0.339 |
| original_200 | 227 × 453 | Passed | 449.32707 | 0.467 |
| fine_050 | 454 × 906 | Passed | 338.24187 | 0.529 |
| fine_100 | 454 × 906 | Passed | 492.83979 | 0.618 |
| fine_200 | 454 × 906 | Passed | 492.83979 | 0.716 |

Each run has 49 saved fields spanning 0–420 s and a continuous integration trace
ending at 420 s. Desired CFL is **0.5**; the acceptance ceiling is **1.0**, with
the unchanged existing audit tolerance of 1.001 for printed CFL. Exceeding the
desired target is not itself an acceptance failure. The declared global maximum
time step is 0.1 s; the initial step is 0.02 s and the source-motion ceiling is
0.1 s. The actual traces satisfy both the established audit and the additional
global-step policy.

The **archived** 200 m/s case remains excluded. Rechecking its trace again found
CFL values of 1.12 and 1.19. It was not substituted for either new 200 m/s case.

## Evidence rechecked

- Recreated all six input decks with the current code and compared them with the
  executed decks, including cap, dimensions, time controls, monitors, physical
  settings and resolved terrain/source paths. The only intended difference
  within each matched grid group remains the numerical water-speed limit.
- Verified the pinned solver executable/runtime, seven required reference-input
  hashes, unchanged computation/acceptance code, prepared inputs, preflight
  records and every sealed file in each run. Public compact records agree with
  the local execution records. Distinct execution claims, complete-run content
  fingerprints and filesystem identities detected no reused or mixed case files.
- Recomputed refinement integration and monitor eligibility. Terrain/source
  files and nodal artificial geometry are unchanged from the archived setup.
  Domain, physical monitoring bounds and gauge positions are unchanged. Fine
  cells halve both actual spacings. Averaging fine cells back to coarse cells
  differs by at most 3.79e-11 m for bed elevation and 9.10e-13 m for final source
  displacement, within the previously declared 1e-8 m preflight tolerance.
- Replayed the existing CFL/time-step, field-validity, source-bed timing,
  monitoring-coverage and input-consistency checks. All 294 saved fields were
  read. Generated diagnostics went into temporary folders; original evidence
  was mounted read-only.
- Recomputed original-area and expanded-area run-up, wetted eligible land area,
  maximum eligible land-water depth, and P2/P3/P5 peak water-surface elevations.
  A separate scalar reduction checked the monitor/gauge measurements. The
  original 0.1 m threshold, natural-land eligibility, artificial-cell masks and
  monitoring definitions are preserved. Archived 100 m/s monitoring/gauge
  evidence was also rehashed and remeasured.
- Verified all **56 comparisons**: eight pairs, each with seven quantities.
  These include 50→100, 100→200, grid refinement and fresh-versus-archived 100.
- Regenerated all three CSVs, Markdown, HTML and the figure in a temporary
  folder. All six files are byte-identical to the existing deliverables.
  Collected `results.json` also matches the published compact records exactly.
  Tests check full-precision CSV values, HTML data attributes, display rounding,
  Markdown values and the plotted accepted-case data.

## Tests and the one verification-code correction

**201 distinct tests passed**, with zero failures and no remaining skipped test.
This total combines two executions without double-counting repeated tests:

| Execution | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: |
| Initial focused experiment + measurement + shared regressions | 199 | 0 | 1 |
| Final new-verifier tests + private-reference geometry test | 9 | 0 | 0 |

The initial skip was
`tests/test_release_monitoring.py::test_real_prepared_monitor_geometry_is_expanded_and_static`,
with the default reason “Requires separately supplied reference data; see
docs/DATA.md.” It subsequently **passed** with `--with-reference-data` and the
verified local inputs. One existing Rasterio affine-operation deprecation
warning was emitted; no failure was converted to a skip.

Final coverage comprises 23 existing experiment tests, 8 new verification tests,
20 measurement-analysis tests and 150 directly relevant shared regressions. The
new tests cover actual Clawpack deck writing for all six cap/grid combinations,
invalid caps, hand-checkable land/gauge metrics, invalid monitor data, desired
CFL versus acceptance ceiling, diagnostic isolation, plot inclusion/exclusion,
and arithmetic roundoff. Test code is preserved in
[test_reverification.py](test_reverification.py).

The first version of the new verifier incorrectly demanded exact decimal
agreement between two area-conversion evaluation orders. Its six run audits
passed, but the later comparison stopped on a 3.6344e-15 km² discrepancy
(3.6344e-9 m²). The checker now permits only 1e-14 km² / 1e-12 percentage-point
area arithmetic roundoff; other metric comparisons remain exact. A regression
test rejects genuinely changed results. The full replay then passed. This
correction changed neither the experiment's acceptance criteria nor any
configuration, saved result, analysis/report code or numerical finding.

## Findings supported by the recheck

- The 50→100 m/s expanded-run-up increase persists: **+132.25035 m (+41.71%)**
  on the original grid and **+154.59792 m (+45.71%)** on the finer grid.
- Expanded monitored run-up is unchanged from 100→200 m/s on both grids at
  recorded precision. This does not establish identical solutions: the fine-grid
  maximum land-water depth and P3/P5 peaks have small nonzero differences.
  All seven reported quantities are equal for the original-grid 100/200 pair
  at saved precision, without implying equal fields or time series.
- Refinement raises monitored run-up by about **6.68% at 50 m/s** and
  **9.68% at 100 and 200 m/s**. Two grids do not establish convergence.
- Fresh original-grid 100 m/s gives **449.32707 m**, compared with archived
  **469.84918 m**: **−20.52211 m (−4.37%)**. The time-stepping policy matters.
  An eventual synthesis must keep the earlier policy and new matched matrix
  distinguishable, rather than treat them as one interchangeable cap comparison.

These are monitor-specific deterministic results, not established bay-wide
maxima, historical observations, statistical uncertainty or evidence that one
speed limit is physically correct. This is a verification of archived execution
evidence, not an independent reproduction of the hydrodynamic simulations.

## HTML and remaining limits

The HTML has 11 structurally checked tables, an embedded figure identical to the
PNG, resolving local links and no external rendering dependencies. The PNG was
visually inspected: labels, legend and footer are readable without detected
overlap or clipping. A fresh attempt to open the local HTML in the in-app browser
was denied by browser URL policy. **Rendered HTML visual review remains pending**;
structural/data checks and the earlier PDF review do not substitute for it.

The sealed `geoclaw.data` records the speed limit; `fort.geo` does not separately
echo that setting. Execution identity is supported by the sealed decks, verified
runtime, claims, hashes and consistent outputs. Field checks cover every saved
field, not every unsaved state. Gauge records end near 419.9 s, within the
existing coverage criterion; no exact 420 s gauge sample is invented. Logged
limiter events are not unique affected cells or momentum/energy measurements.

The numerical evidence is ready for a **reviewed synthesis** with the earlier
study, subject to those qualifications and human review. The root README has
not been updated. Open [report.html](report.html) in a local browser to finish
the outstanding visual review; no simulation rerun is requested.

## Reproduce from the repository root

Use the existing pinned environment; do not build, pull or install software.
The following shell array is supported by Bash and Zsh. Set `task_private_root`
to the original local patched project directory containing the recorded runs.
The destination is a fresh temporary directory, never the repository or session.

```bash
task_private_root=/Users/veramaygoldsmith/Downloads/project_for_git/Lituya_Cap_Comparison
task_review="$(mktemp -d /tmp/lituya-reverification.XXXXXX)"
task_image=sha256:e34a83602d2ed2abaad337aa2a4b97a5f6e84b8f801de5fb6cc40f714d7027d4
task_docker=(docker run --rm --pull never --network none --read-only
  --tmpfs /tmp:rw,exec,nosuid -e PYTHONDONTWRITEBYTECODE=1 -e MPLCONFIGDIR=/tmp/mpl
  -e "LITUYA_RUN_IMAGE_ID=$task_image"
  --mount "type=bind,source=$PWD,target=/repo,readonly"
  --mount "type=bind,source=$task_private_root/data/reference,target=/repo/data/reference,readonly"
  --mount "type=bind,source=$task_private_root/comparison_runs/20261019T041033Z_ff1b17c2,target=/archive,readonly"
  --mount "type=bind,source=$task_private_root/comparison_runs/speed_grid_a205e423,target=/session,readonly"
  --mount "type=bind,source=$task_review,target=/review"
  --workdir /repo --entrypoint python "$task_image" -B)

"${task_docker[@]}" experiments/speed-limit-grid-resolution/reverify.py \
  --session /session --archive /archive --output /review/replay
```

This rehashes/rechecks existing outputs and creates diagnostics and regenerated
reports in scratch. It never invokes the solver or the legacy workflow.
The actual final execution used `/review/replay_final`; the initial attempt is
retained separately in local scratch. Exact executed inner commands and counts
are in [reverification.json](reverification.json).

Run the focused code checks, including the original private-reference test:

```bash
"${task_docker[@]}" -m pytest -o addopts=-q -p no:cacheprovider -rs \
  --with-reference-data --junitxml=/review/tests.xml \
  experiments/speed-limit-grid-resolution/test_experiment.py \
  experiments/speed-limit-grid-resolution/test_reverification.py \
  analysis/measurement_robustness/test_analysis.py \
  tests/test_runup_metrics.py tests/test_release_monitoring.py \
  tests/test_readers_and_validation.py tests/test_time_controls.py \
  tests/test_common_and_setrun.py
```

All selected tests except the explicitly marked geometry test work without
private inputs or production fields. In an environment with the pinned Python
dependencies, run the same inner `python -B -m pytest ...` command without
`--with-reference-data` for public-only testing; the geometry test will be
explicitly skipped. The actual two executions above are distinguished from this
single combined command for future reproduction.

For public-only report regeneration, copy the existing `results.json` and
`provenance.json` into a new scratch directory, then run the existing
`report.py --from-records --output SCRATCH` command in the documented environment.
No private fields are needed for that step. The full verification script checks
the same public rendering against independently remeasured local outputs.

## File and Git preservation

Branch: `experiment/speed-limit-grid-resolution`.
Starting/current checkpoint: `a205e42312762e45ef99df4b1ae19fdd83ce4193`.
The 16 existing staged additions and all pre-existing tracked/staged file bytes
are unchanged. Measurement-analysis files, archived baseline, root README,
approved figures, original previews and PDF review copy are preserved.

Only these four files were added for this verification; all remain untracked,
unignored and uncommitted:

- `reverify.py` — read-only replay and independent numerical checks.
- `test_reverification.py` — eight focused tests.
- `reverification.json` — case evidence, commands, counts, hashes and limitations.
- `REVERIFICATION.md` — this technical verification record and instructions.

Both the checkpointed measurement tests and existing/new experiment tests remain
in the intended repository version. These four new files must be explicitly
included in a later approved commit. Nothing was staged, committed, pushed or
merged during this verification.
