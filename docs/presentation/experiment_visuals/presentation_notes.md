# Presentation captions, methods and proposed interpretation

Generated from `render.py` and the recorded inputs. The figure and comparison table were approved for inclusion in the root README; these notes retain the detailed methods and interpretation proposal.

## Run-up figure

**Run-up sensitivity to speed limit and grid resolution**

On each grid, monitored run-up is unchanged when the limit increases from 100 to 200 m/s.

Highest monitored run-up is the highest sampled natural-land elevation in the expanded monitoring area where water depth reached at least 0.1 m during the simulation. Elevations are relative to model sea level.

Connecting lines join the three tested speed limits; they do not imply simulations at intermediate limits. Exact plotted values and source hashes remain in [provenance.json](provenance.json).

## Comparison table

**Run-up, flooded area, and water levels**

Comparison across speed limits and grid resolutions, including the earlier 100 m/s simulation.

Land measurements use the study’s natural-land selection and 0.1 m water-depth threshold. Wetted area includes land reached by water at any time during the simulation. P2, P3, and P5 identify simulation gauge locations; their water levels are elevations relative to model sea level.

Run-up is displayed to two decimals, water depth/gauge levels to three and wetted area to six. This retains the small differences between the finer-grid 100 and 200 m/s cases. Exact recorded values remain in the HTML table attributes and provenance.

## Time-step comparison at 100 m/s

On the original grid, the revised time-stepping settings reduced highest monitored run-up from 469.85 to 449.33 m—a decrease of 20.52 m (4.37%).

## Methods note

The earlier simulation used a target CFL of 0.75 and a maximum allowed time step of 2 s. The follow-up simulations used a target CFL of 0.5 and a maximum allowed time step of 0.1 s. Actual time steps were adaptive.

Shared numerical controls: initial step 0.02 s; moving-source maximum step 0.1 s; CFL acceptance ceiling 1.0; maximum 200,000 steps. The existing formatted-log acceptance tolerance is unchanged.

GeoClaw 5.14.0; simulation duration 420 s. Original grid: 227 × 453 cells; spacing 30 × 29.96688742 m. Finer grid: 454 × 906 cells; spacing 15 × 14.98344371 m.

Physical source, terrain, domain, friction, wet/dry settings, monitoring boundaries and measurement definitions are unchanged. Actual adaptive time steps may differ across cases and grids. The 100 m/s time-step comparison changes both the target CFL and the maximum allowed time step; it does not isolate either control individually.

Different maxima need not occur at the same time or location. Equal gauge peaks do not establish identical time series. Run-up is the sampled natural-land ground elevation, not water depth or gauge water-surface elevation.

## Proposed interpretation for review

The follow-up experiment tested three numerical water-speed limits on two grid resolutions using the same physical setup and matched time-stepping settings. Increasing the limit from 50 to 100 m/s increased highest monitored run-up on both grids. Increasing it further to 200 m/s left this measure unchanged on each grid, although some other outputs differed slightly on the finer grid. Grid refinement increased the run-up values, and the comparison with the earlier 100 m/s simulation also showed sensitivity to time-stepping settings. Together, these results show that the strong response to the 50 m/s limit persists under refinement, while the absolute run-up remains sensitive to other numerical choices.

These comparisons describe sensitivity within the tested model setup and monitoring area. Agreement between the 100 and 200 m/s run-up values does not establish grid convergence or historical accuracy.

## Sources and supporting records

Source values: [`results.csv`](../../../experiments/speed-limit-grid-resolution/results.csv), [`comparisons.csv`](../../../experiments/speed-limit-grid-resolution/comparisons.csv) and [`results.json`](../../../experiments/speed-limit-grid-resolution/results.json). Controls and identity: [`protocol.json`](../../../experiments/speed-limit-grid-resolution/protocol.json) and the linked experiment provenance. The presentation provenance records the exact source commit and input hashes.

Detailed acceptance checks, verification and excluded-case information remain in the [technical report](../../../experiments/speed-limit-grid-resolution/report.html) and [verification record](../../../experiments/speed-limit-grid-resolution/REVERIFICATION.md). These original research documents are unchanged.
