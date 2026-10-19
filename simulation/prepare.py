"""Role-aware 2.5-D conversion of the uploaded Franco reconstruction.

This is not FLOW-3D FAVOR geometry and not a two-fluid landslide solver.
The conversion choices and every source-motion parameter are recorded.
"""
from pathlib import Path
import json, csv
import numpy as np
from scipy.ndimage import label, binary_dilation
from scipy.interpolate import RegularGridInterpolator
from .common import ROOT, load, save, sha, hash_json
from .numerics import write_tt3, write_dtt3, shifted_thickness, movement, cell_average
NATURAL = ['Bathimetry', 'GilbertGlacier', 'DeltasGilbertInlet', 'CrillonInlet', 'SlopeGilbertNE', 'SlopesGilbertSW', 'Topography']

def validate_config(c):
    d = c['domain']
    s = c['source']
    r = c['run']
    w = c['water']
    extra_positive = [s['travel_negative_y_m'], s['maximum_solver_step_during_motion_s'],
                      r['early_output_interval_s'], r['late_output_interval_s'],
                      r['still_output_interval_s'], w['gravity_m_s2'], w['dry_tolerance_m']]
    if not all(np.isfinite(v) and v > 0 for v in extra_positive):
        raise ValueError('Distance, time intervals, gravity and dry tolerance must be finite and positive.')
    if not np.isfinite(r['early_output_until_s']) or r['early_output_until_s'] < 0:
        raise ValueError('Early-output window must be finite and nonnegative.')
    vals = [d['x_max_m'] - d['x_min_m'], d['y_max_m'] - d['y_min_m'], r['target_cell_size_m'], r['duration_s'], s['travel_duration_s'], s['history_interval_s'], s['volume_m3']]
    if not all((np.isfinite(v) and v > 0 for v in vals)):
        raise ValueError('Lengths, times and volume must be finite and positive.')
    if s['travel_x_m'] != 0:
        raise ValueError('This version implements motion along the inspected local -Y direction only.')
    if not 0 <= s['start_time_s'] < r['duration_s'] or s['start_time_s'] + s['travel_duration_s'] > r['duration_s']:
        raise ValueError('Run must contain the complete source motion.')
    if not 0.8 <= c['geometry']['sw_relief_factor'] <= 1.2:
        raise ValueError('Optional SW-relief factor must be 0.8–1.2; larger deformations need review.')
    if w['sea_level_m'] != 0 or c['coordinates']['native_reference_water_z_m'] != 220:
        raise ValueError('This conversion uses Z-220 and sea level 0. Do not relabel or double-shift the datum.')
    if r['target_cell_size_m'] < 15:
        raise ValueError('Packaged geometry is sampled at 15 m. Finer runs require fresh geometry sampling, not just smaller solver cells.')

def reference_fields(c):
    ref = ROOT / 'data/reference'
    meta = load(ref / 'mesh_sampling.json')
    p = ref / 'mesh_surfaces_15m.npz'
    if sha(p) != meta['derived_grid_sha256']:
        raise ValueError('Reference geometry checksum changed.')
    with np.load(p) as a:
        x = a['x']
        y = a['y']
        natural = np.fmax.reduce([a[n + '_upper'] for n in NATURAL])
        lo = a['DomainRemover_lower']
        hi = a['DomainRemover_upper']
        missing = ~np.isfinite(natural)
        excluded = np.isfinite(lo) & np.isfinite(hi) & (lo <= np.where(missing, 0.0, natural) + 1e-06) & (hi > np.where(missing, 220.0, natural) + 1e-06)
        xx, yy = np.meshgrid(x, y)
        d = c['domain']
        exterior = (xx < d['x_min_m']) | (xx > d['x_max_m']) | (yy < d['y_min_m']) | (yy > d['y_max_m'])
        if np.any(missing & ~excluded & ~exterior):
            raise ValueError('Uncovered active terrain. No ocean or zero elevations will be invented.')
        excluded |= missing
        base = natural - 220.0
        base[excluded] = c['geometry']['exclusion_barrier_elevation_m']
        wall = np.isfinite(a['VirtualWall_upper']) & ~excluded
        if c['geometry']['include_published_virtual_wall']:
            base = np.fmax(base, np.where(wall, a['VirtualWall_upper'] - 220.0, np.nan))
        s0 = np.nan_to_num(a['Rockslide_upper'] - a['Rockslide_lower'], nan=0.0)
        if np.any(s0 < 0):
            raise ValueError('Inverted slide ray intersection.')
        measured_volume = float(s0.sum() * (x[1] - x[0]) * (y[1] - y[0]))
        normalization = c['source']['volume_m3'] / measured_volume
        if abs(normalization - 1) > 0.01:
            raise ValueError('Mesh sampling loses >1% of slide volume. Refine source sampling; do not rescale arbitrarily.')
        s0 *= normalization
        occupied = s0 > 1e-08
        if np.any(excluded & occupied) or np.any(base[occupied] <= 0):
            raise ValueError('Original slide footprint is not completely on the accepted NE slope.')
        contact_gap = (a['Rockslide_lower'] - natural)[occupied]
        water_top = a['Waterbody_upper'].copy()
    wx = np.clip(np.minimum((xx - 1000.0) / 200.0, (2400.0 - xx) / 200.0), 0, 1)
    wy = np.clip(np.minimum((yy - 900.0) / 200.0, (2150.0 - yy) / 200.0), 0, 1)
    weight = wx * wx * (3 - 2 * wx) * wy * wy * (3 - 2 * wy)
    weight[(base <= 0) | excluded | wall] = 0.0
    modified = base * (1.0 + (c['geometry']['sw_relief_factor'] - 1.0) * weight)
    return (dict(x=x, y=y, base=modified, natural=natural - 220.0, excluded=excluded, wall=wall, s0=s0, water_top=water_top, geometry_weight=weight), dict(reference_sha256=meta['derived_grid_sha256'], sampled_slide_volume_m3=measured_volume, volume_normalization=normalization, initial_footprint_min_ground_m=float(base[occupied].min()), source_seating_adjustment_max_abs_m=float(abs(contact_gap).max())))

def prepare(c, out):
    validate_config(c)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    a, checks = reference_fields(c)
    x, y = (a['x'], a['y'])
    dx = x[1] - x[0]
    dy = y[1] - y[0]
    base = a['base']
    s0 = a['s0']
    s = c['source']
    d = c['domain']
    jj, ii = np.where(s0 > 0)
    pad = 4
    i0 = max(0, int(ii.min()) - pad)
    i1 = min(len(x), int(ii.max()) + pad + 1)
    j0 = max(0, int(jj.min() - np.ceil(s['travel_negative_y_m'] / dy)) - pad)
    j1 = min(len(y), int(jj.max()) + pad + 1)
    sx, sy = (x[i0:i1], y[j0:j1])
    initial = s0[j0:j1, i0:i1]
    if sx[0] <= d['x_min_m'] or sx[-1] >= d['x_max_m'] or sy[0] <= d['y_min_m'] or (sy[-1] >= d['y_max_m']):
        raise ValueError('Slide history approaches the computational boundary; keep the reconstructed source, enlarge reviewed domain.')
    if np.any(a['geometry_weight'][j0:j1, i0:i1] > 0):
        raise ValueError('Geometry intervention overlaps the protected source region.')
    end = s['start_time_s'] + s['travel_duration_s']
    dt = s['history_interval_s']
    steps = int(np.ceil(end / dt)) + 1
    times = np.arange(steps) * dt
    if abs(times[-1] - end) > 1e-08:
        raise ValueError('Source duration must be a multiple of history interval.')
    dz = []
    volumes = []
    history = []
    swept = np.zeros(initial.shape, dtype=bool)
    first_wet = None
    localbed = base[j0:j1, i0:i1]
    localexcluded = a['excluded'][j0:j1, i0:i1]
    for t in times:
        st = shifted_thickness(initial, t, s, dy)
        vol = float(st.sum() * dx * dy)
        volumes.append(vol)
        occupied = st > 1e-08
        swept |= occupied
        if np.any(st[[0, -1], :] > 1e-08) or np.any(st[:, [0, -1]] > 1e-08):
            raise ValueError('Source has been clipped by its grid.')
        if np.any(occupied & localexcluded):
            raise ValueError('Slide enters an excluded domain column.')
        wet_fraction = float(st[localbed < 0].sum() / st.sum())
        if first_wet is None and wet_fraction > 1e-05:
            first_wet = float(t)
        history.append([float(t), float(movement(t, s)), vol, wet_fraction])
        dz.append(st - initial)
    dz = np.array(dz)
    drift = float(np.max(abs(np.array(volumes) / s['volume_m3'] - 1)))
    if drift > 1e-09:
        raise ValueError('The prescribed source loses volume in transit.')
    if first_wet is None or history[-1][3] < 0.8:
        raise ValueError('The original slide path does not enter sufficient receiving water. Do not relocate it automatically.')
    b0 = base + s0
    nx = int(np.ceil((d['x_max_m'] - d['x_min_m']) / c['run']['target_cell_size_m'] - 1e-10))
    ny = int(np.ceil((d['y_max_m'] - d['y_min_m']) / c['run']['target_cell_size_m'] - 1e-10))
    xe = np.linspace(d['x_min_m'], d['x_max_m'], nx + 1)
    ye = np.linspace(d['y_min_m'], d['y_max_m'], ny + 1)
    bcell = cell_average(b0, x, y, xe, ye)
    endgrid = np.zeros(b0.shape)
    endgrid[j0:j1, i0:i1] = dz[-1]
    expected = cell_average(endgrid, x, y, xe, ye)
    labels, _ = label((base < 0) & ~a['excluded'])
    ix = np.argmin(abs(x - 1550))
    iy = np.argmin(abs(y - 2810))
    basin_label = int(labels[iy, ix])
    if basin_label == 0:
        raise ValueError('Published central-inlet probe is not in water.')
    if c['checks']['require_open_connection_to_bay']:
        qx = np.argmin(abs(x - 2795))
        qy = np.argmin(abs(y - 464))
        if labels[qy, qx] != basin_label:
            raise ValueError('Gilbert Inlet is disconnected from the published main-bay probe.')
    probes = load(ROOT / 'data/reference/original_probes.json')
    gauges = []
    for p in probes:
        if p['label'].startswith('P') or p['index'] == 1:
            gx, gy, _ = p['xyz_m']
            ci = int((gx - xe[0]) / (xe[1] - xe[0]))
            cj = int((gy - ye[0]) / (ye[1] - ye[0]))
            ground = float(bcell[cj, ci])
            required = p['label'] in ['P2', 'P4', 'P5', 'P6', 'P7N', 'P7S', 'P8', 'P9']
            if required and ground >= 0:
                raise ValueError('Published wet probe ' + p['label'] + ' is dry after conversion.')
            gauges.append(dict(id=p['index'], label=p['label'] if p['index'] != 1 else 'R524', x_m=gx, y_m=gy, initial_cell_bed_m=ground, required_initially_wet=required, source='original authors XY; water column output, not original 3-D point sampling'))
    write_tt3(out / 'terrain.tt3', x, y, b0)
    write_dtt3(out / 'slide.dtt3', sx, sy, times, dz)
    np.savez_compressed(out / 'terrain_arrays.npz', x=x, y=y, base=base, b0=b0, s0=s0, excluded=a['excluded'], wall=a['wall'], xe=xe, ye=ye, bcell=bcell, expected_final_dz_cells=expected, geometry_weight=a['geometry_weight'])
    np.savez_compressed(out / 'source_arrays.npz', x=sx, y=sy, s0=initial, times=times, dz=dz, global_origin=np.array([j0, i0]), swept=swept)
    with (out / 'source_history.csv').open('w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['time_s', 'travel_towards_negative_Y_m', 'represented_volume_m3', 'fraction_of_volume_over_initially_wet_bed'])
        w.writerows(history)
    write_tiff(out / 'terrain.tif', x, y, b0)
    activewet = (base < 0) & ~a['excluded']
    wateroutside = activewet & ~np.isfinite(a['water_top'])
    wf = a['water_top'][activewet & np.isfinite(a['water_top'])] - 220
    checks.update(source_volume_drift_relative=drift, source_first_wet_overlap_s=first_wet, source_final_volume_fraction_over_wet_bed=history[-1][3], source_final_crest_above_sea_m=float(np.max((localbed + dz[-1] + initial)[dz[-1] + initial > 1e-08])), native_excluded_nodes=int(a['excluded'].sum()), excluded_nodes_are_computational_barriers_not_geology=True, flattened_water_top_range_m=[float(wf.min()), float(wf.max())], initial_wet_nodes_outside_original_waterbody=int(wateroutside.sum()), source_zero_initial_dz_max=float(abs(dz[0]).max()), source_final_net_displacement_volume_m3=float(dz[-1].sum() * dx * dy), numerical_cell_sizes_m=[float(xe[1] - xe[0]), float(ye[1] - ye[0])], source_grid_is_protected_from_geometry_changes=True)
    setup = dict(status='prepared_not_simulated', nx=nx, ny=ny, domain_xyxy_m=[d['x_min_m'], d['y_min_m'], d['x_max_m'], d['y_max_m']], gauges=gauges, source_bounds_xyxy_m=[float(sx[0]), float(sy[0]), float(sx[-1]), float(sy[-1])], source_stop_s=end, config_hash=hash_json(c), source_file_sha256=sha(out / 'slide.dtt3'), terrain_file_sha256=sha(out / 'terrain.tt3'), reference_file_sha256=checks['reference_sha256'], calibrated=False)
    save(out / 'setup.json', setup)
    save(out / 'checks.json', checks)
    save(out / 'config.json', c)
    from .placement import describe
    describe(out)
    return (setup, checks)

def write_tiff(path, x, y, z):
    import rasterio
    from rasterio.transform import from_origin
    dx = x[1] - x[0]
    dy = y[1] - y[0]
    with rasterio.open(path, 'w', driver='GTiff', width=len(x), height=len(y), count=1, dtype='float64', transform=from_origin(x[0] - dx / 2, y[-1] + dy / 2, dx, dy), crs='LOCAL_CS["Franco native local XY (not georeferenced)",LOCAL_DATUM["Franco model origin",0],UNIT["metre",1],AXIS["Local X",EAST],AXIS["Local Y",NORTH]]', compress='deflate') as dst:
        dst.write(z[::-1], 1)
        dst.update_tags(AREA_OR_POINT='Point', coordinate_description='Franco native local XY metres; no geographic CRS', vertical_description='Native Z minus 220 m; nominal water=0 m', warning='Depth-averaged adapted terrain includes explicit excluded-column barriers; see checks.json.')
