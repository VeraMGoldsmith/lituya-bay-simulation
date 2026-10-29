# Lituya Bay simulation

A numerical investigation of the 1958 Lituya Bay megatsunami using GeoClaw, focusing on landslide-generated wave propagation, run-up estimation, and numerical sensitivity.

The repository contains a moving-bed source model, simulation configurations, validation procedures, software tests, and visualizations. The experimental work includes a controlled comparison of numerical water-speed limits (50, 100, and 200 m/s), followed by analyses of run-up measurement methods and the influence of grid resolution.

This preliminary release brings together the modeling approach, results from the original and follow-up studies, and identified numerical limitations. The studies examine how numerical settings and measurement choices affect the simulated results and their interpretation.

## Research objectives

This project investigates the numerical behavior of a simplified model of the 1958 Lituya Bay megatsunami, with particular attention to wave propagation, run-up estimation, and numerical sensitivity.

The study examines how different water-speed limits (50, 100, and 200 m/s) affect simulated run-up and numerical stability. The follow-up experiment investigates whether the sensitivity to these limits persists when the grid is refined, using smaller cells to represent the terrain and water movement in greater detail.

The study also considers how the boundaries of the monitored area and the minimum water depth used to report run-up influence the measurements. The objective is to identify which findings remain consistent across these comparisons and which depend on the selected numerical settings or measurement criteria.

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
The 50 and 100 m/s configurations completed the 420-second simulation period and passed the recorded basic validation checks. Measured run-up increased from 339.72 m to 469.85 m, a difference of approximately 38.3%.

This difference indicates substantial sensitivity to the selected numerical water-speed limit within the tested configurations. The 200 m/s configuration encountered CFL/time-step stability issues and is excluded from the accepted run-up comparison.

Run-up was measured as the maximum eligible ground elevation reached by water at a minimum depth of 0.1 m within the defined monitoring area. These values are specific to that measurement procedure and have not been established as domain-wide maxima.

The results demonstrate numerical sensitivity but do not, by themselves, establish historical accuracy or numerical convergence.

## Simulation visualizations

The figures and animation present saved outputs from session `20261019T041033Z_ff1b17c2`, covering a 420 s simulation period. The figures compare the 50 and 100 m/s numerical water-speed limits, while the animation shows the 100 m/s configuration. Together, they illustrate simulated wave evolution, inundation, and monitored run-up. These are simulation results, not historical observations.

**Wave evolution.** The maps show water-surface elevation relative to model sea level at six recorded times: 20, 46, 80, 160, 300, and 420 s. The two rows compare the 50 and 100 m/s configurations using a shared symmetric-log color scale.

![Wave evolution](docs/figures/wave_evolution.png)

**Animated wave evolution.** The animation shows simulated water-surface elevation for the 100 m/s configuration over 0–420 s. It uses all 49 saved frames, displayed at 25× speed with timing proportional to their recorded timestamps and no interpolation between frames.

![Lituya Bay — simulated wave evolution](docs/previews/wave_evolution_cap_100/wave_evolution_cap_100_text_preview.gif)

**Inundation and run-up.** The maps show the maximum simulated water depth on eligible natural land within the expanded monitoring area. Here, water depth is the vertical distance from the local ground surface to the water surface. Each location represents its maximum over the simulation period. Contours show ground elevation, and stars identify the highest monitored run-up in each configuration. These run-up values have not been verified as bay-wide maxima.

![Inundation and run-up](docs/figures/spatial_runup.png)

**Numerical sensitivity.** Monitored run-up is 339.72 m for the 50 m/s configuration and 469.85 m for the 100 m/s configuration. This difference demonstrates sensitivity to the numerical water-speed limit within the tested configurations. The 200 m/s configuration is excluded because it failed the recorded CFL/time-step checks.

![Numerical sensitivity](docs/figures/numerical_sensitivity.png)

The maps use local model coordinates. Masking artificial cells in the figures does not remove their influence on the simulation. The results do not establish historical accuracy or numerical convergence.

The [figure provenance](docs/figures/figure_provenance.json) records full-precision measurements, settings, source hashes and rendering details. The [plotting script](experiments/2026-10-19-speed-caps/plot_figures.py) checks the saved data before generating the figures. Regeneration requires the original local simulation session; raw simulation fields and reference inputs are not included in this repository.

## Follow-up analysis: run-up measurements and grid resolution

The follow-up analyses examined how measurement choices and grid resolution affect the interpretation of the original speed-limit comparison. The [measurement-robustness analysis](analysis/measurement_robustness/report.html) used archived results to assess the influence of the monitored area and the water-depth reporting threshold—the minimum depth used to count a land location as wetted. Expanding the monitored area left the 50 m/s run-up unchanged and increased the original 100 m/s value by 5.85 m. The large difference between the two speed limits remained.
The grid-resolution experiment then investigated whether that difference persisted when the model used smaller cells. Water-speed limits of 50, 100, and 200 m/s were compared on the original grid, with approximately 30 m cell spacing, and a finer grid, with approximately 15 m cell spacing. The finer grid represents the same physical area with smaller cells, allowing terrain and water movement to be represented in greater spatial detail. All six simulations used the same physical setup and a common set of revised time-stepping settings.

The large increase in highest monitored run-up from 50 to 100 m/s persisted on both grids. Raising the limit further, from 100 to 200 m/s, left the highest monitored run-up unchanged on each grid. The finer grid produced higher run-up values at all three speed limits, while some other measurements differed slightly between its 100 and 200 m/s simulations.

The comparison between the original and follow-up 100 m/s simulations also showed sensitivity to time-stepping settings. On the original grid, highest monitored run-up changed from 469.85 m in the earlier experiment to 449.33 m under the revised settings. The actual time steps adjusted automatically as each simulation progressed.

The new 200 m/s simulations passed the numerical checks on both grids. The original 200 m/s simulation remains excluded because it failed the numerical stability checks.

![Highest monitored run-up at 50, 100, and 200 m/s: 317.08, 449.33, and 449.33 m on the original grid; 338.24, 492.84, and 492.84 m on the finer grid.](docs/presentation/experiment_visuals/runup_grid_comparison.png)

*Run-up sensitivity to speed limit and grid resolution.* Run-up is the highest sampled natural-land elevation reached by at least 0.1 m of water in the expanded monitoring area, relative to model sea level.

[![Comparison of seven run-up, wetted-area, water-depth, and gauge-level measurements across six follow-up simulations and the earlier original-grid 100 m/s simulation, separated by time-stepping policy.](docs/presentation/experiment_visuals/secondary_comparison.png)](docs/presentation/experiment_visuals/secondary_comparison.png)

*Run-up, flooded area, and water levels.* The earlier 100 m/s simulation is shown separately because its time-stepping settings differ. [View the table at full size](docs/presentation/experiment_visuals/secondary_comparison.png) or use the [readable HTML table](docs/presentation/experiment_visuals/secondary_comparison.html).

The follow-up findings support the original observation of a large run-up difference between the 50 and 100 m/s limits. That difference persisted on both grids, while increasing the limit from 100 to 200 m/s did not change the highest monitored run-up. The absolute run-up values, however, remained sensitive to grid resolution and time-stepping settings.

These findings apply to the tested model setup and monitored area. Equal run-up values do not mean that all aspects of the simulated flow were identical, and the comparisons do not establish numerical convergence or historical accuracy. See the [speed-limit/grid-resolution report](experiments/speed-limit-grid-resolution/report.html), [presentation methods](docs/presentation/experiment_visuals/presentation_notes.md), and [source provenance](docs/presentation/experiment_visuals/provenance.json) for detailed settings, results, and verification records.

## Testing and verification

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
The default command collects only `tests/`; the analysis and experiment tests
require the separate commands documented there.

The follow-up studies include additional tests for measurement calculations, experiment configuration generation, and handling of invalid data and failed cases. The six follow-up simulations were checked against the declared numerical acceptance criteria using saved outputs, time-step logs, monitoring records, and input and runtime provenance. Measurements and comparisons were recomputed from the saved outputs, and the follow-up figure and table were checked against the committed result tables. Detailed procedures and verification records accompany the [measurement-robustness analysis](analysis/measurement_robustness/README.md), [speed-limit/grid-resolution study](experiments/speed-limit-grid-resolution/README.md), and [completed-run verification](experiments/speed-limit-grid-resolution/REVERIFICATION.md). Passing these checks does not establish historical accuracy or numerical convergence.

## Reproducibility and data requirements

Seven external reference files are not redistributed. Their sources, acquisition instructions, and checksum requirements are documented in
[docs/DATA.md](docs/DATA.md).

Reproducing the recorded experiments requires the reference datasets, the specified GeoClaw environment, and the documented preflight checks.

The repository preserves simulation configurations, execution scripts, experimental records, and identifiers needed to trace the recorded results. The Dockerfile provides a build recipe; it does not automatically execute a simulation. A new physical run requires the correct reference inputs and a verified environment.

Software tests can be run independently of the full hydrodynamic simulations.

## Code layout

- `simulation/`: input preparation, measurement, validation, and bounded comparison.
- `geoclaw/`: GeoClaw input writer and Fortran build recipe.
- `tests/`: software tests, synthetic outputs, and solver-input regression fixtures.
- `tools/`: reference resampling, build manifests, and synthetic solver smoke checks.
- `calibration/`, `reporting/`, `workflow.py`: retained earlier workflow modules;
  their source search is outside the bounded experiment and is not a default action.
- `experiments/`: small recorded results and original experiment hashes.

## References

The reconstruction is attributed to [Franco et al. (2020)](https://doi.org/10.5194/nhess-20-2255-2020)
and its [dataset](https://doi.org/10.5281/zenodo.3831448).
The water solver is [GeoClaw / Clawpack](https://github.com/clawpack/clawpack), v5.14.0.
See [THIRD_PARTY.md](THIRD_PARTY.md) and [LICENSE](LICENSE) for component boundaries.

## Research authorship

This project was developed by V. M. Goldsmith. Her contributions include defining the research objectives, developing the experimental approach, selecting and refining numerical comparisons, determining test coverage and validation requirements, evaluating model behavior and results, and establishing the scope and limitations of the study.

AI-assisted tools were used for software implementation, debugging, testing, numerical analysis, and documentation. Research design, methodological decisions, interpretation of results, and publication decisions remained with V. M. Goldsmith.

## Release information

The distribution version is 0.1.0. Older version strings in frozen configurations, launcher image labels, and release/RELEASE_ID identify the earlier workflow or recorded experiment; they are preserved for provenance.
