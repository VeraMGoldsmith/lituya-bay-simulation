# Testing and verification

## Default software tests

The default `python -m pytest` command runs the data-independent suite and
reports explicit skips for tests marked `reference_data`. It uses synthetic
water-output fixtures and mocked solver/Docker processes. Solver-input deck
fixtures exercise the real formatting regression; they are not water results.
No GeoClaw simulation is launched by this suite.

The configuration in [`pyproject.toml`](../pyproject.toml) sets
`testpaths = ["tests"]`. With no explicit test paths, the default command does
**not** collect tests under `analysis/` or `experiments/`. The additional study
commands below are separate from this default suite; the current GitHub Actions
workflow also uses the default command.

Coverage includes `simulation`, `calibration`, `reporting`, `geoclaw`, `tools`,
and `workflow`. The default distribution reports coverage without applying
the full-suite 90% threshold because the reconstruction-dependent tests cannot
run from the public files alone. No production module is excluded to improve
the reported percentage.

With separately supplied inputs, the full reference-data gate for `tests/` is:

```sh
python -m pytest --with-reference-data --cov-fail-under=90
```

All seven reference file hashes are checked before this mode runs. See
[DATA.md](DATA.md). Passing software tests does not establish historical
accuracy, spatial/time convergence, or validity of a failed physical run.

GitHub Actions runs the data-independent suite on Python 3.12 and uploads
coverage files. Remote CI status is established only by an actual completed
GitHub Actions run. Dependencies are version-pinned; the environment is not
a fully hashed lock of transitive and operating-system packages.

The local packaging checks are recorded in `release/PACKAGING_CHECKS.json`.
The Dockerfile remains a recipe; a new image build is a separate check.

## Follow-up study software tests

Run from the repository root. These tests use small fixtures and published
records; they require neither private reference inputs nor saved production
outputs, and they do not launch the solver.

The measurement-analysis tests use the Python standard library:

```sh
python3 -B -m unittest discover -s analysis/measurement_robustness -p 'test_*.py' -v
```

The experiment command collects both `test_experiment.py` and the later
`test_reverification.py`:

```sh
python3 -B -m unittest discover -s experiments/speed-limit-grid-resolution -p 'test_*.py' -v
```

Use the existing Python 3.12 scientific environment for the experiment tests.
The later verification tests require NumPy, Matplotlib and the Clawpack 5.14.0
input-writing library, in addition to the repository's pinned dependencies.
Clawpack is supplied by the established pinned runtime; it is not installed by
`environment/requirements-test.txt`. Missing software is an error, not a reason
to skip these tests. No simulation execution is needed to test input generation.

In that environment, the explicit pytest alternative for all three files is:

```sh
python -B -m pytest -o addopts=-q -p no:cacheprovider -rs \
  analysis/measurement_robustness/test_analysis.py \
  experiments/speed-limit-grid-resolution/test_experiment.py \
  experiments/speed-limit-grid-resolution/test_reverification.py
```

Here `-o addopts=-q` replaces the default coverage options for a focused run.
These tests cover measurement arithmetic and thresholds, invalid or inconsistent
data, cap/grid/time-control propagation, failed-case exclusion, comparisons,
and agreement among generated tables and figures. They test software behavior;
they do not independently verify the completed simulations from raw evidence.

See the [measurement instructions](../analysis/measurement_robustness/README.md),
[experiment instructions](../experiments/speed-limit-grid-resolution/README.md),
and [initial verification record](../experiments/speed-limit-grid-resolution/verification.json).
The [later verification record](../experiments/speed-limit-grid-resolution/REVERIFICATION.md)
and [machine-readable results](../experiments/speed-limit-grid-resolution/reverification.json)
retain the exact executed commands, test-file hashes, pass/fail/skip counts and
skip reasons, including directly relevant shared-code regression tests. The
earlier counts predate the added `test_reverification.py`; they are historical
records, not a count of today's discovery command.

## Verification of completed simulation runs

Completed-run verification is a separate read-only replay of saved evidence.
The six follow-up runs were checked against the declared field-validity,
CFL/time-step, monitoring-coverage and input-consistency criteria, including the
declared global time-step ceiling. Desired CFL 0.5 is a target; acceptance uses
the existing ceiling of 1.0 and its documented printed-log tolerance. Reaching
420 s alone is insufficient. The earlier failed 200 m/s case remains excluded.

The replay requires the original checksummed reference inputs, prepared inputs,
six-case session `speed_grid_a205e423`, archived session
`20261019T041033Z_ff1b17c2`, and the exact pinned runtime in
[`protocol.json`](../experiments/speed-limit-grid-resolution/protocol.json).
These private inputs and large outputs are not distributed in the public
repository. See [DATA.md](DATA.md) for reference-input requirements.

Follow the [pinned-environment and read-only mount setup](../experiments/speed-limit-grid-resolution/REVERIFICATION.md#reproduce-from-the-repository-root)
from the repository root. After defining its `task_docker` array, the established
replay command is:

```bash
"${task_docker[@]}" experiments/speed-limit-grid-resolution/reverify.py \
  --session /session --archive /archive --output /review/replay
```

The output must be a new scratch directory, outside the repository and input
sessions. This command rechecks execution identity and acceptance, recomputes
monitor/gauge measurements and comparisons, and regenerates reports for
agreement checks. It does not rerun simulations. Public report regeneration
alone does not perform this raw-output verification. Exact procedures, numerical
results and remaining review limitations are retained in the linked verification
records; their historical execution status is not updated by this guide.

The follow-up presentation's figure coordinates, table values and source hashes
were also checked against the committed results; see its
[methods and generation instructions](presentation/experiment_visuals/README.md)
and [provenance](presentation/experiment_visuals/provenance.json).
Software tests and saved-output verification do not establish historical
accuracy or numerical convergence.
