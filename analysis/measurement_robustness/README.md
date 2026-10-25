# Archived-results measurement robustness

This folder contains a bounded technical analysis of published summaries, not a
new simulation or a manuscript. It asks how sensitivity to the numerical
water-speed limit varies with the reported quantity and measurement definition.

Open **[report.html](report.html)** in a browser, or read [report.md](report.md).
The HTML contains its own styles and needs no network access. Its print layout
uses landscape pages and repeats table headers.

The reports are generated technical analysis reports produced with AI-assisted
implementation, testing, analysis and documentation. See the repository's
[research-authorship and AI-assistance statement](../../README.md#research-authorship).
They are not independently written PhD application writing samples. Review of
the generated calculations and conclusions remains pending. HTML visual review
also remains pending: browser policy blocked local-file inspection. Structural
and data checks do not substitute for visual review.

## Reproduce

From the repository root, using Python 3.9 or later and Git:

```sh
python3 -B analysis/measurement_robustness/analyze.py --starting-commit bc478443109c7bb2620bd3ffb05c5e2cefb1aeca
python3 -B -m unittest discover -s analysis/measurement_robustness -p 'test_*.py' -v
```

The standalone script and its tests use only the Python standard library.
No installation, private reference data, saved production fields, Docker build,
calibration workflow, or solver is required. The repository's existing solver
tests use their separately documented Python 3.12 environment.

The script regenerates only the three CSVs, two reports and `provenance.json` in
this folder. Use `--output-dir /tmp/lituya-measurement-review` for a separate
output copy. If `--starting-commit` is omitted, the current HEAD is recorded.
The initial checked-in outputs can be regenerated with the explicit base above;
working-tree context in provenance will correctly change after a commit.

## Files and interpretation

- `analyze.py`: read-only input checks, comparisons, conditional threshold-bound
  reasoning, and report generation.
- `comparison.csv`: all seven quantities, signed absolute differences
  (100 minus 50 m/s), and descriptive percentage changes.
- `monitoring_choice.csv`: expanded minus original run-up within each case.
- `threshold_bound.csv`: expanded-monitor peak-cell evidence for the requested
  reporting-threshold interval. This is a deduction, not a threshold sweep.
- `report.md`, `report.html`: the same tables, methods and limitations.
- `provenance.json`: public input hashes, Git context, peak-cell coordinates and
  depths, gauge sampling coverage, and output hashes. Decimal numbers are stored
  as strings in this metadata to preserve their recorded precision.
- `test_analysis.py`: hand-checkable arithmetic, invalid-input and consistency
  checks, threshold reasoning, archived regression, and agreement among formats.

The CSVs preserve decimal source values and calculations without display
rounding. Division uses 28 significant-digit decimal arithmetic; extra digits
are bookkeeping precision, not additional physical accuracy. A blank percentage
means the baseline is unsuitable (zero/negative, or a comparison crossing zero).
Missing/nonfinite required comparison values and conflicting records stop
generation with an error. Missing threshold-proof premises produce “not
established from available records” while retaining other supported comparisons.

Public result and measurement-code hashes must agree with their existing
manifests. A hash mismatch stops generation; it is not repaired or ignored.
All overlapping monitor fields are cross-checked, including the coordinates,
depths and times attached to the actual run-up-maximizing cells. Land counts and
land-depth maxima appear only in figure provenance and cannot be independently
remeasured from the published summaries. No private data are inspected here.

## Starting state

Branch: `analysis/measurement-robustness`.
Starting commit: `bc478443109c7bb2620bd3ffb05c5e2cefb1aeca`, exactly the commit
specified for this analysis and the fetched GitHub `main` at inspection.

The local checkout initially pointed to `f6d0f0e654ba3e900bc1dd66afeef8a164efbfa6`.
The two subsequent commits (`f782154…`, `bc478443…`) changed only root README
wording. The new branch starts after those edits; the root README is not edited
by this analysis. The numerical records and existing figures are identical
across these commits. Local `main` is left at its original commit.

The original untracked `render_animation.py` and `wave_evolution_cap_100.gif`
previews are preserved outside this folder and remain uncommitted; their hashes
are recorded in provenance. No other pre-existing working-tree changes were
found. Nothing is pushed, merged or published by the analysis command.
