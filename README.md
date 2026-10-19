# Lituya Bay simulation

Experimental GeoClaw simulations of the Lituya Bay megatsunami, with numerical
sensitivity tests, run-up analysis, and documented model limitations.

This is an early code milestone. It contains a prescribed moving-bed source,
GeoClaw setup, output validation, software tests, and records of a completed
50/100/200 m/s water-speed-cap comparison. It does not establish historical
accuracy or numerical convergence.

## Start with software tests

Use Python 3.12 in a virtual environment, from the repository root:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r environment/requirements-test.txt
python -m pytest
```

The default tests need no reconstruction data and start no water solver.
Reconstruction-dependent tests are explicitly skipped. See
[testing instructions](docs/TESTING.md) for the full local check and coverage scope.

## Recorded experiment

The completed session is `20261019T041033Z_ff1b17c2`; each case reached 420 s.
The cap is a numerical water-speed limit, not the landslide velocity.

| Water-speed cap (m/s) | Expanded-monitor run-up (m) | Recorded outcome |
| --- | ---: | --- |
| 50 | 339.72425 | Passed basic checks |
| 100 | 469.84918 | Passed basic checks |
| 200 | Unavailable | Failed CFL/time-step checks |

See the [CSV](experiments/2026-10-19-speed-caps/results.csv),
[detailed diagnostics](experiments/2026-10-19-speed-caps/results.json), and
[record description](experiments/2026-10-19-speed-caps/README.md).
Run-up means eligible ground-cell elevation wetted to at least 0.1 m within
the specified monitor. It is not a demonstrated domain-wide maximum.
The 200 m/s diagnostics must not be used as an accepted run-up result.

## Data and execution limits

Seven third-party reference files are deliberately excluded. A fresh clone
supports software testing but is not a self-contained reproduction of the
Lituya experiment. Acquisition and checksum requirements are in
[docs/DATA.md](docs/DATA.md).

The retained launchers and `release/` controls document the experiment code.
They are not needed to view results or run software tests. A new physical run
requires the exact reference inputs, a verified GeoClaw environment, and a new
preflight. The one-time recovery launcher and completed local session claims
are not distributed. Never reuse or remove a completed session's claims.

The Dockerfile is included as a build recipe. Its runtime default displays
comparison help; it does not start a simulation. No fresh Docker build or new
hydrodynamic run is claimed for this packaging milestone.

## Code layout

- `simulation/`: input preparation, measurement, validation, and bounded comparison.
- `geoclaw/`: GeoClaw input writer and Fortran build recipe.
- `tests/`: software tests, synthetic outputs, and solver-input regression fixtures.
- `tools/`: reference resampling, build manifests, and synthetic solver smoke checks.
- `calibration/`, `reporting/`, `workflow.py`: retained earlier workflow modules;
  their source search is outside the bounded experiment and is not a default action.
- `experiments/`: small recorded results and original experiment hashes.

## Attribution and project status

The reconstruction is attributed to [Franco et al. (2020)](https://doi.org/10.5194/nhess-20-2255-2020)
and its [dataset](https://doi.org/10.5281/zenodo.3831448).
The water solver is [GeoClaw / Clawpack](https://github.com/clawpack/clawpack), v5.14.0.
See [THIRD_PARTY.md](THIRD_PARTY.md) and [LICENSE](LICENSE) for component boundaries.

Coding, testing, and repository preparation received AI assistance. Research
authorship and publication decisions remain with Vera May Goldsmith. No
research manuscript is included in this code release.

The distribution version is 0.1.0. Older version strings in frozen configurations,
launcher image labels, and `release/RELEASE_ID` identify the earlier workflow or
recorded experiment; they are preserved for provenance.
