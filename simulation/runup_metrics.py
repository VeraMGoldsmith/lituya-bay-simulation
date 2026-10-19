"""Run-up diagnostics shared by the production reader and archived-output replay.

These functions inspect already calculated maxima. They do not evolve water.
Restricted to one fixed grid, rectangular cell-centred monitors, and static
terrain outside the slide footprint. A clean mask does not rule out indirect
wave effects from nearby artificial boundaries.
"""
from __future__ import annotations
from collections.abc import Mapping
import numpy as np
from .numerics import cell_average


def _axis(values, name):
    a = np.asarray(values, dtype=float)
    if a.ndim != 1 or len(a) < 2 or not np.isfinite(a).all() or np.any(np.diff(a) <= 0):
        raise ValueError(f'{name} must be a finite, strictly increasing axis.')
    return a


def artificial_cell_mask(terrain: Mapping, *, include_virtual_wall: bool = True):
    """Flag any positive bilinear overlap with an enabled artificial feature.

    Uses the same integration routine as terrain preparation. Missing masks
    fail closed: elevation alone must never stand in for provenance.
    """
    required = {'x', 'y', 'xe', 'ye', 'excluded', 'wall'}
    if not required.issubset(terrain.keys()):
        raise ValueError('Missing terrain coordinates or artificial-geometry masks.')
    x, y, xe, ye = (_axis(terrain[k], k) for k in ('x', 'y', 'xe', 'ye'))
    masks = []
    for key in ('excluded', 'wall'):
        a = np.asarray(terrain[key])
        if a.shape != (len(y), len(x)) or not np.isin(a, [0, 1]).all():
            raise ValueError(f'{key} must be a binary nodal mask with the terrain shape.')
        masks.append(a.astype(bool))
    nodal = masks[0] | (masks[1] if include_virtual_wall else False)
    return cell_average(nodal.astype(float), x, y, xe, ye) > 0.0


def measure_runup(monitor, xe, ye, artificial_cells, *, depth_threshold_m=0.1):
    """Measure wetted cell-bed elevation within this monitor, with warnings.

    Input columns: x, y, level, B, hmax, time_at_hmax, arrival.
    No interpolation beyond existing points or assumption of a bay-wide maximum
    is made. All equal-height maxima are retained; any edge tie triggers a flag.
    """
    xe, ye = _axis(xe, 'xe'), _axis(ye, 'ye')
    if not np.isfinite(depth_threshold_m) or depth_threshold_m <= 0:
        raise ValueError('Depth threshold must be finite and positive.')
    m = np.asarray(monitor, dtype=float)
    if m.ndim != 2 or m.shape[1] != 7 or not len(m) or not np.isfinite(m).all():
        raise ValueError('Expected a nonempty finite seven-column fgmax monitor.')
    mask = np.asarray(artificial_cells)
    if mask.shape != (len(ye)-1, len(xe)-1) or mask.dtype != np.bool_:
        raise ValueError('Artificial-cell mask must be boolean and match the solver grid.')
    if not np.isin(m[:, 2], [0, 1]).all():
        raise ValueError('Only an unobserved point or fixed-grid level 1 is supported.')
    observed = m[:, 2] == 1
    if np.any(m[observed, 4] < 0):
        raise ValueError('Observed maximum depths must be nonnegative.')
    i = np.searchsorted(xe, m[:, 0], side='right') - 1
    j = np.searchsorted(ye, m[:, 1], side='right') - 1
    if np.any((i < 0) | (i >= len(xe)-1) | (j < 0) | (j >= len(ye)-1)):
        raise ValueError('A monitor point lies outside the solver grid.')
    xc, yc = (xe[:-1]+xe[1:])/2, (ye[:-1]+ye[1:])/2
    # Allows rounding of the ASCII output, not arbitrary relocation of gauges.
    xtol, ytol = np.min(np.diff(xe))*1e-5, np.min(np.diff(ye))*1e-5
    if not np.allclose(m[:, 0], xc[i], atol=xtol, rtol=0) or not np.allclose(m[:, 1], yc[j], atol=ytol, rtol=0):
        raise ValueError('This diagnostic requires cell-centred monitor points.')
    pairs = np.column_stack([j, i])
    if len(np.unique(pairs, axis=0)) != len(m):
        raise ValueError('Duplicate monitor cells are not supported.')
    if len(m) != (i.max()-i.min()+1)*(j.max()-j.min()+1):
        raise ValueError('Monitor must be a complete rectangular block of cells.')
    artificial = mask[j, i]
    eligible = observed & (m[:, 3] > 0) & ~artificial
    wetted = eligible & (m[:, 4] >= depth_threshold_m)
    boundary = (i == i.min()) | (i == i.max()) | (j == j.min()) | (j == j.max())
    runup = float(m[wetted, 3].max()) if wetted.any() else (0.0 if eligible.any() else None)
    peaks = wetted & (m[:, 3] == runup) if runup is not None else np.zeros(len(m), dtype=bool)
    locations = []
    for k in np.flatnonzero(peaks):
        locations.append(dict(x_m=float(m[k, 0]), y_m=float(m[k, 1]),
                              maximum_depth_m=float(m[k, 4]),
                              time_at_maximum_depth_s=float(m[k, 5]),
                              on_monitor_boundary=bool(boundary[k])))
    return dict(
        maximum_wetted_cell_elevation_m=runup,
        peak_locations=locations,
        peak_touches_monitor_boundary=bool(np.any(peaks & boundary)),
        artificial_monitor_cells=int(artificial.sum()),
        wetted_artificial_monitor_cells=int(np.sum(artificial & observed & (m[:, 4] >= depth_threshold_m))),
        eligible_natural_land_cells=int(eligible.sum()),
        observed_points=int(observed.sum()), monitor_points=len(m),
        all_points_observed=bool(observed.all()),
        depth_threshold_m=float(depth_threshold_m),
        metric_scope='provided_monitor_only',
        historically_validated=False,
        note='Cell-bed elevation, not free-surface height. No claim of a domain-wide maximum or convergence.'
    )
