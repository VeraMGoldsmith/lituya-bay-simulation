"""Finite source-path calibration, with an unchanged reconstructed basin.

The original add-on varied distance and duration. This integration also uses a
common observation mask, rejects nonfinite scores, and keeps the baseline in the
selection so a worse candidate is not promoted just because it is new.
"""
from __future__ import annotations

import copy
from pathlib import Path
import math
import traceback

import numpy as np

from simulation.common import load, save
from simulation.prepare import prepare
from simulation.runtime import run_cases
from simulation.read_output import frame_numbers, read_frame


def candidates(spec: dict) -> list[tuple[str, float, float]]:
    durations, distances = spec["durations_s"], spec["travel_distances_m"]
    if not durations or not distances:
        raise ValueError("The source search must contain durations and distances.")
    if not all(np.isfinite(v) and v > 0 for v in durations + distances):
        raise ValueError("Candidate distances and durations must be finite and positive.")
    values = [(f"D{t:g}_L{d:g}", float(t), float(d)) for t in durations for d in distances]
    if len({v[0] for v in values}) != len(values):
        raise ValueError("Duplicate source candidates.")
    return values


def prepare_candidates(base: dict, destination: Path, spec: dict) -> tuple[list[dict], list[dict]]:
    destination = Path(destination)
    prepared, rejected = [], []
    for name, duration, distance in candidates(spec):
        case = destination / name
        case.mkdir(parents=True, exist_ok=False)
        config = copy.deepcopy(base)
        config["source"].update(travel_duration_s=duration, travel_negative_y_m=distance)
        config["source"]["provenance"] = "Prescribed source-path candidate; fixed Franco release footprint and volume. Compared with published HySEA response proxies, not HySEA equations."
        save(case / "candidate_config.json", config)
        try:
            setup, checks = prepare(config, case / "inputs")
            save(case / "status.json", {"status": "prepared_not_simulated"})
            prepared.append({"candidate": name, "case": case, "config": config, "setup": setup})
        except Exception as exc:
            record = {"candidate": name, "duration_s": duration, "travel_negative_y_m": distance,
                      "status": "rejected_inputs", "error": str(exc)}
            save(case / "status.json", record)
            rejected.append(record)
    return prepared, rejected


def receiver_mask(inputs: Path, setups: list[dict], spec: dict) -> np.ndarray:
    """Use the same initially wet cells outside every source grid in the ensemble."""
    with np.load(Path(inputs) / "terrain_arrays.npz") as data:
        xe, ye = data["xe"], data["ye"]
        xx, yy = np.meshgrid((xe[:-1] + xe[1:]) / 2, (ye[:-1] + ye[1:]) / 2)
        west, south, east, north = spec["receiver_bounds_xyxy_m"]
        mask = (data["bcell"] < 0) & (xx >= west) & (xx <= east) & (yy >= south) & (yy <= north)
    for setup in setups:
        x0, y0, x1, y1 = setup["source_bounds_xyxy_m"]
        mask &= (xx < x0) | (xx > x1) | (yy < y0) | (yy > y1)
    if not mask.any():
        raise ValueError("No common receiving-water cells remain outside the source grids.")
    return mask


def frame_metric(folder: Path, mask: np.ndarray, target_times, dry_tolerance: float) -> dict:
    records = []
    for index in frame_numbers(folder):
        t, patches = read_frame(folder, index)
        q = patches[0].q
        if q.shape[:2] != mask.shape:
            raise ValueError("Calibration grid differs from the shared receiving-water mask.")
        values = q[:, :, 3][mask & (q[:, :, 0] > dry_tolerance)]
        value = float(max(0., values.max())) if values.size else None
        records.append((float(t), value))
    result = {}
    for target in target_times:
        time, value = min(records, key=lambda item: abs(item[0] - float(target)))
        if abs(time - float(target)) > 1e-6 or value is None or not np.isfinite(value):
            raise ValueError(f"No finite receiving-water output at required time {target} s.")
        result[str(target)] = {"frame_time_s": time, "max_positive_eta_m": value}
    return result


def opposite_arrival(folder: Path, config: dict) -> float | None:
    path = Path(folder) / "opposite_slope_max_depth.csv"
    if not path.is_file():
        raise ValueError("Missing opposite-slope monitor output.")
    monitor = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)
    if monitor.shape[1] != 7 or not np.isfinite(monitor).all():
        raise ValueError("Invalid opposite-slope monitor table.")
    # Initially wet points have arrival zero; they are not landward run-up arrival.
    eligible = ((monitor[:, 2] >= 1) & (monitor[:, 3] > 0)
                & (monitor[:, 3] < config["geometry"]["exclusion_barrier_elevation_m"] - 1)
                & (monitor[:, 4] >= config["checks"]["runup_depth_threshold_m"])
                & (monitor[:, 6] >= 0) & (monitor[:, 6] <= config["run"]["duration_s"]))
    return float(monitor[eligible, 6].min()) if eligible.any() else None


def rms_score(metrics: dict, runup: float, arrival: float | None, targets: dict) -> float:
    residuals = []
    for time, target in targets["temporal"].items():
        residuals.append((metrics[time]["max_positive_eta_m"] - target) / target)
    residuals.append((runup - targets["maximum_runup_m"]) / targets["maximum_runup_m"])
    residuals.append(2. if arrival is None else (arrival - targets["opposite_spur_arrival_s"]) / targets["opposite_spur_arrival_s"])
    if not np.isfinite(residuals).all():
        raise ValueError("Nonfinite calibration diagnostics cannot be ranked.")
    return math.sqrt(sum(r * r for r in residuals) / len(residuals))


def measure(case: Path, name: str, config: dict, mask: np.ndarray, targets: dict) -> dict:
    validation = load(case / "slide/validation.json")
    if validation.get("status") != "passed_basic_checks":
        raise ValueError("Cannot score a run that failed numerical checks.")
    metrics = frame_metric(case / "slide", mask, targets["temporal"], config["water"]["dry_tolerance_m"])
    runup = float(validation["opposite_SW_slope_max_wetted_cell_elevation_m"])
    arrival = opposite_arrival(case / "slide", config)
    return {"candidate": name, "status": "completed", "duration_s": config["source"]["travel_duration_s"],
            "travel_negative_y_m": config["source"]["travel_negative_y_m"], "metrics": metrics,
            "runup_m": runup, "opposite_slope_arrival_s": arrival,
            "score": rms_score(metrics, runup, arrival, targets),
            "placement": load(case / "inputs/source_placement.json")}


def select(records: list[dict]) -> dict:
    completed = [record for record in records if record.get("status") == "completed" and np.isfinite(record.get("score", np.nan))]
    if not completed:
        raise ValueError("No candidate has a finite score and passed numerical checks.")
    # Stable ordering breaks ties in favor of the unchanged baseline.
    return min(completed, key=lambda record: record["score"])


def run_search(base: dict, baseline: Path, baseline_setup: dict, destination: Path,
               spec: dict, targets: dict) -> tuple[Path, list[dict]]:
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    save(destination / "search_spec.json", spec)
    save(destination / "published_targets.json", targets)
    prepared, rejected = prepare_candidates(base, destination, spec)
    if not prepared:
        save(destination / "summary.json", rejected)
        raise ValueError("Every source candidate failed preparation; inspect the recorded errors.")
    mask = receiver_mask(baseline / "inputs", [baseline_setup] + [item["setup"] for item in prepared], spec)
    np.save(destination / "common_receiver_mask.npy", mask)
    records = [measure(baseline, "baseline", base, mask, targets)] + rejected
    for item in prepared:
        case, config = item["case"], item["config"]
        try:
            run_cases(config, item["setup"], case, control=baseline)
            record = measure(case, item["candidate"], config, mask, targets)
        except Exception as exc:
            (case / "last_error.txt").write_text(traceback.format_exc())
            record = {"candidate": item["candidate"], "status": "failed", "error": str(exc),
                      "duration_s": config["source"]["travel_duration_s"],
                      "travel_negative_y_m": config["source"]["travel_negative_y_m"]}
        records.append(record)
        save(destination / "summary.json", records)
    best = select(records)
    save(destination / "best_candidate.json", best)
    selected = baseline if best["candidate"] == "baseline" else destination / best["candidate"]
    save(destination / "selection.json", {
        "selected_candidate": best["candidate"], "baseline_score": records[0]["score"],
        "selected_score": best["score"], "improved_proxy_score": best["score"] < records[0]["score"],
        "scope": "Finite set including baseline; no historical validation or global optimum claimed.",
        "incomplete_candidates": sum(record["status"] != "completed" for record in records),
        "reuse_note": "Identical sealed stationary control reused; each accepted candidate still requires its own slide integration.",
    })
    return selected, records
