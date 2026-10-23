#!/usr/bin/env python3
"""Render a preview GIF from the sealed cap_100 outputs; never run a solver.

From the repository root, using the existing pinned plotting environment:
    python -B docs/previews/wave_evolution_cap_100/render_animation_text_preview.py \
        --session /path/to/comparison_runs/20261019T041033Z_ff1b17c2

Only wave_evolution_cap_100_text_preview.gif is written, beside this script by default.
The approved plotting script is imported read-only for its source verification,
output reader, artificial-cell mask, terrain background, and plotting style.
All 49 saved states are displayed without interpolation. At 25x acceleration,
the 2 s and 20 s output intervals become exact GIF delays of 80 and 800 ms.
The final recorded state is held for 1200 ms, giving an 18-second loop.
Source hashes, frame times, delays, and rendering settings are embedded in the
GIF comment. GIF's 256-colour format requires colour quantization: a single
fixed palette is used for every frame, with no dithering or spatial smoothing.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import platform
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
PLOT_SCRIPT = ROOT / "experiments/2026-10-19-speed-caps/plot_figures.py"
spec = importlib.util.spec_from_file_location("approved_figures", PLOT_SCRIPT)
approved = importlib.util.module_from_spec(spec)
spec.loader.exec_module(approved)

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.colors import SymLogNorm, to_rgb
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
import numpy as np
import PIL
from PIL import Image

CASE = "cap_100"
ACCELERATION = 25
FINAL_HOLD_MS = 1200
GIF_NAME = "wave_evolution_cap_100_text_preview.gif"


def read_recorded_frames(session):
    provenance, consumed, readers = approved.verify_sources(session)
    figure_record = approved.read_json(ROOT / "docs/figures/figure_provenance.json")
    approved.require(approved.sha256(PLOT_SCRIPT) == figure_record["script_sha256"],
                     "Approved plotting script has changed.")
    approved.require(figure_record["session"] == provenance["session"],
                     "Approved figures refer to another session.")
    for name, expected in figure_record["figures_sha256"].items():
        approved.require(approved.sha256(ROOT / "docs/figures" / name) == expected,
                         f"Approved figure has changed: {name}")

    def source(relative):
        path = session / relative
        consumed[relative] = approved.sha256(path)
        return path

    config = approved.read_json(source("config.json"))
    setup = approved.read_json(source("inputs/setup.json"))
    case_config = approved.read_json(source(f"cases/{CASE}/config.json"))
    validation = approved.read_json(source(f"cases/{CASE}/validation.json"))
    steps = approved.read_json(source(f"cases/{CASE}/time_step_check.json"))
    results = approved.read_json(approved.RECORD / "results.json")
    approved.require(results["session"] == provenance["session"] and
                     results["cases"][CASE]["valid_for_comparison"] and
                     results["cases"][CASE]["cap_m_s"] == 100 and
                     case_config["numerics"]["water_speed_limit_m_s"] == 100 and
                     validation["status"] == "passed_basic_checks" and steps["status"] == "passed",
                     "The requested accepted 100 m/s case was not found.")
    approved.require(config["clawpack_tag"] == "v5.14.0" and config["run"]["duration_s"] == 420 and
                     config["checks"]["runup_depth_threshold_m"] == .1,
                     "Unexpected recorded configuration.")
    with np.load(source("inputs/terrain_arrays.npz"), allow_pickle=False) as archive:
        terrain = {key: archive[key] for key in archive.files}
    artificial = approved.artificial_cell_mask(
        terrain, include_virtual_wall=config["geometry"]["include_published_virtual_wall"])
    xc = (terrain["xe"][:-1] + terrain["xe"][1:]) / 2
    yc = (terrain["ye"][:-1] + terrain["ye"][1:]) / 2
    expected_extent = np.array(setup["domain_xyxy_m"])[[0, 2, 1, 3]]
    folder = session / "cases" / CASE
    frames = []
    for number in approved.frame_numbers(folder):
        source(f"cases/{CASE}/fort.t{number:04d}")
        source(f"cases/{CASE}/fort.q{number:04d}")
        time, patches = approved.read_frame(folder, number)
        patch = patches[0]
        approved.require(len(patches) == 1 and patch.q.shape == (setup["ny"], setup["nx"], 4) and
                         np.allclose(patch.extent, expected_extent, atol=1e-7, rtol=0),
                         "Frame grid or extent differs from the approved figure.")
        approved.require(np.allclose(patch.xlower + (np.arange(patch.nx) + .5) * patch.dx, xc) and
                         np.allclose(patch.ylower + (np.arange(patch.ny) + .5) * patch.dy, yc),
                         "Frame and terrain grids differ.")
        if time == 0:
            approved.require(np.allclose(patch.q[:, :, 3] - patch.q[:, :, 0], terrain["bcell"],
                                         atol=.02, rtol=0), "Initial bed mismatch.")
        wet = (patch.q[:, :, 0] >= .1) & ~artificial
        eta = np.ma.masked_where(~wet, patch.q[:, :, 3])
        approved.require(eta.count() > 0 and float(eta.min()) >= -500 and float(eta.max()) <= 500,
                         f"The approved colour range would clip frame {number} at {time} s.")
        frames.append(dict(number=number, time_s=time, eta=eta))
    approved.require([f["time_s"] for f in frames] == list(range(0, 61, 2)) + list(range(80, 421, 20)),
                     "Unexpected or incomplete saved frame sequence.")
    return dict(config=config, setup=setup, terrain=terrain, artificial=artificial, xc=xc, yc=yc), frames, dict(
        session=provenance["session"], case=CASE, numerical_water_speed_limit_m_s=100,
        verification=dict(sealed_experiment_files=len(provenance["experiment_file_sha256"]),
                          prepared_inputs=len(provenance["prepared_input_sha256"]), all_hashes_match=True),
        approved_script_sha256=approved.sha256(PLOT_SCRIPT),
        approved_figure_provenance_sha256=approved.sha256(ROOT / "docs/figures/figure_provenance.json"),
        experiment_provenance_sha256=approved.sha256(approved.RECORD / "provenance.json"),
        reader_sha256=readers, consumed_session_files_sha256=dict(sorted(consumed.items())))


def fixed_palette():
    # Render using the approved colormaps, then encode with one stable GIF palette.
    wave = plt.get_cmap("RdBu_r")(np.linspace(0, 1, 224))[:, :3]
    terrain = approved.TERRAIN_CMAP(np.linspace(0, 1, 16))[:, :3]
    exact = [to_rgb(c) for c in ("white", approved.INK, approved.ARTIFICIAL, "#f0f5f6",
                                "#616c73", "#394650", "#929da5", "#475761")]
    text_edges = [np.array(to_rgb(c)) * alpha + (1 - alpha)
                  for c in (approved.INK, "#475761") for alpha in (.2, .4, .6, .8)]
    rgb = np.rint(255 * np.vstack([wave, terrain, exact, text_edges])).astype(np.uint8)
    approved.require(rgb.shape == (256, 3), "GIF palette must have 256 colours.")
    palette = Image.new("P", (1, 1))
    palette.putpalette(rgb.ravel().tolist())
    return palette


def render(data, frames, output, metadata):
    approved.style()
    fig = plt.figure(figsize=(9, 12), dpi=110)
    fig.text(.5, .976, "Lituya Bay — simulated wave evolution",
             ha="center", fontsize=16, weight="bold")
    fig.text(.5, .949, "Numerical water-speed limit: 100 m/s · Playback: 25×",
             ha="center", fontsize=11)
    fig.text(.5, .925, approved.settings(data), ha="center", fontsize=10, color="#475761")
    counter = fig.text(.5, .893, "", ha="center", fontsize=16, weight="bold")
    ax = fig.add_axes([.21, .235, .58, .64])
    extent = approved.terrain_background(ax, data)
    norm = SymLogNorm(linthresh=5, linscale=1, vmin=-500, vmax=500, base=10)
    im = ax.imshow(frames[0]["eta"], extent=extent, origin="lower", cmap="RdBu_r", norm=norm,
                   interpolation="nearest")
    bed = np.ma.masked_where(data["artificial"], data["terrain"]["bcell"])
    ax.contour(data["xc"], data["yc"], bed, levels=[0], colors="#616c73", linewidths=.45)
    x0, y0, x1, y1 = data["setup"]["source_bounds_xyxy_m"]
    ax.add_patch(Rectangle((x0, y0), x1-x0, y1-y0, fill=False, edgecolor="#394650", lw=.75, ls=":"))
    ax.set_xlim(extent[:2]); ax.set_ylim(extent[2:])
    ax.set_xticks([0, 2500, 5000]); ax.set_yticks([-8000, -4000, 0, 4000])
    ax.set_xlabel("Local X (m)"); ax.set_ylabel("Local Y (m)")
    ax.set_aspect("equal")
    cax = fig.add_axes([.2, .172, .6, .014])
    cb = fig.colorbar(im, cax=cax, orientation="horizontal", ticks=[-500, -100, -20, -5, 0, 5, 20, 100, 500])
    cb.ax.set_xticklabels(["−500", "−100", "−20", "−5", "0", "5", "20", "100", "500"])
    cb.ax.tick_params(labelsize=10)
    cb.set_label("Water-surface elevation relative to model sea level (m)\n"
                 "Fixed symmetric-log scale; linear between −5 and +5 m.", fontsize=11)
    fig.legend(handles=[Patch(facecolor="#e5e4df", label="Dry natural ground"),
                        Patch(facecolor=approved.ARTIFICIAL, label="Excluded artificial cells"),
                        Line2D([], [], color="#616c73", lw=1, label="Initial shoreline"),
                        Line2D([], [], color="#394650", lw=1, ls=":", label="Moving-bed grid")],
               loc="lower center", bbox_to_anchor=(.5, .067), ncol=2, frameon=False, fontsize=10)
    approved.footer(fig, [
        "Shown where water depth ≥ 0.1 m; artificial cells excluded.",
        "Artificial-boundary effects remain; historical accuracy and numerical convergence are not established.",
        "Terrain adapted from Franco et al. (2020) · Local model coordinates."], y=.012, fontsize=9.5)
    palette = fixed_palette()
    encoded = []
    for frame in frames:
        im.set_data(frame["eta"])
        counter.set_text(f"Simulation time: {frame['time_s']:g} / 420 s")
        fig.canvas.draw()
        rgb = Image.fromarray(np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy())
        encoded.append(rgb.quantize(palette=palette, dither=Image.Dither.NONE))
        print(f"Rendered saved frame {frame['number']:04d}: {frame['time_s']:g} s", flush=True)
    plt.close(fig)
    times = np.array([f["time_s"] for f in frames])
    delay_ms = np.diff(times) * 1000 / ACCELERATION
    approved.require(np.all(delay_ms % 10 == 0), "Frame timing cannot be represented exactly in GIF.")
    durations = [int(d) for d in delay_ms] + [FINAL_HOLD_MS]
    metadata.update(
        animation_script_sha256=approved.sha256(Path(__file__)), analysis_starts_solver=False,
        runtime=dict(python=platform.python_version(), matplotlib=matplotlib.__version__,
                     numpy=np.__version__, pillow=PIL.__version__),
        frames=[dict(frame=f["number"], time_s=f["time_s"], display_duration_ms=d,
                     wet_eta_min_m=float(f["eta"].min()), wet_eta_max_m=float(f["eta"].max()))
                for f, d in zip(frames, durations)],
        playback=dict(acceleration=ACCELERATION, simulation_coverage_s=[float(times[0]), float(times[-1])],
                      final_hold_ms=FINAL_HOLD_MS, loop_duration_ms=sum(durations), loop_forever=True,
                      temporal_interpolation=False),
        rendering=dict(variable="time-dependent water-surface elevation eta; fort.q column 4",
                       units="m above model sea level = 0", water_depth_threshold_m=.1,
                       mask="same artificial_cell_mask and h >= 0.1 m criterion as approved wave figure",
                       extent_xxyy_m=extent, aspect="equal", interpolation="nearest native cells",
                       cmap="RdBu_r", norm="SymLogNorm(-500,500), linthresh=5, linscale=1, base=10",
                       clipping=False, palette="fixed 256 colours: 224 RdBu_r, 16 terrain, 16 overlay/text",
                       dithering=False, image_size_px=list(encoded[0].size)),
        limitations=["Saved states only; output intervals are 2 s through 60 s, then 20 s.",
                     "Simulated result; historical accuracy and numerical convergence are not established.",
                     "Artificial-boundary influence remains despite visual masking.",
                     "Local model coordinates; no verified geographic orientation.",
                     "GIF quantizes rendered colours to one fixed palette shared by every frame."])
    comment = json.dumps(metadata, sort_keys=True, allow_nan=False).encode("utf-8")
    encoded[0].save(output, save_all=True, append_images=encoded[1:], duration=durations, loop=0,
                    disposal=1, optimize=False, comment=comment)
    with Image.open(output) as check:
        approved.require(check.n_frames == len(frames) and check.info["loop"] == 0,
                         "Encoded GIF frame count or loop setting is wrong.")
        approved.require(check.info["comment"] == comment, "Embedded provenance was not preserved.")
        for i, expected in enumerate(encoded):
            check.seek(i)
            approved.require(check.info["duration"] == durations[i], "Encoded frame delay differs.")
            approved.require(np.array_equal(np.asarray(check.convert("RGB")), np.asarray(expected.convert("RGB"))),
                             f"GIF compositing changed saved frame {i}.")
    print(json.dumps(dict(gif=str(output), frame_count=len(frames), coverage_s=times[[0, -1]].tolist(),
                          loop_seconds=sum(durations)/1000, sha256=approved.sha256(output)), indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--runtime-image-sha256", default=None)
    args = parser.parse_args()
    session = args.session.resolve()
    output = args.output_dir.resolve()
    approved.require(session.is_dir() and output.is_dir(), "Session and preview directories must already exist.")
    approved.require(not output.is_relative_to(session) and not session.is_relative_to(output),
                     "The preview must be separate from saved simulation outputs.")
    approved.require(output != ROOT / "docs/figures", "Approved figures must not be overwritten.")
    print("Verifying sealed data and reading all recorded cap_100 frames...", flush=True)
    data, frames, metadata = read_recorded_frames(session)
    metadata["runtime_image_sha256"] = args.runtime_image_sha256
    print(f"Verified {len(frames)} recorded states; rendering without a solver.", flush=True)
    render(data, frames, output / GIF_NAME, metadata)


if __name__ == "__main__":
    main()
