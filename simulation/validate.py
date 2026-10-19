"""Basic numerical acceptance, separate from historical calibration.

Negative depths are never clamped in archived solver output. Only <=1 micrometre
negative values with effectively zero momentum on nominal dry land can be
accepted, and every accepted occurrence is recorded. This does not diagnose
roundoff as the cause of every such occurrence.
"""
from pathlib import Path
import sys, csv
import numpy as np
from .common import ROOT, save
from .monitoring import read_monitors
from .read_output import frame_numbers, read_frame, read_gauge
from geoclaw.setrun import output_times
from .bed_check import transition_basis, compare_transition, OUTPUT_STEP_FACTOR, TIME_EPS

def negative_depth_issues(q, check, x, y, t):
    h = q[:, :, 0]
    bed = q[:, :, 3] - h
    mom = np.hypot(q[:, :, 1], q[:, :, 2])
    bad = h < -check['negative_depth_limit_m']
    allowed = bad & (h >= -check['dry_land_negative_limit_m']) & (bed >= 0) & (mom <= check['dry_land_momentum_limit_m2_s'])
    violations = bad & ~allowed
    records = []
    for j, i in np.argwhere(bad):
        records.append(dict(t_s=float(t), x_m=float(x[i]), y_m=float(y[j]), h_m=float(h[j, i]), bed_m=float(bed[j, i]), momentum_m2_s=float(mom[j, i]), accepted_dry_land_tolerance=bool(allowed[j, i])))
    return (violations, records)

def validate(folder, case, c, setup, inputs, baseline=None):
    folder = Path(folder)
    checks = c['checks']
    errors = []
    smallneg = []
    history = []
    gauges = []
    a = np.load(Path(inputs) / 'terrain_arrays.npz')
    xe = a['xe']
    ye = a['ye']
    xc = (xe[:-1] + xe[1:]) / 2
    yc = (ye[:-1] + ye[1:]) / 2
    cellarea = (xe[1] - xe[0]) * (ye[1] - ye[0])
    xx, yy = np.meshgrid(xc, yc)
    domain = setup['domain_xyxy_m']
    source = setup['source_bounds_xyxy_m']
    outside = (xx < source[0]) | (xx > source[2]) | (yy < source[1]) | (yy > source[3])
    nframes = frame_numbers(folder)
    expected = output_times(c, case)
    times = []
    maxeta = 0.0
    maxspeed = 0.0
    waveoutside = 0.0
    bottomerror = 0.0
    initialerror = None
    initialbed = None
    transition_records = []
    basis = None
    final_frames_checked = 0
    source_step = c["source"]["maximum_solver_step_during_motion_s"]
    for index in nframes:
        t, patches = read_frame(folder, index)
        if len(patches) != 1:
            raise ValueError('Expected exactly one fixed-grid patch.')
        p = patches[0]
        q = p.q
        if q.shape != (setup['ny'], setup['nx'], 4) or not np.allclose([p.xlower, p.ylower, p.dx, p.dy], [xe[0], ye[0], xe[1] - xe[0], ye[1] - ye[0]], atol=2e-06, rtol=0):
            raise ValueError('Output grid differs from the prepared coordinates.')
        h = q[:, :, 0]
        eta = q[:, :, 3]
        bed = eta - h
        v, records = negative_depth_issues(q, checks, xc, yc, t)
        smallneg.extend(records)
        if v.any():
            detail = next((r for r in records if not r['accepted_dry_land_tolerance']))
            errors.append('Invalid negative water depth: ' + str(detail))
            break
        if initialbed is None:
            initialbed = bed.copy()
            initialerror = float(np.max(abs(bed - a['bcell'])))
            if abs(t) > 1e-08:
                errors.append('Missing t=0 frame.')
            if np.max(abs(q[:, :, 1:3])) > 1e-08 or np.max(abs(eta[h > c['water']['dry_tolerance_m']]), initial=0) > 1e-08:
                errors.append('Initial water is not flat and at rest.')
            if initialerror > checks['initial_bed_error_limit_m']:
                errors.append(f'Initial bed differs from integrated input by {initialerror:g} m. Inspect the terrain reader, not source parameters.')
        deep = h > checks['still_evaluation_depth_m']
        speed = np.divide(np.hypot(q[:, :, 1], q[:, :, 2]), h, out=np.zeros_like(h), where=h > c['water']['dry_tolerance_m'])
        em = float(np.max(abs(eta[deep]), initial=0))
        sm = float(np.max(speed[deep], initial=0))
        maxeta = max(maxeta, em)
        maxspeed = max(maxspeed, sm)
        waveoutside = max(waveoutside, float(np.max(abs(eta[deep & outside]), initial=0)))
        if case == 'still':
            bottomerror = max(bottomerror, float(np.max(abs(bed - initialbed))))
        elif t >= setup['source_stop_s'] - TIME_EPS:
            delta = bed - initialbed - a['expected_final_dz_cells']
            if t <= setup['source_stop_s'] + source_step * OUTPUT_STEP_FACTOR + TIME_EPS:
                if basis is None:
                    basis, interval, source_end = transition_basis(inputs, a, a['expected_final_dz_cells'])
                    if abs(source_end - setup['source_stop_s']) > TIME_EPS:
                        raise ValueError('Source stopping time disagrees with the saved source history.')
                comparison = compare_transition(delta, basis, interval, setup['source_stop_s'], t, source_step)
                transition_records.append(comparison)
                bottomerror = max(bottomerror, comparison['comparison_residual_m'])
            else:
                final_frames_checked += 1
                bottomerror = max(bottomerror, float(np.max(abs(delta))))
        history.append([t, em, sm, float((h * cellarea).sum()), float(h.min())])
        times.append(t)
    if len(times) != len(expected) or (len(times) == len(expected) and (not np.allclose(times, expected, atol=1e-06, rtol=0))):
        errors.append('Missing frames or solver stopped before the requested final time.')
    if case == 'still' and (maxeta > checks['still_eta_limit_m'] or maxspeed > checks['still_speed_limit_m_s']):
        errors.append(f'Still-water residual: eta={maxeta:.6g} m, speed={maxspeed:.6g} m/s exceeds the predeclared limits. Do not auto-relax them.')
    if case == 'slide' and final_frames_checked == 0:
        errors.append('No fully post-source frame to verify the final bed. Keep the final-bed check.')
    if bottomerror > checks['maximum_bed_change_error_m']:
        errors.append(f'Bed-change mismatch {bottomerror:.6g} m exceeds limit.')
    if case == 'slide' and waveoutside < max(checks['minimum_wave_above_baseline_m'], 10 * (baseline or {}).get('max_abs_eta_deep_m', 0.0)):
        errors.append('No resolved water response outside the moving-source grid.')
    if not errors:
        for point in setup['gauges']:
            g = read_gauge(folder, point['id'])
            wet = g[:, 2] > c['water']['dry_tolerance_m']
            if point['required_initially_wet'] and (not wet[0]):
                errors.append('Required water gauge starts dry: ' + point['label'])
            if g[0, 1] > 1e-06 or g[-1, 1] < c['run']['duration_s'] - 2.01:
                errors.append('Gauge output is incomplete: ' + point['label'])
            gauges.append(dict(id=point['id'], label=point['label'], ever_wet=bool(wet.any()), maximum_eta_m=float(np.max(g[wet, 5])) if wet.any() else None, maximum_depth_m=float(np.max(g[:, 2])), samples=len(g)))
    runup = None
    runup_diagnostics = None
    if not errors and case == 'slide':
        try:
            runup_diagnostics = read_monitors(folder, inputs, c, setup)
            # Preserve this legacy-window scalar for archived plotting/calibration.
            # The bounded release uses the separately named primary metric.
            runup = runup_diagnostics['monitors']['legacy']['maximum_wetted_cell_elevation_m']
        except (ValueError, KeyError, OSError) as exc:
            errors.append('Run-up diagnostic failure: ' + str(exc))
    result = dict(status='passed_basic_checks' if not errors else 'failed', case=case, errors=errors, frames_read=len(times), last_time_s=float(times[-1]) if times else None, max_abs_eta_deep_m=maxeta, max_speed_deep_m_s=maxspeed, maximum_wave_outside_source_m=waveoutside, initial_bed_max_error_m=initialerror, final_bed_change_max_error_m=bottomerror, negative_depth_occurrences=smallneg, accepted_small_dry_land_occurrences=sum((p['accepted_dry_land_tolerance'] for p in smallneg)), opposite_SW_slope_max_wetted_cell_elevation_m=runup, runup_depth_threshold_m=checks['runup_depth_threshold_m'], historically_calibrated=False, gauges=gauges, volume_note='Open boundaries: total water volume is reported, not labelled a closed-system conservation test.')
    result['runup_diagnostics'] = runup_diagnostics
    result['runup_primary'] = (runup_diagnostics['monitors'][runup_diagnostics['primary_monitor']]
                               if runup_diagnostics else None)
    result['legacy_runup_scalar_scope'] = 'legacy_monitor_only'
    result['bed_timing_check'] = dict(transition_frames=transition_records, fully_post_source_frames_checked=final_frames_checked, spatial_tolerance_m=checks['maximum_bed_change_error_m'], note='Transition frames use one bounded global source phase; later frames must match the final bed.')
    save(folder / 'validation.json', result)
    with (folder / 'field_history.csv').open('w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['time_s', 'max_abs_eta_at_depth_gt_1m', 'max_speed_at_depth_gt_1m_m_s', 'water_volume_m3', 'minimum_depth_m'])
        w.writerows(history)
    if errors:
        raise ValueError('\n'.join(errors))
    return result
