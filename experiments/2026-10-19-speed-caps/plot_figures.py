#!/usr/bin/env python3
"""Plot the recorded speed-cap experiment; never prepare inputs or run a solver.

From the repository root, with the pinned environment/requirements.txt installed:
    python -B experiments/2026-10-19-speed-caps/plot_figures.py \
        --session /path/to/comparison_runs/20261019T041033Z_ff1b17c2

The raw session is intentionally not distributed with this repository. All 451
sealed experiment files, all 10 prepared inputs, the result summaries, and the
reader/measurement source hashes must match before any figure is written.
Only three PNGs and figure_provenance.json are written to --output-dir (default:
docs/figures). Input files are only read. PNGs use native cells, without smoothing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
RECORD = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, LogNorm, Normalize, SymLogNorm
from matplotlib.lines import Line2D
from matplotlib.patches import Patch as LegendPatch, Rectangle
import numpy as np
import scipy

from simulation.monitoring import monitor_points, monitor_specs
from simulation.read_output import frame_numbers, number, read_frame
from simulation.runup_metrics import artificial_cell_mask, measure_runup

SESSION_ID = "20261019T041033Z_ff1b17c2"
TIMES = (20, 46, 80, 160, 300, 420)
CASES = ("cap_050", "cap_100")
INK = "#172e41"
ARTIFICIAL = "#c3c8cd"
TERRAIN_CMAP = LinearSegmentedColormap.from_list("natural_ground", ["#faf9f5", "#777b7c"])
COLORS = ("#007c91", "#cd6337")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def verify_sources(session):
    provenance = read_json(RECORD / "provenance.json")
    require(Path(provenance["session"]).name == SESSION_ID, "Wrong recorded session.")
    inputs = {}
    for name, expected in provenance["experiment_file_sha256"].items():
        relative = Path(name).relative_to(provenance["session"])
        require(sha256(session / relative) == expected, f"Changed/missing experiment file: {relative}")
    for name, expected in provenance["prepared_input_sha256"].items():
        require(sha256(session / "inputs" / name) == expected, f"Changed input: {name}")
        inputs[f"inputs/{name}"] = expected
    for name, expected in provenance["result_files_sha256"].items():
        require(sha256(RECORD / name) == expected, f"Changed result summary: {name}")
    readers = {}
    for name in ("simulation/__init__.py", "simulation/read_output.py", "simulation/monitoring.py",
                 "simulation/runup_metrics.py", "simulation/numerics.py"):
        expected = provenance["sealed_code_sha256"][name]
        require(sha256(ROOT / name) == expected, f"Changed reader/measurement code: {name}")
        readers[name] = expected
    return provenance, inputs, readers


def load_data(session, consumed):
    def source(relative):
        path = session / relative
        consumed[relative] = sha256(path)
        return path

    config = read_json(source("config.json"))
    setup = read_json(source("inputs/setup.json"))
    results = read_json(RECORD / "results.json")
    require(results["session"] == f"comparison_runs/{SESSION_ID}", "Results refer to another session.")
    require(config["clawpack_tag"] == "v5.14.0" and config["run"]["duration_s"] == 420,
            "Unexpected solver or duration.")
    with np.load(source("inputs/terrain_arrays.npz"), allow_pickle=False) as archive:
        terrain = {key: archive[key] for key in archive.files}
    artificial = artificial_cell_mask(
        terrain, include_virtual_wall=config["geometry"]["include_published_virtual_wall"])
    specs, primary = monitor_specs(config)
    require(primary == "expanded", "Expected the expanded primary monitor.")
    specs = {spec["name"]: spec for spec in specs}
    threshold = config["checks"]["runup_depth_threshold_m"]
    require(threshold == 0.1, "Unexpected run-up depth threshold.")
    xc = (terrain["xe"][:-1] + terrain["xe"][1:]) / 2
    yc = (terrain["ye"][:-1] + terrain["ye"][1:]) / 2
    cases = {}
    for case in CASES:
        record = results["cases"][case]
        folder = session / "cases" / case
        case_config = read_json(source(f"cases/{case}/config.json"))
        validation = read_json(source(f"cases/{case}/validation.json"))
        steps = read_json(source(f"cases/{case}/time_step_check.json"))
        require(record["valid_for_comparison"] and validation["status"] == "passed_basic_checks"
                and steps["status"] == "passed", f"Unaccepted case: {case}")
        require(case_config["numerics"]["water_speed_limit_m_s"] == record["cap_m_s"], "Cap mismatch.")
        decks = source(f"cases/{case}/fgmax_grids.data").read_text().splitlines()
        for key, expected in (("dt_check", 0), ("interp_method", 0), ("tend_max", 420)):
            values = [number(line.split()[0]) for line in decks if line.split("#")[-1].strip() == key]
            require(values == [expected, expected], f"Unexpected fgmax {key}.")
        monitors = {}
        metrics = {}
        for name, spec in specs.items():
            xs, ys = monitor_points(spec, setup, require_static=True)
            raw = np.loadtxt(source(f"cases/{case}/fgmax{spec['fgno']:04d}.txt"), ndmin=2)
            require(raw.shape == (len(xs), 7), "Unexpected monitor shape.")
            order = np.lexsort((raw[:, 0], raw[:, 1]))
            expected = np.column_stack([xs, ys])
            expected = expected[np.lexsort((expected[:, 0], expected[:, 1]))]
            require(np.allclose(raw[order, :2], expected, atol=0.0002, rtol=0), "Monitor coverage mismatch.")
            i = np.searchsorted(terrain["xe"], raw[:, 0], side="right") - 1
            j = np.searchsorted(terrain["ye"], raw[:, 1], side="right") - 1
            require(np.allclose(raw[:, 3], terrain["bcell"][j, i],
                                atol=config["checks"]["initial_bed_error_limit_m"], rtol=0),
                    "Monitor bed is not the expected static ground.")
            metric = measure_runup(raw, terrain["xe"], terrain["ye"], artificial,
                                   depth_threshold_m=threshold)
            recorded = record["monitor_diagnostics_not_valid_runup_if_case_failed"][name]
            require(metric == recorded, f"Recomputed run-up differs from the record: {case}/{name}")
            require(all(validation["runup_diagnostics"]["monitors"][name][key] == value
                        for key, value in metric.items()), "Validation and raw monitor disagree.")
            wet = (raw[:, 2] == 1) & (raw[:, 3] > 0) & ~artificial[j, i] & (raw[:, 4] >= threshold)
            hmax = np.ma.masked_all(artificial.shape)
            hmax[j[wet], i[wet]] = raw[wet, 4]
            metric = dict(metric, wetted_eligible_cells=int(wet.sum()),
                          maximum_depth_on_wetted_eligible_land_m=float(raw[wet, 4].max()))
            monitors[name] = hmax
            metrics[name] = metric
        frames = {}
        saved_times = []
        for frame in frame_numbers(folder):
            time_path = source(f"cases/{case}/fort.t{frame:04d}")
            time = number(time_path.read_text().split()[0])
            saved_times.append(time)
            if time not in (0, *TIMES):
                continue
            source(f"cases/{case}/fort.q{frame:04d}")
            read_time, patches = read_frame(folder, frame)
            patch = patches[0]
            expected_extent = np.array(setup["domain_xyxy_m"])[[0, 2, 1, 3]]
            require(read_time == time and len(patches) == 1 and
                    patch.q.shape == (setup["ny"], setup["nx"], 4) and
                    np.allclose(patch.extent, expected_extent, atol=1e-7, rtol=0), "Frame grid/time mismatch.")
            require(np.allclose(patch.xlower + (np.arange(patch.nx) + .5) * patch.dx, xc) and
                    np.allclose(patch.ylower + (np.arange(patch.ny) + .5) * patch.dy, yc),
                    "Frame and terrain grids differ.")
            if time == 0:
                require(np.allclose(patch.q[:, :, 3] - patch.q[:, :, 0], terrain["bcell"],
                                    atol=.02, rtol=0), "Initial bed mismatch.")
                continue
            wet = (patch.q[:, :, 0] >= threshold) & ~artificial
            frames[time] = dict(frame=frame, eta=np.ma.masked_where(~wet, patch.q[:, :, 3]))
        require(saved_times == list(range(0, 61, 2)) + list(range(80, 421, 20)), "Unexpected saved-time sequence.")
        require(set(frames) == set(TIMES), "Missing requested snapshots.")
        cases[case] = dict(cap=record["cap_m_s"], metrics=metrics, monitors=monitors, frames=frames)
    failed = results["cases"]["cap_200"]
    failed_check = read_json(source("cases/cap_200/time_step_check.json"))
    require(not failed["valid_for_comparison"] and failed_check["status"] == "failed"
            and any("CFL" in error for error in failed_check["errors"]), "Missing 200 m/s exclusion evidence.")
    require(next(row for row in results["summary"]["cases"] if row["case"] == "cap_200")["runup_expanded_m"] is None,
            "Failed case must not have an accepted run-up value.")
    return dict(config=config, setup=setup, terrain=terrain, artificial=artificial,
                xc=xc, yc=yc, cases=cases, specs=specs, results=results)


def style():
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
                         "text.color": INK, "axes.labelcolor": INK, "axes.edgecolor": "#929da5",
                         "xtick.color": INK, "ytick.color": INK, "axes.titlesize": 12,
                         "axes.titleweight": "semibold", "figure.facecolor": "white",
                         "savefig.facecolor": "white", "axes.spines.top": False,
                         "axes.spines.right": False})


def terrain_background(ax, data):
    terrain = data["terrain"]
    ax.set_facecolor("#f0f5f6")
    extent = [terrain["xe"][0], terrain["xe"][-1], terrain["ye"][0], terrain["ye"][-1]]
    natural = ~data["artificial"] & (terrain["bcell"] > 0)
    ax.imshow(np.ma.masked_where(~natural, terrain["bcell"]), extent=extent,
              origin="lower", cmap=TERRAIN_CMAP, vmin=0, vmax=1100, interpolation="nearest")
    ax.imshow(np.ma.masked_where(~data["artificial"], np.ones_like(terrain["bcell"])),
              extent=extent, origin="lower", interpolation="nearest",
              cmap=LinearSegmentedColormap.from_list("artificial", [ARTIFICIAL, ARTIFICIAL]), vmin=0, vmax=1)
    return extent


def footer(fig, lines, *, y=.022, fontsize=11):
    fig.text(.055, y, "\n".join(lines), ha="left", va="bottom", fontsize=fontsize, color="#475761", linespacing=1.45)


def settings(data):
    return "GeoClaw 5.14.0 · approximately 30 m grid · 420 s run · prescribed moving bed: 0–30 s"


def save(fig, output, name):
    fig.savefig(output / name, dpi=180, metadata={"Software": "Matplotlib; recorded GeoClaw outputs",
                                                "Description": f"Lituya Bay session {SESSION_ID}; preliminary numerical results"})
    plt.close(fig)


def wave_figure(data, output):
    fig, axes = plt.subplots(2, 6, figsize=(18, 12.8), sharex=True, sharey=True)
    fig.subplots_adjust(left=.065, right=.965, top=.875, bottom=.245, wspace=.10, hspace=.10)
    fig.text(.055, .967, "Wave evolution", fontsize=24, weight="bold")
    fig.text(.055, .937, "Simulated water-surface elevation over 420 seconds at two numerical water-speed limits.", fontsize=13)
    fig.text(.055, .910, settings(data), fontsize=11, color="#475761")
    norm = SymLogNorm(linthresh=5, linscale=1, vmin=-500, vmax=500, base=10)
    for row, case in enumerate(CASES):
        item = data["cases"][case]
        for col, time in enumerate(TIMES):
            ax = axes[row, col]
            extent = terrain_background(ax, data)
            eta = item["frames"][time]["eta"]
            require(float(eta.min()) >= -500 and float(eta.max()) <= 500, "Wave colour range would clip data.")
            im = ax.imshow(eta, extent=extent, origin="lower", cmap="RdBu_r", norm=norm, interpolation="nearest")
            bed = np.ma.masked_where(data["artificial"], data["terrain"]["bcell"])
            ax.contour(data["xc"], data["yc"], bed, levels=[0], colors="#616c73", linewidths=.45)
            x0, y0, x1, y1 = data["setup"]["source_bounds_xyxy_m"]
            ax.add_patch(Rectangle((x0, y0), x1-x0, y1-y0, fill=False, edgecolor="#394650", lw=.75, ls=":"))
            ax.set_title(f"t = {time} s", pad=8)
            ax.set_xticks([0, 2500, 5000])
            ax.set_yticks([-8000, -4000, 0, 4000])
            ax.set_xlim(extent[:2]); ax.set_ylim(extent[2:])
            ax.tick_params(labelsize=9)
            if col == 0:
                ax.set_ylabel(f"{item['cap']} m/s water-speed limit\nLocal Y (m)", fontsize=12, labelpad=11)
            if row == 1:
                ax.set_xlabel("Local X (m)", fontsize=10)
    cax = fig.add_axes([.23, .183, .55, .016])
    cb = fig.colorbar(im, cax=cax, orientation="horizontal", ticks=[-500, -100, -20, -5, 0, 5, 20, 100, 500])
    cb.ax.set_xticklabels(["−500", "−100", "−20", "−5", "0", "5", "20", "100", "500"])
    cb.set_label("Water-surface elevation η (m above model sea level = 0)\nShared symmetric-log scale; linear between −5 and +5 m.", fontsize=12)
    fig.legend(handles=[LegendPatch(facecolor="#e5e4df", label="Dry natural ground"),
                        LegendPatch(facecolor=ARTIFICIAL, label="Excluded artificial cells"),
                        Line2D([], [], color="#616c73", lw=1, label="Initial shoreline"),
                        Line2D([], [], color="#394650", lw=1, ls=":", label="Moving-bed grid")],
               loc="lower center", bbox_to_anchor=(.52, .085), ncol=4, frameon=False, fontsize=12)
    footer(fig, ["Water-surface elevation is shown where water depth is at least 0.1 m. The outline marks the initial shoreline.",
                 "Artificial-boundary effects remain; historical accuracy and convergence are not established.",
                 "Terrain adapted from Franco et al. (2020) · Details: figure_provenance.json"], y=.012, fontsize=12)
    save(fig, output, "wave_evolution.png")


def spatial_figure(data, output):
    fig, axes = plt.subplots(1, 2, figsize=(15, 9.8), sharex=True, sharey=True)
    fig.subplots_adjust(left=.07, right=.97, top=.84, bottom=.34, wspace=.12)
    fig.text(.055, .955, "Inundation and run-up", fontsize=24, weight="bold")
    fig.text(.055, .917, "Maximum simulated water depth on natural land during the 420-second simulation.", fontsize=13)
    fig.text(.055, .886, "Each location shows its maximum depth over time, not a single snapshot.", fontsize=11)
    fig.text(.055, .852, settings(data), fontsize=11, color="#475761")
    bounds = data["specs"]["expanded"]["bounds_xyxy_m"]
    for ax, case in zip(axes, CASES):
        item = data["cases"][case]
        extent = terrain_background(ax, data)
        land = np.ma.masked_where(data["artificial"] | (data["terrain"]["bcell"] <= 0), data["terrain"]["bcell"])
        contours = ax.contour(data["xc"], data["yc"], land, levels=[100, 200, 300, 400, 500, 600, 800, 1000],
                              colors="#656b6d", linewidths=.55)
        ax.clabel(contours, fontsize=8, fmt="%d", inline_spacing=4)
        depth = item["monitors"]["expanded"]
        require(float(depth.max()) <= 130, "Depth colour range would clip data.")
        im = ax.imshow(depth, extent=extent, origin="lower", interpolation="nearest", cmap="viridis",
                       norm=LogNorm(vmin=.1, vmax=130))
        for name, linestyle, color in (("expanded", "-", INK), ("legacy", "--", "#a74373")):
            x0, y0, x1, y1 = data["specs"][name]["bounds_xyxy_m"]
            ax.add_patch(Rectangle((x0, y0), x1-x0, y1-y0, fill=False, edgecolor=color, lw=1.4, ls=linestyle, zorder=5))
        metric = item["metrics"]["expanded"]
        for point in metric["peak_locations"]:
            ax.plot(point["x_m"], point["y_m"], marker="*", ms=16, color="#e75631", mec="white", mew=.9, zorder=7)
            ax.annotate(f"Highest monitored run-up\n{metric['maximum_wetted_cell_elevation_m']:.2f} m\n"
                        f"(X, Y) = ({point['x_m']:.0f}, {point['y_m']:.2f}) m",
                        xy=(point["x_m"], point["y_m"]), xytext=(-790, 2110), fontsize=10,
                        ha="left", va="top", bbox=dict(boxstyle="round,pad=.4", fc="white", ec="#adb6bc", alpha=.96),
                        arrowprops=dict(arrowstyle="-", color=INK, lw=1), zorder=8)
        ax.set_title(f"{item['cap']} m/s water-speed limit", pad=13, fontsize=14)
        ax.set_xlim(bounds[0]-35, bounds[2]+35); ax.set_ylim(bounds[1]-35, bounds[3]+35)
        ax.set_xticks([-1000, 0, 1000, 2000, 3000]); ax.set_yticks([0, 500, 1000, 1500, 2000])
        ax.set_xlabel("Local X (m)")
    axes[0].set_ylabel("Local Y (m)")
    terrain_cb = fig.colorbar(plt.cm.ScalarMappable(norm=Normalize(0, 1100), cmap=TERRAIN_CMAP),
                              cax=fig.add_axes([.14, .275, .29, .018]), orientation="horizontal", ticks=[0, 200, 400, 600, 800, 1000])
    terrain_cb.set_label("Static ground elevation (m above model sea level)", fontsize=10)
    depth_cb = fig.colorbar(im, cax=fig.add_axes([.60, .275, .29, .018]), orientation="horizontal",
                            ticks=[.1, 1, 10, 50, 130])
    depth_cb.ax.set_xticklabels(["0.1", "1", "10", "50", "130"])
    depth_cb.set_label("Maximum water depth on land (m; logarithmic scale)", fontsize=10)
    depth_cb.ax.minorticks_off()
    fig.legend(handles=[Line2D([], [], color=INK, lw=1.4, label="Expanded monitoring area"),
                        Line2D([], [], color="#a74373", ls="--", lw=1.4, label="Original monitoring area"),
                        Line2D([], [], color="#e75631", marker="*", ls="", ms=12, label="Highest monitored run-up"),
                        LegendPatch(facecolor=ARTIFICIAL, label="Excluded artificial cells"),
                        LegendPatch(facecolor="#f0f5f6", label="Initially submerged ground")],
               loc="lower center", bbox_to_anchor=(.52, .16), ncol=3, frameon=False, fontsize=10)
    footer(fig, ["Run-up is the highest eligible ground elevation, relative to model sea level, reached by at least 0.1 m of water",
                 "within the expanded monitoring area. These are simulated measurements, not historical observations or verified bay-wide maxima.",
                 "Artificial-boundary effects remain.",
                 "Terrain adapted from Franco et al. (2020) · Details: figure_provenance.json"], y=.025)
    save(fig, output, "spatial_runup.png")


def sensitivity_figure(data, output):
    fig, ax = plt.subplots(figsize=(12, 8.4))
    fig.subplots_adjust(left=.12, right=.96, top=.78, bottom=.255)
    fig.text(.065, .95, "Numerical sensitivity", fontsize=24, weight="bold")
    fig.text(.065, .907, "Effect of the numerical water-speed limit on monitored run-up.", fontsize=13)
    fig.text(.065, .870, settings(data), fontsize=11, color="#475761")
    values = [data["cases"][case]["metrics"]["expanded"]["maximum_wetted_cell_elevation_m"] for case in CASES]
    delta = values[1] - values[0]
    require(abs(delta - data["results"]["summary"]["setting_differences"]["R100_minus_R50_m"]) < 1e-9,
            "Sensitivity difference mismatch.")
    ax.bar([0, 1], values, width=.45, color=COLORS, zorder=3)
    for x, value in enumerate(values):
        ax.text(x, value+13, f"{value:.2f} m", ha="center", fontsize=14, weight="bold")
    ax.set_xticks([0, 1], ["50", "100"])
    ax.set_xlim(-.6, 1.6); ax.set_ylim(0, 560)
    ax.set_xlabel("Numerical water-speed limit (m/s)", labelpad=12)
    ax.set_ylabel("Monitored run-up (m)", labelpad=10)
    ax.set_yticks(range(0, 551, 100)); ax.grid(axis="y", color="#e3e8eb", lw=.8, zorder=0)
    fig.text(.13, .824, f"Increase from 50 to 100 m/s: +{delta:.2f} m (+{100*delta/values[0]:.1f}%).", fontsize=12, color="#00717e")
    footer(fig, ["Simulated run-up was measured within the expanded monitoring area; both displayed configurations passed the recorded basic checks.",
                 "The 200 m/s configuration was excluded because it failed the recorded CFL/time-step stability checks.",
                 "This comparison shows sensitivity to the numerical water-speed limit; it does not establish historical accuracy or numerical convergence.",
                 "Source and settings: figure_provenance.json"], y=.025)
    save(fig, output, "numerical_sensitivity.png")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", type=Path, required=True, help="Existing raw session directory; read only.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs" / "figures")
    parser.add_argument("--runtime-image-sha256", default=None, help="Optional Docker image identifier for provenance.")
    args = parser.parse_args()
    session, output = args.session.resolve(), args.output_dir.resolve()
    require(session.is_dir(), "Raw session directory does not exist.")
    require(not output.is_relative_to(session) and not session.is_relative_to(output),
            "Output directory must be separate from the raw session.")
    print("Verifying sealed outputs, inputs, summaries and measurement code...", flush=True)
    provenance, consumed, readers = verify_sources(session)
    data = load_data(session, consumed)
    style()
    output.mkdir(parents=True, exist_ok=True)
    wave_figure(data, output)
    spatial_figure(data, output)
    sensitivity_figure(data, output)
    metrics = {case: data["cases"][case]["metrics"] for case in CASES}
    frames = {case: [{"time_s": t, "frame": data["cases"][case]["frames"][t]["frame"],
                      "wet_eta_min_m": float(data["cases"][case]["frames"][t]["eta"].min()),
                      "wet_eta_max_m": float(data["cases"][case]["frames"][t]["eta"].max())} for t in TIMES] for case in CASES}
    manifest = dict(
        session=provenance["session"], analysis_starts_solver=False,
        experiment_provenance_sha256=sha256(RECORD / "provenance.json"),
        script_sha256=sha256(Path(__file__)), reader_sha256=readers,
        result_files_sha256=provenance["result_files_sha256"],
        verification=dict(sealed_experiment_files=len(provenance["experiment_file_sha256"]),
                          prepared_inputs=len(provenance["prepared_input_sha256"]), all_hashes_match=True,
                          raw_monitors_remeasured=True, raw_metrics_equal_recorded_metrics=True,
                          static_monitor_beds_verified=True, exact_saved_times=True),
        consumed_session_files_sha256=dict(sorted(consumed.items())),
        runtime=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                     matplotlib=matplotlib.__version__, docker_image_sha256=args.runtime_image_sha256),
        simulation_settings=dict(clawpack=data["config"]["clawpack_tag"], grid_cells=[data["setup"]["nx"], data["setup"]["ny"]],
                                 domain_xyxy_m=data["setup"]["domain_xyxy_m"], dx_m=float(np.diff(data["terrain"]["xe"])[0]),
                                 dy_m=float(np.diff(data["terrain"]["ye"])[0]), duration_s=420,
                                 source=data["config"]["source"], coordinates=data["config"]["coordinates"],
                                 model_sea_level_m=0, runup_depth_threshold_m=.1,
                                 monitor_specs=data["config"]["diagnostics"]["runup_monitors"]),
        wave_frames=frames, runup_metrics=metrics,
        excluded_case=dict(case="cap_200", accepted_runup_m=None,
                           reason="Failed CFL/time-step checks despite reaching 420 s.",
                           recorded_errors=data["results"]["cases"]["cap_200"]["time_step_check"]["errors"]),
        rendering=dict(wave_scale="SymLogNorm: -500 to 500 m, linear threshold 5 m, base 10, linscale 1",
                       depth_scale="LogNorm: 0.1 to 130 m", terrain_scale="linear: 0 to 1100 m",
                       interpolation="nearest native cells; contours only interpolate display isolines",
                       wave_wet_threshold_m=.1, artificial_mask="any positive bilinear overlap with excluded or enabled virtual-wall nodal masks",
                       initial_shoreline_reference=True, spatial_domain="expanded monitor only"),
        presentation=dict(
            revision="README-consistent wording and two-category sensitivity display; original map design retained.",
            terminology="numerical water-speed limit",
            figure_titles=["Wave evolution", "Inundation and run-up", "Numerical sensitivity"],
            captions="Short interpretation captions; detailed specifications and limitations retained in this file.",
            traceability_documents=["THIRD_PARTY.md", "docs/DATA.md", "experiments/2026-10-19-speed-caps/results.json"],
            wave_panel_times_s=list(TIMES), wave_layout="2 rows by 6 columns; existing map extents, axes, colours and scales preserved",
            sensitivity_displayed_cases=list(CASES), sensitivity_omitted_case="cap_200 (excluded in caption; all experiment records retained)",
            sensitivity_bar_heights_m=[metrics[case]["expanded"]["maximum_wetted_cell_elevation_m"] for case in CASES],
            runup_label_decimal_places=2, increase_label_decimal_places=2, percentage_label_decimal_places=1,
            numeric_rounding="Display labels only; underlying values and bar heights retain recorded precision.",
            measurement_logic_changed=False, readme_modified=False),
        limitations=["Monitor-specific run-up; domain-wide maxima are not established.",
                     "Maximum-depth envelope combines different times, not one simultaneous water surface.",
                     "Artificial-boundary effects remain even though artificial cells are masked.",
                     "Prescribed source is uncalibrated; historical accuracy and convergence are not established.",
                     "Local Cartesian axes have no verified geographic orientation; no historical observations are plotted.",
                     "Raw fields and reference inputs are not redistributed; regeneration requires the original local session."],
        figures_sha256={name: sha256(output / name) for name in
                        ("wave_evolution.png", "spatial_runup.png", "numerical_sensitivity.png")})
    (output / "figure_provenance.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"verified_experiment_files": 451, "runup_expanded_m": {
        case: metrics[case]["expanded"]["maximum_wetted_cell_elevation_m"] for case in CASES},
        "figures": list(manifest["figures_sha256"]), "output_dir": str(output)}, indent=2))


if __name__ == "__main__":
    main()
