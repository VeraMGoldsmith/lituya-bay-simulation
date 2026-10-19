"""Exactly three fixed-source cases; default action is a gated local preflight.

No source search, no cap optimisation, no reuse of an unverified result.  The
runtime Clawpack writer must produce matching input decks before water runs.
Software tests may replace collaborators; production never fabricates fields.
"""
from __future__ import annotations

import argparse
import copy
import csv
import datetime as dt
import html
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid
import zipfile

from .common import ROOT, hash_json, inside, load, now, save, sha
from .prepare import prepare
from .runtime import logged, solver
from .time_steps import audit as audit_time_steps
from .validate import validate
from .monitoring import monitor_specs, monitor_points
from geoclaw.setrun import write_data

CAPS = (50, 100, 200)
CASE_NAMES = tuple(f'cap_{cap:03d}' for cap in CAPS)
NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][+-]?\d+)?'
SPEED_LINE = re.compile(r'^\s*(' + NUMBER + r')\s*=:\s*speed_limit\b.*$', re.M)
MIN_DATA = {'claw.data', 'amr.data', 'geoclaw.data', 'topo.data', 'dtopo.data',
            'gauges.data', 'fgmax_grids.data'}


class IntegrityError(ValueError):
    """Setup/provenance fault: abort the experiment, not a water-solver result."""


def frozen_config(root=ROOT):
    root = Path(root)
    contract = load(root / 'release/comparison_contract.json')
    path = root / 'release/frozen_baseline_config.json'
    if contract['caps_m_s'] != list(CAPS) or sha(path) != contract['frozen_config_sha256']:
        raise IntegrityError('Frozen comparison contract or baseline changed.')
    c = load(path)
    if 'numerics' in c or c['run']['duration_s'] != 420.0:
        raise IntegrityError('Unexpected frozen numerical overrides or duration.')
    return c, contract


def case_configs(base):
    if 'numerics' in base:
        raise IntegrityError('Base must not already contain a speed-limit override.')
    configs = {}
    for cap, name in zip(CAPS, CASE_NAMES):
        c = copy.deepcopy(base)
        c['numerics'] = {'water_speed_limit_m_s': float(cap)}
        configs[name] = c
    return configs


def code_fingerprint(root=ROOT):
    """Files affecting preparation, numerical setup, execution or diagnostics."""
    root = Path(root)
    paths = [root / n for n in ['Dockerfile', 'run_comparison.sh', 'run.sh', 'comparison.py',
              'pyproject.toml', 'config.json', 'collect_comparison.py', 'geoclaw/Makefile',
              'release/frozen_baseline_config.json',
              'release/comparison_contract.json', 'release/RELEASE_ID', 'release/ISOLATED_COMPARISON']]
    for folder in ['simulation', 'geoclaw', 'tools', 'environment', 'data/reference', 'release/archived_baseline_solver_data']:
        paths.extend(p for p in (root / folder).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts
                     and p.suffix in {'.py', '.json', '.txt', '.npz', '.data'})
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(set(paths))}


def checked_solver(c):
    try:
        return solver(c)
    except Exception as exc:
        raise IntegrityError(str(exc).replace('bash run.sh --build', 'bash run_comparison.sh preflight')
                             .replace('bash run.sh', 'bash run_comparison.sh preflight')) from exc


def input_hashes(folder):
    return {p.name: sha(p) for p in sorted(Path(folder).iterdir()) if p.is_file()}


def check_physical_inputs(inputs, contract):
    for filename, key in [('terrain.tt3','terrain_file_sha256'), ('slide.dtt3','source_file_sha256')]:
        if sha(Path(inputs) / filename) != contract[key]:
            raise IntegrityError(f'{filename} differs from the archived frozen baseline.')


def numerical_records(folder):
    """Normalize the cap and its value-field padding; preserve all other bytes."""
    folder = Path(folder)
    paths = {p.name:p for p in folder.glob('*.data')}
    if not MIN_DATA <= paths.keys():
        raise IntegrityError('Generated solver data files are missing.')
    text = paths['geoclaw.data'].read_text()
    matches = SPEED_LINE.findall(text)
    if len(matches) != 1:
        raise IntegrityError('Expected exactly one explicit generated speed_limit.')
    cap = float(matches[0].replace('D','E').replace('d','e'))
    # The real Clawpack writer left-justifies values in a 20-character field.
    # 50.0 and 100.0 therefore have different padding before =:. Normalize
    # only that padding along with the allowed cap; preserve the field name,
    # comments, surrounding lines, and every other solver setting.
    normalized = SPEED_LINE.sub(lambda m: m[0][:m.start(1)-m.start()] + '<CAP>' +
                                ' ' + m[0][m.end(1)-m.start():].lstrip(' \t'), text)
    contents = {name:p.read_text() for name,p in paths.items()}
    contents['geoclaw.data'] = normalized
    return cap, contents


def canonical_deck(contents):
    """Compare controls to the archived baseline, ignoring comments/path depth."""
    result={}
    for name,text in contents.items():
        if name=='fgmax_grids.data':continue  # deliberately expanded; separately verified
        lines=[]
        for row in text.splitlines():
            row=row.split('#',1)[0].strip()
            if not row:continue
            for asset in ('terrain.tt3','slide.dtt3'):
                row=re.sub(r"'[^']*/"+re.escape(asset)+r"'", "'@"+asset+"'", row)
            lines.append(' '.join(row.split()))
        result[name]='\n'.join(lines)
    return result


def verify_monitor_deck(folder, base, setup):
    """Check generated fgmax point lists against the common measurement spec."""
    text = (Path(folder)/'fgmax_grids.data').read_text()
    # Ignore comments; the point_style=0 format consists of scalars then XY pairs.
    lines = [line.split('#',1)[0].strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    def scalar(line):
        return float(line.split('=:',1)[0].strip().replace('D','E').replace('d','e'))
    specs, primary = monitor_specs(base)
    if len(lines) < 2 or scalar(lines[0]) != 1 or scalar(lines[1]) != len(specs):
        raise IntegrityError('Generated fgmax header differs from the two-monitor specification.')
    cursor = 2
    counts = {}
    import numpy as np
    for spec in specs:
        X,Y = monitor_points(spec, setup, require_static=True)
        expected = [spec['fgno'], 0., base['run']['duration_s'], 0., 1.,
                    base['checks']['runup_depth_threshold_m'], 0., 0., len(X)]
        if len(lines) < cursor + 9 + len(X):
            raise IntegrityError('Generated fgmax points are incomplete.')
        values = [scalar(s) for s in lines[cursor:cursor+9]]
        if not np.allclose(values, expected, rtol=0, atol=1.e-10):
            raise IntegrityError('Generated fgmax controls changed; require per-step, cell-average monitoring.')
        points = np.array([[float(v) for v in row.split()] for row in lines[cursor+9:cursor+9+len(X)]])
        if points.shape != (len(X),2) or not np.allclose(points, np.c_[X,Y], rtol=0, atol=1.e-8):
            raise IntegrityError('Generated fgmax point coordinates do not match the common specification.')
        cursor += 9 + len(X)
        counts[spec['name']] = len(X)
    if cursor != len(lines):
        raise IntegrityError('Unexpected trailing fgmax records.')
    return {'primary':primary, 'points':counts, 'dt_check_s':0., 'interp_method':0}


def verify_decks(session, base, setup):
    session = Path(session)
    configs = case_configs(base)
    reference = None
    archived_dir=ROOT/'release/archived_baseline_solver_data'
    _,archived=numerical_records(archived_dir)
    archived=canonical_deck(archived)
    records = {}
    for name, expected_cap in zip(CASE_NAMES, CAPS):
        folder = session / 'cases' / name
        if load(folder/'config.json') != configs[name]:
            raise IntegrityError(f'Case configuration changed: {name}.')
        cap, normalized = numerical_records(folder)
        if cap != expected_cap:
            raise IntegrityError(f'{name} generated speed_limit is {cap}, expected {expected_cap}.')
        if canonical_deck(normalized) != archived:
            raise IntegrityError('Generated controls differ from the archived baseline beyond the allowed cap/monitor changes.')
        if reference is None:
            reference = normalized
        elif normalized != reference:
            different = sorted(k for k in normalized.keys() | reference.keys()
                               if normalized.get(k) != reference.get(k))
            raise IntegrityError('Non-cap solver settings differ: '+', '.join(different))
        monitor = verify_monitor_deck(folder, base, setup)
        records[name] = {'speed_limit_m_s':cap, 'monitor':monitor,
                         'data_sha256':{p.name:sha(p) for p in sorted(folder.glob('*.data'))},
                         'config_sha256':sha(folder/'config.json')}
    return {'status':'passed', 'only_deck_difference':'speed_limit numeric value', 'cases':records}


def new_session(root=ROOT):
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    path = Path(root)/'comparison_runs'/(stamp+'_'+uuid.uuid4().hex[:8])
    path.mkdir(parents=True, exist_ok=False)
    return path


def prepare_session(session, base, contract):
    """Called by preflight only; shared source is created once, not per case."""
    session = Path(session)
    setup, checks = prepare(base, session/'inputs')
    check_physical_inputs(session/'inputs', contract)
    save(session/'config.json', base)
    for name,c in case_configs(base).items():
        folder = session/'cases'/name
        folder.mkdir(parents=True, exist_ok=False)
        save(folder/'config.json', c)
        write_data(folder, session/'inputs', c, setup, 'slide')
    decks = verify_decks(session, base, setup)
    save(session/'generated_settings_check.json',decks)
    return setup, checks, decks


def preflight(root=ROOT):
    root=Path(root)
    session = new_session(root)
    record = {'status':'running', 'created_utc':now(), 'new_lituya_integrations':0,
              'scope':'input checks plus tiny synthetic solver test; not a Lituya water run'}
    save(session/'preflight.json',record)
    save(root/'comparison_results/latest_attempt.json',{'session':session.relative_to(root).as_posix()})
    try:
        base,contract = frozen_config(root)
        exe,image = checked_solver(base)
        before = code_fingerprint(root)
        save(session/'image_manifest.json',image)
        # Run both small synthetic cases with the actual, verified executable.
        logged([sys.executable, '-m','tools.smoke','--executable',str(exe),
                '--report',str(session/'synthetic_smoke.json')], root, session/'synthetic_smoke.log')
        smoke=load(session/'synthetic_smoke.json')
        if smoke.get('status') != 'passed':
            raise IntegrityError('Synthetic executable smoke test did not pass.')
        setup,checks,decks=prepare_session(session,base,contract)
        if before != code_fingerprint(root):
            raise IntegrityError('Code changed during preflight.')
        record.update(status='passed', completed_utc=now(),
                      code_sha256=before, inputs_sha256=input_hashes(session/'inputs'),
                      generated_decks=decks,
                      solver_sha256=image['solver_sha256'],
                      image_manifest_sha256=hash_json(image),
                      docker_image_id=os.environ.get('LITUYA_RUN_IMAGE_ID'),
                      synthetic_cases=smoke.get('cases',[]))
        save(session/'preflight.json',record)
        save(root/'comparison_results/latest_preflight.json',{'session':session.relative_to(root).as_posix()})
        print('PREFLIGHT PASSED. No Lituya water cases were run.\nNext production command: bash run_comparison.sh run')
    except BaseException as exc:
        record.update(status='failed', error=str(exc), completed_utc=now())
        save(session/'preflight.json',record)
        raise
    finally:
        render_summary(session)
    return session


def current_session(root=ROOT):
    root=Path(root)
    pointer=root/'comparison_results/latest_preflight.json'
    if not pointer.is_file():
        raise IntegrityError('No passed preflight. Run bash run_comparison.sh preflight first.')
    selected=load(pointer)['session']
    latest=root/'comparison_results/latest_attempt.json'
    if not latest.is_file() or load(latest)['session'] != selected:
        raise IntegrityError('The latest preflight attempt did not pass; refusing fallback to an older session.')
    return inside(root,selected)


def assert_sealed(session, root, base, contract):
    record=load(Path(session)/'preflight.json')
    if record.get('status') != 'passed':
        raise IntegrityError('Preflight was not successful.')
    if record['code_sha256'] != code_fingerprint(root):
        raise IntegrityError('Code or frozen inputs changed after preflight; do a new preflight.')
    if record['inputs_sha256'] != input_hashes(Path(session)/'inputs'):
        raise IntegrityError('Shared prepared inputs changed after preflight.')
    check_physical_inputs(Path(session)/'inputs', contract)
    setup=load(Path(session)/'inputs/setup.json')
    if verify_decks(session,base,setup) != record['generated_decks']:
        raise IntegrityError('Generated input decks changed after preflight.')
    return setup


def reset_summary(folder):
    """Streaming diagnostic counts, not integrated energy or unique parcels."""
    path=Path(folder)/'fort.amr'
    result={'status':'not_available', 'logged_b4step2_events':0,
            'events_at_depth_ge_10_m':0, 'maximum_printed_depth_m':None,
            'first_time_s':None,'last_time_s':None,
            'note':'Rounded b4step2 log events only; not all limiting operations or energy loss.'}
    if not path.is_file():
        return result
    t=None
    time_re=re.compile(r'b4step2 at t\s*=\s*('+NUMBER+')')
    reset_re=re.compile(r'reset s\s*=\s*('+NUMBER+r')\s+h\s*=\s*('+NUMBER+')')
    def number(s):return float(s.replace('D','E').replace('d','e'))
    with path.open(errors='replace') as f:
        for line in f:
            m=time_re.search(line)
            if m:t=number(m[1])
            m=reset_re.search(line)
            if not m:continue
            h=number(m[2])
            result['logged_b4step2_events']+=1
            result['events_at_depth_ge_10_m']+=int(h>=10)
            result['maximum_printed_depth_m']=max(h,result['maximum_printed_depth_m'] or 0.)
            if result['first_time_s'] is None:result['first_time_s']=t
            result['last_time_s']=t
    result['status']='parsed'
    return result


def run_experiment(root=ROOT):
    root=Path(root)
    session=current_session(root)
    if (session/'experiment.json').exists() or (session/'production_claim.json').exists():
        raise IntegrityError('This experiment was already started. Existing results will not be overwritten; contact the reviewer before starting another preflight.')
    base,contract=frozen_config(root)
    setup=assert_sealed(session,root,base,contract)
    exe,image=checked_solver(base)
    pre=load(session/'preflight.json')
    if image['solver_sha256']!=pre['solver_sha256'] or hash_json(image)!=pre['image_manifest_sha256']:
        raise IntegrityError('Solver/build identity differs from preflight.')
    current_image=os.environ.get('LITUYA_RUN_IMAGE_ID')
    if pre.get('docker_image_id') != current_image:
        raise IntegrityError('Docker image differs from preflight; no water cases started.')
    for name in CASE_NAMES:
        folder=session/'cases'/name
        if any(folder.glob('fort.*')) or (folder/'solver.log').exists():
            raise IntegrityError('Existing water output detected; refusing to overwrite it.')
    # Atomic one-time claim prevents concurrent launches from sharing output.
    try:
        with (session/'production_claim.json').open('x') as f:
            json.dump({'claimed_utc':now(), 'process_id':os.getpid()}, f)
    except FileExistsError as exc:
        raise IntegrityError('This experiment was already claimed by another launch.') from exc
    state={'status':'running','started_utc':now(),'planned_cases':list(CASE_NAMES),
           'historically_validated':False, 'cap_chosen_by_runup':False,
           'cases':{name:{'status':'not_started','speed_limit_m_s':cap} for name,cap in zip(CASE_NAMES,CAPS)}}
    save(session/'experiment.json',state)
    save(root/'comparison_results/latest_attempt.json',{'session':session.relative_to(root).as_posix()})
    try:
        for name,cap in zip(CASE_NAMES,CAPS):
            assert_sealed(session,root,base,contract)
            if sha(exe) != pre['solver_sha256']:
                raise IntegrityError('Executable changed during comparison.')
            folder=session/'cases'/name
            c=load(folder/'config.json')
            status=state['cases'][name]
            status.update(status='running',started_utc=now())
            save(session/'experiment.json',state)
            print(f'\n{name}: same 30 s / 1400 m source; water cap {cap} m/s; 420 simulated seconds.',flush=True)
            started=time.monotonic()
            try:
                # Invocation failures are infrastructure errors, not numerical outcomes.
                try:
                    logged([exe],folder,folder/'solver.log')
                except RuntimeError as exc:
                    status.update(status='solver_failed',error=str(exc))
                else:
                    failures=[]
                    try:
                        audit_time_steps(folder,c,'slide')
                    except ValueError as exc:
                        failures.append('Time-step check: '+str(exc))
                    try:
                        result=validate(folder,'slide',c,setup,session/'inputs',baseline=None)
                        status['validation']=result
                    except (ValueError, OSError, KeyError) as exc:
                        failures.append('Field/measurement check: '+str(exc))
                    if failures:
                        status.update(status='checks_failed',errors=failures)
                    else:
                        status['status']='completed_basic_checks'
            finally:
                status.update(completed_utc=now(), solver_and_checks_wall_seconds=time.monotonic()-started)
                status['limiter_summary']=reset_summary(folder)
                save(folder/'limiter_summary.json',status['limiter_summary'])
                save(session/'experiment.json',state)
                render_summary(session)
            # A source/deck change after the final case must also be caught.
            assert_sealed(session,root,base,contract)
        if sha(exe) != pre['solver_sha256']:
            raise IntegrityError('Executable changed during the final case.')
        good=all(v['status']=='completed_basic_checks' for v in state['cases'].values())
        state.update(status='completed_basic_checks' if good else 'completed_with_failures', completed_utc=now())
        print('Three planned cases processed. No additional caps or source candidates will be run.',flush=True)
    except BaseException as exc:
        state.update(status='interrupted' if isinstance(exc,KeyboardInterrupt) else 'aborted_infrastructure',error=str(exc),completed_utc=now())
        for item in state['cases'].values():
            if item['status']=='running':item.update(status='interrupted_or_aborted',error=str(exc))
        raise
    finally:
        save(session/'experiment.json',state)
        render_summary(session)
    return session,state


def render_summary(session):
    session=Path(session)
    state=load(session/'experiment.json') if (session/'experiment.json').exists() else {}
    pre=load(session/'preflight.json') if (session/'preflight.json').exists() else {}
    rows=[]
    for name,cap in zip(CASE_NAMES,CAPS):
        item=state.get('cases',{}).get(name,{'status':'not_run'})
        val=item.get('validation',{})
        primary=val.get('runup_primary') or {}
        monitors=(val.get('runup_diagnostics') or {}).get('monitors',{})
        # Failed or partial cases never become valid run-up values in the table.
        good=item.get('status')=='completed_basic_checks'
        rows.append({'case':name,'water_speed_limit_m_s':cap,'status':item['status'],
                     'runup_expanded_m':primary.get('maximum_wetted_cell_elevation_m') if good else None,
                     'runup_legacy_m':monitors.get('legacy',{}).get('maximum_wetted_cell_elevation_m') if good else None,
                     'boundary_touching':primary.get('peak_touches_monitor_boundary') if good else None,
                     'logged_reset_events':item.get('limiter_summary',{}).get('logged_b4step2_events'),
                     'wall_seconds':item.get('solver_and_checks_wall_seconds')})
    differences={}
    comparable = state.get('status') in {'completed_basic_checks', 'completed_with_failures'}
    for a,b in [(0,1),(1,2),(0,2)]:
        x,y=rows[a]['runup_expanded_m'],rows[b]['runup_expanded_m']
        differences[f'R{CAPS[b]}_minus_R{CAPS[a]}_m']=None if not comparable or x is None or y is None else y-x
    summary={'preflight_status':pre.get('status','not_run'),'experiment_status':state.get('status','not_run'),
             'cases':rows,'setting_differences':differences,
             'historically_validated':False,'note':'No preferred cap is selected. Passing checks does not establish convergence or historical validity.'}
    save(session/'comparison_summary.json',summary)
    with (session/'comparison_summary.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    table=''.join('<tr>'+''.join('<td>'+html.escape('Not available' if r[k] is None else str(r[k]))+'</td>' for k in rows[0])+'</tr>' for r in rows)
    header=''.join('<th>'+html.escape(k.replace('_',' '))+'</th>' for k in rows[0])
    message=html.escape(summary['note'])
    (session/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Lituya fixed-source comparison</title>'
        '<style>body{font:16px system-ui;margin:3em;max-width:1200px}table{border-collapse:collapse}td,th{padding:10px;border:1px solid #aaa;text-align:left}th{background:#eee}</style>'
        '<h1>Lituya fixed-source speed-limit comparison</h1>'
        '<p>Preflight: '+html.escape(summary['preflight_status'])+'; experiment: '+html.escape(summary['experiment_status'])+'</p>'
        '<table><tr>'+header+'</tr>'+table+'</table><p>'+message+'</p>'
        '<p>50 / 100 / 200 m/s are numerical test settings, not historical water velocities.</p>')
    return summary


def collect(root=ROOT):
    """Small diagnostics only; explicit manifest lists omitted raw water fields."""
    root=Path(root)
    pointer=root/'comparison_results/latest_attempt.json'
    if not pointer.is_file():
        raise IntegrityError('No comparison attempt exists to collect.')
    session=inside(root,load(pointer)['session'])
    destination=root/f'lituya-comparison-diagnostics-{session.name}-{uuid.uuid4().hex[:6]}.zip'
    manifest={'session':session.relative_to(root).as_posix(),'included':[],'omitted':[],
              'note':'Full water frames and large prepared arrays are omitted; source/config hashes retained.'}
    with zipfile.ZipFile(destination,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(session.rglob('*')):
            if not p.is_file():continue
            rel=p.relative_to(session)
            if p.is_symlink():
                raise IntegrityError('Diagnostic collector refuses symlinked files.')
            permitted=(p.suffix in {'.json','.data','.csv','.html'} or
                       p.name in {'fort.amr','solver.log','synthetic_smoke.log'} or
                       (p.name.startswith(('fgmax','gauge','fort.t')) and p.suffix!='.npz'))
            if permitted and p.stat().st_size<=20*1024*1024:
                z.write(p,'experiment/'+rel.as_posix());manifest['included'].append(rel.as_posix())
            else:manifest['omitted'].append({'path':rel.as_posix(),'size_bytes':p.stat().st_size})
        z.writestr('manifest.json',json.dumps(manifest,indent=2))
    print('Diagnostics archive: '+str(destination),flush=True)
    return destination


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',nargs='?',default='preflight',choices=['preflight','run','collect','status'])
    args=parser.parse_args(argv)
    try:
        if args.action=='preflight':
            preflight();collect()
        elif args.action=='run':
            _,state=run_experiment();collect()
            return 0 if state['status']=='completed_basic_checks' else 3
        elif args.action=='collect':collect()
        else:
            pointer=load(ROOT/'comparison_results/latest_attempt.json')
            print(json.dumps(render_summary(inside(ROOT,pointer['session'])),indent=2))
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        print('STOPPED: '+str(exc),file=sys.stderr,flush=True)
        if args.action in {'preflight','run'}:
            try:collect()
            except Exception as collection_error:print('Collection unavailable: '+str(collection_error),file=sys.stderr)
        return 130 if isinstance(exc,KeyboardInterrupt) else 2


if __name__=='__main__':
    raise SystemExit(main())
