#!/usr/bin/env python3
"""Bounded six-case experiment. Uses the existing solver, never calibration.

Container entry points: preflight --grid original|fine; run --case NAME;
check (read-only verification of recorded acceptance and file seals).
Use launch.py on the host to supply the fixed runtime and read-only inputs.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
BASE = ROOT / "experiments/2026-10-19-speed-caps"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def load(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def protocol():
    p = load(HERE / 'protocol.json')
    require(p['grids']['fine'] == [2*x for x in p['grids']['original']], 'Refinement must halve both actual spacings')
    require(p['speed_limits_m_s'] == [50, 100, 200], 'Only the bounded caps are supported')
    require(len(set(p['stage1'] + p['stage2'])) == 6, 'Exactly six distinct planned cases required')
    return p


def case_parts(name, p):
    require(name in p['stage1'] + p['stage2'], 'Unplanned case')
    grid, cap = name.split('_')
    return grid, int(cap)


def config_for(base, name, p):
    grid, cap = case_parts(name, p)
    c = copy.deepcopy(base)
    c['numerics'] = {'water_speed_limit_m_s': float(cap)}
    if grid == 'fine': c['run']['target_cell_size_m'] /= 2
    return c


def accepted(record):
    return (record.get('status') == 'accepted' and record.get('solver_exit_code') == 0
            and all(record.get('checks', {}).get(k) == 'passed' for k in
                    ('field', 'time_steps', 'policy', 'input_consistency', 'monitor_deck')))


def stage_gate(session, name, p):
    case_parts(name, p)
    for other in p['stage1'] + p['stage2']:
        f = session / 'cases' / other / 'record.json'
        if f.exists():
            record = load(f)
            require(record['status'] == 'accepted', f'Stop expansion: {other} is {record["status"]}; do not retry or retune')
    if name in p['stage2']:
        require(all((session/'cases'/c/'record.json').exists() and accepted(load(session/'cases'/c/'record.json'))
                    for c in p['stage1']), 'Stage 1 must pass independently before expansion')
        require((session/'preflight_fine.json').is_file(), 'Finer-grid physical preflight required before Stage 2')


def policy_trace(text, maximum):
    """Additional global dt ceiling, retaining the existing formatted-log tolerance."""
    from decimal import Decimal
    pattern = re.compile(r'AMRCLAW:\s*level\s+\d+\s+CFL\s*=\s*\S+\s+dt\s*=\s*(\S+)\s+final t')
    count, largest = 0, Decimal(0)
    for line in text.splitlines():
        m = pattern.search(line)
        if not m: continue
        token = m[1].lower().replace('d', 'e')
        dt = Decimal(token)
        require(dt.is_finite() and dt > 0, 'Invalid time step')
        precision = Decimal(10) ** dt.as_tuple().exponent / 2
        require(dt - precision <= Decimal(str(maximum))*Decimal('1.001') + Decimal('1e-8'),
                f'Declared global dt ceiling violated: {dt}')
        largest = max(largest, dt)
        count += 1
    require(count > 0, 'Missing integration trace')
    return dict(status='passed', steps=count, maximum_printed_dt_s=float(largest), dt_max_s=maximum)


def code_hashes():
    files = ['geoclaw/setrun.py', 'simulation/prepare.py', 'simulation/numerics.py',
             'simulation/monitoring.py', 'simulation/runup_metrics.py', 'simulation/read_output.py',
             'simulation/validate.py', 'simulation/bed_check.py', 'simulation/time_steps.py',
             'simulation/cap_comparison.py', 'simulation/runtime.py', 'simulation/common.py']
    return {f: sha(ROOT/f) for f in files}


def verify_environment(archive, p):
    from simulation.runtime import solver
    base = load(ROOT/'release/frozen_baseline_config.json')
    refs = load(ROOT/'required_private_inputs.json')
    for f, h in refs.items(): require(sha(ROOT/f) == h, 'Wrong required reference input: '+f)
    seal = load(BASE/'provenance.json')
    require(seal['session'] == p['archived_session'], 'Wrong archived session')
    require(base == load(archive/'config.json'), 'Frozen physical configuration differs from archive')
    for f, h in seal['prepared_input_sha256'].items(): require(sha(archive/'inputs'/f) == h, 'Changed prepared input: '+f)
    for f, h in seal['result_files_sha256'].items(): require(sha(BASE/f) == h, 'Changed archived summary: '+f)
    for f, h in code_hashes().items(): require(seal['sealed_code_sha256'][f] == h, 'Changed original computation/acceptance code: '+f)
    require(os.environ.get('LITUYA_RUN_IMAGE_ID') == p['runtime_image'], 'Wrong container image')
    exe, image = solver(base)
    require(image == load(archive/'image_manifest.json'), 'Runtime manifest differs from archived runtime')
    require(sha(exe) == p['solver_sha256'], 'Wrong solver executable')
    return base, exe, image, refs, seal


def verify_session(session, archive, p):
    base, exe, image, refs, seal = verify_environment(archive, p)
    m = load(session/'identity.json')
    require(m['protocol_sha256'] == sha(HERE/'protocol.json') and m['driver_sha256'] == sha(__file__), 'Experiment policy/driver changed')
    require(m['code_sha256'] == code_hashes(), 'Acceptance/measurement code changed')
    require(m['image_manifest'] == image, 'Runtime changed')
    for grid in ('original', 'fine'):
        f = session / f'preflight_{grid}.json'
        if f.exists():
            for name,h in load(f)['prepared_files_sha256'].items():
                require(sha(session/'inputs'/grid/name) == h, f'Prepared input changed: {grid}/{name}')
    return base, exe


def decks(folder, inputs, c, setup, p):
    from geoclaw.setrun import setrun
    from simulation.cap_comparison import verify_monitor_deck
    r = setrun(c, setup, 'slide', inputs)
    policy = p['time_policy']
    r.clawdata.dt_initial = policy['dt_initial_s']
    r.clawdata.dt_max = policy['dt_max_s']
    r.clawdata.cfl_desired = policy['cfl_desired']
    require(r.clawdata.cfl_max == policy['cfl_max'] and r.clawdata.steps_max == policy['steps_max'] and
            r.dtopo_data.dt_max_dtopo == policy['source_dt_max_s'], 'Acceptance/source controls would change')
    folder.mkdir(parents=True, exist_ok=True)
    old = Path.cwd()
    try:
        os.chdir(folder)
        r.write()
        for name in ('topo.data','dtopo.data'):
            f=folder/name
            f.write_text(f.read_text().replace(str(inputs),os.path.relpath(inputs,folder)))
    finally: os.chdir(old)
    return verify_monitor_deck(folder,c,setup)


def normalized_decks(folder):
    return {f.name: re.sub(r'^.*=:\s*speed_limit.*$', '@speed_limit', f.read_text(), flags=re.M)
            for f in sorted(folder.glob('*.data'))}


def preflight(session, archive, grid, p):
    import numpy as np
    from simulation.numerics import cell_average
    from simulation.runup_metrics import artificial_cell_mask
    from simulation.monitoring import monitor_specs, monitor_points
    base, exe, image, refs, seal = verify_environment(archive,p)
    session.mkdir(parents=True,exist_ok=True)
    if (session/'identity.json').exists():
        verify_session(session,archive,p)
    else:
        require(not any(session.iterdir()), 'Refusing unidentified nonempty session')
        # Seal verification reads the archive; no original claims/pointers are changed.
        for f,h in seal['experiment_file_sha256'].items():
            rel=Path(f).relative_to(p['archived_session'])
            require(sha(archive/rel)==h,'Changed archived output: '+str(rel))
        save(session/'identity.json',dict(created_utc=now(),checkpoint=p['checkpoint'],
             protocol_sha256=sha(HERE/'protocol.json'),driver_sha256=sha(__file__),code_sha256=code_hashes(),
             image_manifest=image,runtime_image=p['runtime_image'],required_inputs_sha256=refs,
             archived_prepared_sha256=seal['prepared_input_sha256'],archive_files_verified=len(seal['experiment_file_sha256'])))
    target=session/f'preflight_{grid}.json'
    if target.exists(): return load(target)
    if grid=='fine':
        require(all((session/'cases'/c/'record.json').exists() and accepted(load(session/'cases'/c/'record.json'))
                    for c in p['stage1']), 'Stage 1 must pass before fine preflight')
        for case in p['stage1']: verify_case(session,archive,case,p)
    inputs=session/'inputs'/grid
    require(not inputs.exists(), 'Partial preflight inputs exist; inspect, do not overwrite')
    shutil.copytree(archive/'inputs',inputs)
    setup=load(inputs/'setup.json')
    require([setup['nx'],setup['ny']]==p['grids']['original'], 'Original dimensions mismatch')
    with np.load(inputs/'terrain_arrays.npz') as f: terrain={k:f[k] for k in f.files}
    original=copy.deepcopy(terrain)
    setup_original=copy.deepcopy(setup)
    c=copy.deepcopy(base)
    if grid=='fine':
        nx,ny=p['grids']['fine']; w,s,e,n=setup['domain_xyxy_m']
        terrain['xe']=np.linspace(w,e,nx+1); terrain['ye']=np.linspace(s,n,ny+1)
        terrain['bcell']=cell_average(terrain['b0'],terrain['x'],terrain['y'],terrain['xe'],terrain['ye'])
        with np.load(inputs/'source_arrays.npz') as src:
            dz=np.zeros_like(terrain['b0']); j,i=src['global_origin']; d=src['dz'][-1]
            dz[j:j+d.shape[0],i:i+d.shape[1]]=d
        terrain['expected_final_dz_cells']=cell_average(dz,terrain['x'],terrain['y'],terrain['xe'],terrain['ye'])
        for k in ('bcell','expected_final_dz_cells'):
            averaged=terrain[k].reshape(setup['ny'],2,setup['nx'],2).mean(axis=(1,3))
            require(np.allclose(averaged,original[k],rtol=0,atol=1e-8),'Refined integration does not preserve coarse averages: '+k)
        setup.update(nx=nx,ny=ny)
        c['run']['target_cell_size_m']/=2
        for g in setup['gauges']:
            i=np.searchsorted(terrain['xe'],g['x_m'],side='right')-1
            j=np.searchsorted(terrain['ye'],g['y_m'],side='right')-1
            g['initial_cell_bed_m']=float(terrain['bcell'][j,i])
            require(not g['required_initially_wet'] or g['initial_cell_bed_m']<0,'Required wet gauge became dry: '+g['label'])
        np.savez_compressed(inputs/'terrain_arrays.npz',**terrain)
        save(inputs/'setup.json',setup)
        save(inputs/'config.json',c)
    fixed=('terrain.tt3','slide.dtt3','source_arrays.npz','source_history.csv')
    for f in fixed: require(sha(inputs/f)==sha(archive/'inputs'/f),'Changed physical terrain/source: '+f)
    for k in ('x','y','base','b0','s0','excluded','wall','geometry_weight'):
        require(np.array_equal(terrain[k],original[k],equal_nan=True),'Physical nodal geometry changed: '+k)
    artificial=artificial_cell_mask(terrain,include_virtual_wall=c['geometry']['include_published_virtual_wall'])
    monitors={}
    for spec in monitor_specs(c)[0]:
        x,y=monitor_points(spec,setup,require_static=True)
        i=np.searchsorted(terrain['xe'],x,side='right')-1;j=np.searchsorted(terrain['ye'],y,side='right')-1
        monitors[spec['name']]=dict(points=len(x),eligible_natural_land_cells=int(np.sum((terrain['bcell'][j,i]>0)&~artificial[j,i])),
                                  requested_bounds_xyxy_m=spec['bounds_xyxy_m'],sampled_bounds_xyxy_m=[float(x.min()),float(y.min()),float(x.max()),float(y.max())])
    canonical=None; generated={}
    for cap in p['speed_limits_m_s']:
        name=f'{grid}_{cap:03d}';folder=session/'cases'/name
        cfg=config_for(base,name,p)
        require(not folder.exists(),'Existing case folder before preflight: '+name)
        decks(folder,inputs,cfg,setup,p)
        save(folder/'config.json',cfg)
        current=normalized_decks(folder)
        if canonical is None:canonical=current
        require(current==canonical,'Generated decks differ beyond speed_limit')
        generated[name]={f.name:sha(f) for f in folder.iterdir() if f.is_file()}
    record=dict(status='passed',grid=grid,completed_utc=now(),nx=setup['nx'],ny=setup['ny'],
         dx_m=float(terrain['xe'][1]-terrain['xe'][0]),dy_m=float(terrain['ye'][1]-terrain['ye'][0]),
         domain_xyxy_m=setup['domain_xyxy_m'],source_bounds_xyxy_m=setup['source_bounds_xyxy_m'],
         unchanged_physical_files_sha256={f:sha(inputs/f) for f in fixed},
         physical_nodal_geometry_unchanged=True,source_history_unchanged=True,coarse_averages_preserved=True,
         note='Source/terrain nodal spacing remains 15 m. Four-node source padding remains 60 m. Solver cells alone change; boundary-cell masks and sampled gauge beds can differ.',
         gauges=setup['gauges'],monitors=monitors,artificial_cells=int(artificial.sum()),
         prepared_files_sha256={f.name:sha(f) for f in inputs.iterdir() if f.is_file()},generated_cases_sha256=generated)
    save(target,record)
    return record


def metrics(folder,inputs,config,setup,validation):
    import numpy as np
    from simulation.runup_metrics import artificial_cell_mask
    from simulation.read_output import read_gauge
    with np.load(inputs/'terrain_arrays.npz') as f: a={k:f[k] for k in f.files}
    mask=artificial_cell_mask(a,include_virtual_wall=config['geometry']['include_published_virtual_wall'])
    m=np.loadtxt(folder/'fgmax0002.txt',ndmin=2)
    i=np.searchsorted(a['xe'],m[:,0],side='right')-1;j=np.searchsorted(a['ye'],m[:,1],side='right')-1
    wet=(m[:,2]==1)&(m[:,3]>0)&~mask[j,i]&(m[:,4]>=config['checks']['runup_depth_threshold_m'])
    dx=(setup['domain_xyxy_m'][2]-setup['domain_xyxy_m'][0])/setup['nx']
    dy=(setup['domain_xyxy_m'][3]-setup['domain_xyxy_m'][1])/setup['ny']
    result=dict(runup_expanded_m=validation['runup_primary']['maximum_wetted_cell_elevation_m'],
                runup_legacy_m=validation['opposite_SW_slope_max_wetted_cell_elevation_m'],
                wetted_eligible_cells=int(wet.sum()),wetted_area_km2=float(wet.sum()*dx*dy/1e6),
                max_land_depth_m=float(m[wet,4].max()),peak_locations=validation['runup_primary']['peak_locations'],
                boundary_touching=validation['runup_primary']['peak_touches_monitor_boundary'],gauges={})
    for g in setup['gauges']:
        if g['label'] not in ('P2','P3','P5'):continue
        raw=read_gauge(folder,g['id']);live=raw[raw[:,2]>config['water']['dry_tolerance_m']]
        require(len(live)>0,'No wet samples for gauge '+g['label'])
        k=int(np.argmax(live[:,5]))
        result[g['label']+'_eta_m']=float(live[k,5])
        result['gauges'][g['label']]=dict(peak_time_s=float(live[k,1]),first_time_s=float(raw[0,1]),last_time_s=float(raw[-1,1]),samples=len(raw))
    return result


def verify_case(session,archive,name,p):
    verify_session(session,archive,p)
    record=load(session/'cases'/name/'record.json')
    require(accepted(record), f'{name}: not accepted')
    for f,h in record['files_sha256'].items(): require(sha(session/'cases'/name/f)==h,'Changed case evidence: '+name+'/'+f)
    return record


def run(session,archive,name,p):
    from simulation.time_steps import audit
    from simulation.validate import validate
    from simulation.cap_comparison import verify_monitor_deck, reset_summary
    base,exe=verify_session(session,archive,p)
    grid,cap=case_parts(name,p);folder=session/'cases'/name;inputs=session/'inputs'/grid
    if (folder/'record.json').exists():return verify_case(session,archive,name,p)
    stage_gate(session,name,p)
    pre=load(session/f'preflight_{grid}.json')
    for f,h in pre['generated_cases_sha256'][name].items(): require(sha(folder/f)==h,'Changed case deck: '+f)
    require(not any(folder.glob('fort.*')) and not (folder/'solver.log').exists(),'Existing unclaimed solver outputs')
    config=load(folder/'config.json');setup=load(inputs/'setup.json')
    require(config==config_for(base,name,p),'Case configuration mismatch')
    verify_monitor_deck(folder,config,setup)
    with (folder/'claim.json').open('x') as f:json.dump(dict(started_utc=now(),pid=os.getpid()),f)
    rec=dict(case=name,grid=grid,cap_m_s=cap,status='running',started_utc=now(),checks={},errors=[],metrics=None)
    save(folder/'record.json',rec);started=time.monotonic()
    try:
        with (folder/'solver.log').open('w') as log:
            rec['solver_exit_code']=subprocess.run([str(exe)],cwd=folder,stdout=log,stderr=subprocess.STDOUT).returncode
        require(rec['solver_exit_code']==0,'Solver failed')
        for label,check in [('time_steps',lambda:audit(folder,config,'slide')),
                            ('policy',lambda:policy_trace((folder/'fort.amr').read_text(),p['time_policy']['dt_max_s'])),
                            ('field',lambda:validate(folder,'slide',config,setup,inputs,baseline=None)),
                            ('monitor_deck',lambda:verify_monitor_deck(folder,config,setup)),
                            ('input_consistency',lambda:verify_session(session,archive,p))]:
            try:
                value=check();rec['checks'][label]='passed'
                if label=='policy':save(folder/'policy_check.json',value)
                if label=='field':rec['field_validation']=value
            except (ValueError,KeyError,OSError) as exc:
                rec['checks'][label]='failed';rec['errors'].append(label+': '+str(exc))
        if not rec['errors']:
            rec['metrics']=metrics(folder,inputs,config,setup,rec['field_validation'])
            rec['status']='accepted'
        else:rec['status']='checks_failed'
    except BaseException as exc:
        rec['status']='failed_or_interrupted';rec['errors'].append(str(exc))
    rec.update(completed_utc=now(),wall_seconds=time.monotonic()-started,limiter=reset_summary(folder))
    rec['files_sha256']={f.name:sha(f) for f in folder.iterdir() if f.is_file() and f.name not in ('record.json','claim.json')}
    save(folder/'record.json',rec)
    print(json.dumps({k:rec[k] for k in ('case','status','checks','errors','metrics','wall_seconds')},indent=2),flush=True)
    return rec


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['preflight','run','check'])
    parser.add_argument('--session',type=Path,default=Path('/session'))
    parser.add_argument('--archive',type=Path,default=Path('/archive'))
    parser.add_argument('--grid',choices=['original','fine'])
    parser.add_argument('--case')
    args=parser.parse_args();p=protocol()
    if args.action=='preflight':print(json.dumps(preflight(args.session,args.archive,args.grid,p),indent=2))
    elif args.action=='run':
        record=run(args.session,args.archive,args.case,p)
        if not accepted(record):sys.exit(2)
    else:
        verify_session(args.session,args.archive,p)
        for name in p['stage1']+p['stage2']:
            f=args.session/'cases'/name/'record.json'
            if f.exists():
                r=load(f)
                for rel,h in r['files_sha256'].items():require(sha(f.parent/rel)==h,'Changed saved evidence')
                print(name,r['status'],'seal verified')
            else:print(name,'unattempted')


if __name__=='__main__':main()
