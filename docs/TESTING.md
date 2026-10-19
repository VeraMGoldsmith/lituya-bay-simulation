# Software testing

The default `python -m pytest` command runs the data-independent suite and
reports explicit skips for tests marked `reference_data`. It uses synthetic
water-output fixtures and mocked solver/Docker processes. Solver-input deck
fixtures exercise the real formatting regression; they are not water results.
No GeoClaw simulation is launched by this suite.

Coverage includes `simulation`, `calibration`, `reporting`, `geoclaw`, `tools`,
and `workflow`. The default distribution reports coverage without applying
the full-suite 90% threshold because the reconstruction-dependent tests cannot
run from the public files alone. No production module is excluded to improve
the reported percentage.

With separately supplied inputs, the full gate is:

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
