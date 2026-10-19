"""GeoClaw 5.14 Cartesian depth-averaged water solver on the Franco surfaces."""
from pathlib import Path
import os, sys
import math
import numpy as np
from simulation.monitoring import monitor_specs, monitor_points

def output_times(c, case):
    r = c['run']
    end = r['duration_s']
    if case == 'still':
        return sorted(set(np.r_[np.arange(0, end, r['still_output_interval_s']), end].tolist()))
    early = min(end, r['early_output_until_s'])
    return sorted(set(np.r_[np.arange(0, early + 1e-08, r['early_output_interval_s']), np.arange(early, end, r['late_output_interval_s']), end].tolist()))

def setrun(c, setup, case, inputs):
    from clawpack.clawutil.data import ClawRunData
    from clawpack.geoclaw.fgmax_tools import FGmaxGrid
    if case not in ('still', 'slide'):
        raise ValueError('Unknown case.')
    r = ClawRunData('geoclaw', 2)
    d = r.clawdata
    w, s, e, n = setup['domain_xyxy_m']
    nx = setup['nx']
    ny = setup['ny']
    d.lower = [w, s]
    d.upper = [e, n]
    d.num_cells = [nx, ny]
    d.num_eqn = 3
    d.num_aux = 1
    d.num_waves = 3
    d.capa_index = 0
    d.t0 = 0.0
    d.restart = False
    d.output_style = 2
    d.output_times = output_times(c, case)
    d.output_format = 'ascii'
    d.output_q_components = 'all'
    d.output_aux_components = 'none'
    d.output_aux_onlyonce = True
    d.verbosity = 0
    d.dt_variable = True
    d.dt_initial = min(0.02, c['source']['maximum_solver_step_during_motion_s'])
    d.dt_max = 2.0
    d.cfl_desired = 0.75
    d.cfl_max = 1.0
    d.steps_max = 200000
    d.order = 2
    d.dimensional_split = 'unsplit'
    d.transverse_waves = 2
    d.limiter = ['mc'] * 3
    d.use_fwaves = True
    d.source_split = 'godunov'
    d.num_ghost = 2
    d.bc_lower = ['extrap', 'extrap']
    d.bc_upper = ['extrap', 'wall']
    d.checkpt_style = 0
    am = r.amrdata
    am.amr_levels_max = 1
    am.max1d = max(nx, ny) + 10
    am.refinement_ratios_x = [1]
    am.refinement_ratios_y = [1]
    am.refinement_ratios_t = [1]
    am.aux_type = ['center']
    am.flag_richardson = False
    am.flag2refine = False
    am.verbosity_regrid = 0
    am.tprint = True  # Record real time steps in fort.amr for post-run auditing.
    r.regiondata.regions = []
    # GeoClaw 5.14 tick.f enforces dt_max and dt_max_dtopo in this branch.
    # With amr_levels_max=1 this does NOT add spatial refinement or grids.
    r.refinement_data.variable_dt_refinement_ratios = True
    g = r.geo_data
    # Explicit numerical safeguard, independent of the prescribed slide speed.
    cap = c.get('numerics', {}).get('water_speed_limit_m_s', 50.0)
    if isinstance(cap, bool) or not isinstance(cap, (int, float)) or not math.isfinite(cap) or cap <= 0:
        raise ValueError('Water-speed limit must be finite and positive.')
    g.speed_limit = float(cap)
    g.gravity = c['water']['gravity_m_s2']
    g.coordinate_system = 1
    g.sea_level = 0.0
    g.dry_tolerance = c['water']['dry_tolerance_m']
    g.coriolis_forcing = False
    g.friction_forcing = True
    g.manning_coefficient = c['water']['manning_n']
    g.friction_depth = c['water']['friction_depth_m']
    r.topo_data.topofiles = [[3, str(Path(inputs) / 'terrain.tt3')]]
    r.dtopo_data.dtopofiles = [] if case == 'still' else [[3, str(Path(inputs) / 'slide.dtt3')]]
    r.dtopo_data.dt_max_dtopo = c['source']['maximum_solver_step_during_motion_s']
    r.qinit_data.qinit_type = 0
    r.qinit_data.qinitfiles = []
    r.qinit_data.variable_eta_init = False
    r.gaugedata.gauges = [[p['id'], p['x_m'], p['y_m'], 0.0, c['run']['duration_s']] for p in setup['gauges']]
    r.gaugedata.file_format = 'ascii'
    r.gaugedata.q_out_fields = 'all'
    r.gaugedata.aux_out_fields = 'none'
    r.fgmax_data.num_fgmax_val = 1
    if not setup.get('synthetic_smoke_test', False):
        specs, _ = monitor_specs(c)
        require_static = c.get('diagnostics', {}).get('require_static_runup_terrain', False)
        for spec in specs:
            X, Y = monitor_points(spec, setup, require_static=require_static)
            fg = FGmaxGrid()
            fg.fgno = spec['fgno']
            fg.point_style = 0
            fg.npts = len(X)
            fg.X, fg.Y = X, Y
            fg.min_level_check = 1
            fg.tstart_max = 0.0
            fg.tend_max = c['run']['duration_s']
            fg.dt_check = 0.0
            fg.arrival_tol = c['checks']['runup_depth_threshold_m']
            fg.interp_method = 0
            r.fgmax_data.fgmax_grids.append(fg)
    return r

def write_data(folder, inputs, c, setup, case):
    folder = Path(folder).resolve()
    inputs = Path(inputs).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    old = Path.cwd()
    try:
        os.chdir(folder)
        setrun(c, setup, case, inputs).write()
        for name in ['topo.data', 'dtopo.data']:
            p = folder / name
            p.write_text(p.read_text().replace(str(inputs), os.path.relpath(inputs, folder)))
    finally:
        os.chdir(old)
