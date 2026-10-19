# Recorded speed-cap comparison

`results.csv` and `results.json` are unchanged copies of the completed analysis
records for session `20261019T041033Z_ff1b17c2`. They are technical records, not
a manuscript. All cases reached 420 s. The 50 and 100 m/s cases passed basic
checks; the 200 m/s case failed its CFL audit.

The JSON contains raw diagnostic values for the failed case under explicitly
labelled keys. Its `valid_for_comparison` flag is false. Only the `summary`
table/CSV should be used for accepted pairwise run-up comparisons.

`provenance.json` retains the original experiment source, input, and output
hashes. It is not a checksum list for this repackaged checkout: packaging changes
are enumerated separately in `release/PACKAGING_CHECKS.json`. Full raw fields
and reference assets are not included, so this repository alone cannot rerun
the original analysis or independently reproduce the physical calculation.
