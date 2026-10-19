"""Describe prescribed slide placement; do not infer an observed impact point."""
from pathlib import Path

import numpy as np

from .common import load, save


def centroid(thickness, x, y) -> list[float]:
    thickness = np.asarray(thickness)
    if thickness.shape != (len(y), len(x)) or not np.isfinite(thickness).all() or np.any(thickness < -1e-8):
        raise ValueError("Expected finite, nonnegative thickness on the declared grid.")
    mass = float(thickness.sum())
    if mass <= 0:
        raise ValueError("An empty footprint has no centroid.")
    return [float(thickness.sum(axis=0) @ x / mass), float(thickness.sum(axis=1) @ y / mass)]


def describe(inputs: Path) -> dict:
    inputs = Path(inputs)
    config = load(inputs / "config.json")
    checks = load(inputs / "checks.json")
    with np.load(inputs / "source_arrays.npz") as source, np.load(inputs / "terrain_arrays.npz") as terrain:
        x, y = source["x"], source["y"]
        initial = source["s0"]
        final = initial + source["dz"][-1]
        j, i = source["global_origin"]
        bed = terrain["base"][j:j + len(y), i:i + len(x)]
        first = checks["source_first_wet_overlap_s"]
        index = int(np.argmin(abs(source["times"] - first)))
        entering = np.where(bed < 0, initial + source["dz"][index], 0)
        record = {
            "coordinates": "Native local XY in metres; not geographic longitude/latitude",
            "initial_centroid_xy_m": centroid(initial, x, y),
            "prescribed_final_centroid_xy_m": centroid(final, x, y),
            "first_wet_overlap_time_s": float(first),
            "first_wet_overlap_centroid_xy_m": centroid(entering, x, y),
            "travel_negative_y_m": config["source"]["travel_negative_y_m"],
            "travel_duration_s": config["source"]["travel_duration_s"],
            "interpretation": "Input diagnostics: an endpoint and sampled wet-overlap centroid, not a recovered historical impact location.",
        }
    save(inputs / "source_placement.json", record)
    return record
