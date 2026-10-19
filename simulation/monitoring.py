"""Shared, explicit fixed-grid run-up definitions and saved-output processing.

No water integration occurs here. Expanded windows are observations, not changes
in terrain. Missing/partial coverage fails closed in the production reader.
"""
from __future__ import annotations
from pathlib import Path
import copy
import re
import numpy as np
from .runup_metrics import artificial_cell_mask, measure_runup

LEGACY = dict(name="legacy", fgno=1, bounds_xyxy_m=[900., 900., 2500., 2300.])


def monitor_specs(config):
    diagnostics = config.get("diagnostics", {})
    specs = copy.deepcopy(diagnostics.get("runup_monitors", [LEGACY]))
    if not isinstance(specs, list) or not specs:
        raise ValueError("At least one explicit run-up monitor is required.")
    names, numbers = set(), set()
    for item in specs:
        name, number = item.get("name"), item.get("fgno")
        bounds = np.asarray(item.get("bounds_xyxy_m", []), dtype=float)
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise ValueError("Monitor name must be a safe lowercase identifier.")
        if type(number) is not int or not 1 <= number <= 9999:
            raise ValueError("Monitor number must be a positive four-digit integer.")
        if name in names or number in numbers:
            raise ValueError("Duplicate monitor names or numbers.")
        if bounds.shape != (4,) or not np.isfinite(bounds).all() or not (bounds[0] < bounds[2] and bounds[1] < bounds[3]):
            raise ValueError("Monitor bounds must be finite west,south,east,north.")
        item["bounds_xyxy_m"] = bounds.tolist()
        names.add(name); numbers.add(number)
    primary = diagnostics.get("primary_runup_monitor", "legacy")
    if primary not in names or not any(i["name"] == "legacy" and i["fgno"] == 1 for i in specs):
        raise ValueError("Retain legacy monitor 1 and name an existing primary monitor.")
    return specs, primary


def monitor_points(spec, setup, *, require_static=False):
    domain = np.asarray(setup["domain_xyxy_m"], dtype=float)
    nx, ny = setup["nx"], setup["ny"]
    if domain.shape != (4,) or not np.isfinite(domain).all() or not (domain[0] < domain[2] and domain[1] < domain[3]) or type(nx) is not int or type(ny) is not int or min(nx, ny) < 1:
        raise ValueError("Invalid fixed solver grid.")
    bounds = np.asarray(spec["bounds_xyxy_m"], dtype=float)
    if np.any(bounds[:2] < domain[:2]) or np.any(bounds[2:] > domain[2:]):
        raise ValueError("Monitor bounds exceed the solver domain; no silent clipping.")
    dx, dy = (domain[2]-domain[0])/nx, (domain[3]-domain[1])/ny
    xc = domain[0] + (np.arange(nx)+.5)*dx
    yc = domain[1] + (np.arange(ny)+.5)*dy
    xs = xc[(xc >= bounds[0]) & (xc <= bounds[2])]
    ys = yc[(yc >= bounds[1]) & (yc <= bounds[3])]
    if not len(xs) or not len(ys):
        raise ValueError("Monitor contains no cell centres.")
    if require_static:
        source = np.asarray(setup.get("source_bounds_xyxy_m", []), dtype=float)
        if source.shape != (4,) or not np.isfinite(source).all() or not (source[0] < source[2] and source[1] < source[3]):
            raise ValueError("A finite source-grid footprint is required for static run-up terrain.")
        footprint = [xs[0]-dx/2, ys[0]-dy/2, xs[-1]+dx/2, ys[-1]+dy/2]
        overlaps = footprint[0] <= source[2] and footprint[2] >= source[0] and footprint[1] <= source[3] and footprint[3] >= source[1]
        if overlaps:
            raise ValueError("Run-up monitor cells overlap the moving-source grid.")
    xx, yy = np.meshgrid(xs, ys)
    return xx.ravel(), yy.ravel()


def read_monitors(folder, inputs, config, setup):
    """Use the same definitions for solver requests and measured outputs.

    The legacy scalar and CSV are retained for archival workflows. The explicit
    primary metric is used by the bounded release, without source calibration.
    """
    folder, inputs = Path(folder), Path(inputs)
    specs, primary = monitor_specs(config)
    with np.load(inputs / "terrain_arrays.npz") as data:
        terrain = {k: data[k] for k in data.files}
    artificial = artificial_cell_mask(terrain, include_virtual_wall=config["geometry"]["include_published_virtual_wall"])
    result = {}
    require_static = config.get("diagnostics", {}).get("require_static_runup_terrain", False)
    for spec in specs:
        xs, ys = monitor_points(spec, setup, require_static=require_static)
        path = folder / f"fgmax{spec['fgno']:04d}.txt"
        if not path.is_file():
            raise ValueError(f"Missing per-timestep run-up monitor: {path.name}.")
        m = np.loadtxt(path, ndmin=2)
        if m.ndim != 2 or m.shape[1] != 7 or not np.isfinite(m).all():
            raise ValueError("Unexpected fgmax format; expected x,y,level,B,hmax,time,arrival.")
        expected = np.column_stack([xs, ys])
        order = np.lexsort((m[:, 0], m[:, 1]))
        expected = expected[np.lexsort((expected[:, 0], expected[:, 1]))]
        dx = np.min(np.diff(terrain["xe"])); dy = np.min(np.diff(terrain["ye"]))
        if len(m) != len(expected) or not np.allclose(m[order, :2], expected, atol=min(dx,dy)*1e-5, rtol=0):
            raise ValueError("Monitor coverage differs from its declared points.")
        if require_static:
            ii = np.searchsorted(terrain["xe"], m[:, 0], side="right")-1
            jj = np.searchsorted(terrain["ye"], m[:, 1], side="right")-1
            if not np.allclose(m[:, 3], terrain["bcell"][jj, ii], atol=config["checks"]["initial_bed_error_limit_m"], rtol=0):
                raise ValueError("Static run-up bed differs from prepared terrain.")
        metric = measure_runup(m, terrain["xe"], terrain["ye"], artificial,
                               depth_threshold_m=config["checks"]["runup_depth_threshold_m"])
        if not metric["all_points_observed"] or metric["maximum_wetted_cell_elevation_m"] is None:
            raise ValueError("Run-up monitor has unobserved points or no eligible natural land.")
        metric.update(name=spec["name"], fgno=spec["fgno"],
                      requested_bounds_xyxy_m=spec["bounds_xyxy_m"],
                      sampled_bounds_xyxy_m=[float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())],
                      static_source_separation_checked=bool(require_static))
        result[spec["name"]] = metric
        filename = "opposite_slope_max_depth.csv" if spec["name"] == "legacy" else f"runup_{spec['name']}_max_depth.csv"
        np.savetxt(folder / filename, m, delimiter=",", comments="",
                   header="x_m,y_m,level,cell_bed_m,maximum_depth_m,time_at_maximum_depth_s,geoclaw_arrival_s")
    return dict(primary_monitor=primary, monitors=result,
                note="Maxima within declared diagnostic windows, not proven whole-slope or historical maxima. GeoClaw arrival is not an independently validated landward arrival measurement.")
