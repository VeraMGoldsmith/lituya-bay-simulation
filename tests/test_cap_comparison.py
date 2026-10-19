"""Software/contract tests. Mocked water results are NOT hydrodynamic runs."""
import copy
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
import zipfile

import numpy as np
import pytest

from simulation import cap_comparison as cap
from simulation.common import ROOT, save, load, sha, hash_json
from simulation.monitoring import monitor_points, monitor_specs
from geoclaw import setrun as geo

BASE_SETUP={'domain_xyxy_m':[-1010.,-8775.,5800.,4800.], 'nx':227,'ny':453,
            'source_bounds_xyxy_m':[1120.,2370.,2200.,4725.], 'gauges':[], 'source_stop_s':30.}
FIXTURES=ROOT/'tests/fixtures/archived_baseline_deck'


def fixture_writer(folder, inputs, config, setup, case):
    """Copies archived settings; formats mock point lists; never invokes GeoClaw."""
    assert case=='slide'
    folder=Path(folder);folder.mkdir(exist_ok=True,parents=True)
    for f in FIXTURES.glob('*.data'):shutil.copyfile(f,folder/f.name)
    path=folder/'geoclaw.data'
    path.write_text(cap.SPEED_LINE.sub(f"{config['numerics']['water_speed_limit_m_s']} =: speed_limit",path.read_text()))
    lines=['1 =: num_fgmax_val','2 =: num_fgmax_grids']
    specs,_=monitor_specs(config)
    for spec in specs:
        X,Y=monitor_points(spec,setup,require_static=True)
        values=[spec['fgno'],0,config['run']['duration_s'],0,1,config['checks']['runup_depth_threshold_m'],0,0,len(X)]
        lines.extend(map(str,values))
        lines.extend(f'{x:.12f} {y:.12f}' for x,y in zip(X,Y))
    (folder/'fgmax_grids.data').write_text('\n'.join(lines)+'\n')


@pytest.fixture
def decks(tmp_path):
    base,contract=cap.frozen_config()
    session=tmp_path/'comparison'
    for name,c in cap.case_configs(base).items():
        folder=session/'cases'/name
        fixture_writer(folder,session/'inputs',c,BASE_SETUP,'slide')
        save(folder/'config.json',c)
    return session,base,contract


def test_frozen_baseline_and_only_numerical_difference():
    base,contract=cap.frozen_config()
    original=copy.deepcopy(base)
    configs=cap.case_configs(base)
    assert list(configs)==list(cap.CASE_NAMES)
    assert [c['numerics']['water_speed_limit_m_s'] for c in configs.values()]==[50.,100.,200.]
    for c in configs.values():
        q=copy.deepcopy(c);q.pop('numerics');assert q==original
    configs['cap_050']['source']['volume_m3']=1
    assert base==original and configs['cap_100']['source']==original['source']
    with pytest.raises(cap.IntegrityError):cap.case_configs({'numerics':{}})


@pytest.mark.parametrize('fault',['hash','caps','duration','numerics'])
def test_frozen_contract_rejects_changed_baseline(tmp_path,fault):
    base,contract=cap.frozen_config()
    release=tmp_path/'release';release.mkdir()
    target=release/'frozen_baseline_config.json'
    shutil.copy(ROOT/'release/frozen_baseline_config.json',target)
    if fault=='hash':target.write_text('{}')
    elif fault=='caps':contract['caps_m_s']=[50,100,300]
    else:
        if fault=='duration':base['run']['duration_s']=60
        else:base['numerics']={}
        save(target,base);contract['frozen_config_sha256']=sha(target)
    save(release/'comparison_contract.json',contract)
    with pytest.raises(cap.IntegrityError):cap.frozen_config(tmp_path)


def test_all_archived_deck_fields_equal_except_cap(decks):
    session,base,_=decks
    result=cap.verify_decks(session,base,BASE_SETUP)
    assert result['status']=='passed'
    assert result['cases']['cap_200']['monitor']['points']=={'legacy':2491,'expanded':10318}
    assert result['cases']['cap_100']['speed_limit_m_s']==100


@pytest.mark.parametrize('fault',['cap','duplicate','missing_speed','missing_data','friction','config','added_data','monitor_step','monitor_points','monitor_tail','monitor_header','monitor_short'])
def test_decks_reject_uncontrolled_changes(decks,fault):
    session,base,_=decks
    folder=session/'cases/cap_100'
    geo_file=folder/'geoclaw.data'
    if fault=='cap':geo_file.write_text(geo_file.read_text().replace('100.0 =:', '50.0 =:'))
    elif fault=='duplicate':geo_file.write_text(geo_file.read_text()+'\n100 =: speed_limit\n')
    elif fault=='missing_speed':geo_file.write_text(cap.SPEED_LINE.sub('',geo_file.read_text()))
    elif fault=='missing_data':(folder/'claw.data').unlink()
    elif fault=='friction':(folder/'amr.data').write_text('modified non-cap solver settings')
    elif fault=='config':
        c=load(folder/'config.json');c['source']['travel_duration_s']=18;save(folder/'config.json',c)
    elif fault=='added_data':(folder/'extra.data').write_text('x')
    else:
        f=folder/'fgmax_grids.data';s=f.read_text().splitlines()
        if fault=='monitor_step':s[5]='0.1'
        elif fault=='monitor_points':s[11]='9999 9999'
        elif fault=='monitor_tail':s.append('0 0')
        elif fault=='monitor_header':s[1]='1 =: num_fgmax_grids'
        else:s=s[:10]
        # Change all cases equally: the explicit monitor validator must catch it.
        for name in cap.CASE_NAMES:(session/'cases'/name/'fgmax_grids.data').write_text('\n'.join(s)+'\n')
    with pytest.raises((ValueError,cap.IntegrityError)):
        cap.verify_decks(session,base,BASE_SETUP)


def test_config_speed_passes_into_setrun(monkeypatch,tmp_path,config):
    import sys
    class Data:
        def __init__(self,*a):
            for n in ['clawdata','amrdata','regiondata','refinement_data','geo_data','topo_data','dtopo_data','qinit_data','gaugedata']:
                setattr(self,n,SimpleNamespace())
            self.fgmax_data=SimpleNamespace(fgmax_grids=[])
    monkeypatch.setitem(sys.modules,'clawpack',SimpleNamespace())
    monkeypatch.setitem(sys.modules,'clawpack.clawutil.data',SimpleNamespace(ClawRunData=Data))
    monkeypatch.setitem(sys.modules,'clawpack.geoclaw.fgmax_tools',SimpleNamespace(FGmaxGrid=SimpleNamespace))
    for limit in [50,100,200]:
        c=copy.deepcopy(config);c['numerics']={'water_speed_limit_m_s':limit}
        r=geo.setrun(c,BASE_SETUP,'slide',tmp_path)
        assert r.geo_data.speed_limit==limit
        assert r.dtopo_data.dt_max_dtopo==0.1
    for limit in [0,-1,float('nan'),float('inf'),True,'100']:
        config['numerics']={'water_speed_limit_m_s':limit}
        with pytest.raises(ValueError,match='speed limit'):geo.setrun(config,BASE_SETUP,'slide',tmp_path)
    config.pop('numerics');assert geo.setrun(config,BASE_SETUP,'slide',tmp_path).geo_data.speed_limit==50


@pytest.mark.reference_data
def test_prepare_actual_frozen_inputs_once_with_mock_data_writer(tmp_path,monkeypatch):
    """Real terrain/source prep; mock .data writer only; NO water integration."""
    base,contract=cap.frozen_config()
    monkeypatch.setattr(cap,'write_data',fixture_writer)
    setup,checks,decks=cap.prepare_session(tmp_path/'prepared',base,contract)
    assert setup['terrain_file_sha256']==contract['terrain_file_sha256']
    assert setup['source_file_sha256']==contract['source_file_sha256']
    assert decks['status']=='passed'
    assert len(list((tmp_path/'prepared/cases').iterdir()))==3
    assert not list((tmp_path/'prepared').rglob('fort.q*'))


def test_inputs_hash_check(tmp_path):
    (tmp_path/'terrain.tt3').write_text('ground');(tmp_path/'slide.dtt3').write_text('source')
    contract={'terrain_file_sha256':sha(tmp_path/'terrain.tt3'),'source_file_sha256':sha(tmp_path/'slide.dtt3')}
    cap.check_physical_inputs(tmp_path,contract)
    assert len(cap.input_hashes(tmp_path))==2
    (tmp_path/'slide.dtt3').write_text('changed')
    with pytest.raises(cap.IntegrityError):cap.check_physical_inputs(tmp_path,contract)


@pytest.fixture
def execution(tmp_path,monkeypatch,decks):
    old_session,base,contract=decks
    root=tmp_path/'Run Root';root.mkdir()
    session=root/'comparison_runs/session1';session.parent.mkdir()
    shutil.copytree(old_session,session)
    inp=session/'inputs';inp.mkdir()
    save(inp/'setup.json',BASE_SETUP)
    (inp/'terrain.tt3').write_text('frozen bed');(inp/'slide.dtt3').write_text('frozen source')
    contract.update(terrain_file_sha256=sha(inp/'terrain.tt3'),source_file_sha256=sha(inp/'slide.dtt3'))
    exe=root/'solver';exe.write_text('fake executable identity')
    image={'solver_sha256':sha(exe),'clawpack_tag':'v5.14.0'}
    codes={'fixture':'unchanged'}
    monkeypatch.setattr(cap,'code_fingerprint',lambda r:codes.copy())
    monkeypatch.setattr(cap,'frozen_config',lambda r:(copy.deepcopy(base),copy.deepcopy(contract)))
    monkeypatch.setattr(cap,'checked_solver',lambda c:(exe,image.copy()))
    monkeypatch.delenv('LITUYA_RUN_IMAGE_ID',raising=False)
    rec={'status':'passed','code_sha256':codes.copy(),'inputs_sha256':cap.input_hashes(inp),
         'generated_decks':cap.verify_decks(session,base,BASE_SETUP),
         'solver_sha256':image['solver_sha256'],'image_manifest_sha256':hash_json(image),
         'docker_image_id':None}
    save(session/'preflight.json',rec)
    save(root/'comparison_results/latest_preflight.json',{'session':'comparison_runs/session1'})
    save(root/'comparison_results/latest_attempt.json',{'session':'comparison_runs/session1'})
    calls=[]
    def logged(cmd,cwd,path):
        calls.append(Path(cwd).name);Path(path).write_text('mock execution, not a water run')
        (Path(cwd)/'fort.amr').write_text('b4step2 at t = 20.0\nreset s = 51.0 h= 12.0 B= 1\n')
    def result(folder,*args,**kwargs):
        name=Path(folder).name
        height={'cap_050':10.,'cap_100':20.,'cap_200':30.}[name]  # synthetic numbers only
        primary={'maximum_wetted_cell_elevation_m':height,'peak_touches_monitor_boundary':False}
        value={'runup_primary':primary,'runup_diagnostics':{'monitors':{'legacy':primary}},'status':'passed_basic_checks'}
        save(Path(folder)/'validation.json',value)
        return value
    monkeypatch.setattr(cap,'logged',logged)
    monkeypatch.setattr(cap,'audit_time_steps',lambda *a:None)
    monkeypatch.setattr(cap,'validate',result)
    return SimpleNamespace(root=root,session=session,base=base,contract=contract,exe=exe,image=image,
                           codes=codes,calls=calls,logged=logged,result=result)


def test_exactly_three_no_control_no_search_and_differences(execution):
    e=execution
    session,state=cap.run_experiment(e.root)
    assert e.calls==list(cap.CASE_NAMES)
    assert state['status']=='completed_basic_checks'
    summary=load(session/'comparison_summary.json')
    assert summary['setting_differences']['R200_minus_R50_m']==20.
    assert summary['cases'][0]['boundary_touching'] is False
    assert not state['cap_chosen_by_runup'] and not state['historically_validated']
    assert not (session/'still').exists()
    with pytest.raises(cap.IntegrityError,match='already started'):cap.run_experiment(e.root)
    assert e.calls==list(cap.CASE_NAMES)


@pytest.mark.parametrize('fault',['code','input','deck','solver','image','docker','output','preflight'])
def test_tampering_stops_before_water(execution,monkeypatch,fault):
    e=execution
    if fault=='code':e.codes['fixture']='changed'
    elif fault=='input':(e.session/'inputs/terrain.tt3').write_text('different')
    elif fault=='deck':
        f=e.session/'cases/cap_200/geoclaw.data';f.write_text(f.read_text().replace('200.0 =:', '50.0 =:'))
    elif fault=='solver':e.image['solver_sha256']='wrong'
    elif fault=='image':e.image['new_build']='changed'
    elif fault=='docker':monkeypatch.setenv('LITUYA_RUN_IMAGE_ID','new-image')
    elif fault=='output':(e.session/'cases/cap_050/fort.q0000').write_text('old result')
    else:
        f=e.session/'preflight.json';r=load(f);r['status']='failed';save(f,r)
    with pytest.raises(cap.IntegrityError):cap.run_experiment(e.root)
    assert not e.calls


@pytest.mark.parametrize('kind',['solver','checks','missing_monitor'])
def test_failed_case_retained_others_run_no_failed_peak(execution,monkeypatch,kind):
    e=execution
    if kind=='solver':
        def logged(cmd,cwd,path):
            e.logged(cmd,cwd,path)
            if Path(cwd).name=='cap_100':raise RuntimeError('exit 9')
        monkeypatch.setattr(cap,'logged',logged)
    else:
        def validate(folder,*a,**kw):
            if Path(folder).name=='cap_100':
                raise ValueError('no final time' if kind=='checks' else 'Missing per-timestep monitor')
            return e.result(folder,*a,**kw)
        monkeypatch.setattr(cap,'validate',validate)
    _,state=cap.run_experiment(e.root)
    assert e.calls==list(cap.CASE_NAMES)
    assert state['status']=='completed_with_failures'
    summary=load(e.session/'comparison_summary.json')
    assert summary['cases'][1]['runup_expanded_m'] is None
    assert summary['setting_differences']['R100_minus_R50_m'] is None
    assert summary['setting_differences']['R200_minus_R50_m']==20


def test_zero_exit_early_stop_checked_by_trace(execution,monkeypatch):
    e=execution
    def audit(folder,*a):
        if Path(folder).name=='cap_200':raise ValueError('Step trace incomplete')
    monkeypatch.setattr(cap,'audit_time_steps',audit)
    _,state=cap.run_experiment(e.root)
    assert state['cases']['cap_200']['status']=='checks_failed'
    assert load(e.session/'comparison_summary.json')['cases'][2]['runup_expanded_m'] is None


@pytest.mark.parametrize('kind',['interrupt','disk','changed_inputs'])
def test_interrupt_and_infrastructure_abort_preserve_status(execution,monkeypatch,kind):
    e=execution
    def logged(cmd,cwd,path):
        e.logged(cmd,cwd,path)
        if Path(cwd).name=='cap_050':
            if kind=='interrupt':raise KeyboardInterrupt()
            elif kind=='disk':raise OSError('disk full')
            else:(e.session/'inputs/terrain.tt3').write_text('changed during run')
    monkeypatch.setattr(cap,'logged',logged)
    with pytest.raises((KeyboardInterrupt,OSError,cap.IntegrityError)):
        cap.run_experiment(e.root)
    assert e.calls==['cap_050']
    state=load(e.session/'experiment.json')
    assert state['status'] in {'interrupted','aborted_infrastructure'}
    assert state['cases']['cap_100']['status']=='not_started'
    assert all(v is None for v in load(e.session/'comparison_summary.json')['setting_differences'].values())


def test_reset_parser_rounded_logs_and_missing_file(tmp_path):
    assert cap.reset_summary(tmp_path)['status']=='not_available'
    (tmp_path/'fort.amr').write_text('b4step2 at t = 24.80\n reset s = 51.2 h= 0.128D+03 B= 0\nb4step2 at t = 30\nreset s = 52 h= 0.05 B= 0\n')
    r=cap.reset_summary(tmp_path)
    assert r['logged_b4step2_events']==2 and r['events_at_depth_ge_10_m']==1
    assert r['maximum_printed_depth_m']==128 and r['first_time_s']==24.8 and r['last_time_s']==30


def test_collect_excludes_frames_and_lists_omissions(execution):
    e=execution
    (e.session/'cases/cap_050/fort.q0000').write_text('large field excluded')
    (e.session/'cases/cap_050/fort.t0000').write_text('0 time')
    (e.session/'cases/cap_050/gauge00002.txt').write_text('test gauge')
    before=sha(e.session/'inputs/terrain.tt3')
    archive=cap.collect(e.root)
    with zipfile.ZipFile(archive) as z:
        manifest=json.loads(z.read('manifest.json'))
        assert 'experiment/cases/cap_050/fort.t0000' in z.namelist()
        assert 'experiment/cases/cap_050/fort.q0000' not in z.namelist()
        assert any(v['path'].endswith('fort.q0000') for v in manifest['omitted'])
    assert sha(e.session/'inputs/terrain.tt3')==before


def test_current_session_and_collector_reject_escape(tmp_path):
    with pytest.raises(cap.IntegrityError):cap.current_session(tmp_path)
    with pytest.raises(cap.IntegrityError):cap.collect(tmp_path)
    save(tmp_path/'comparison_results/latest_preflight.json',{'session':'../escape'})
    with pytest.raises(ValueError):cap.current_session(tmp_path)


def test_preflight_no_lituya_launch_and_failed_smoke(tmp_path,monkeypatch):
    base,contract=cap.frozen_config()
    root=tmp_path
    monkeypatch.setattr(cap,'frozen_config',lambda r:(base,contract))
    exe=root/'fake';exe.write_text('exe')
    monkeypatch.setattr(cap,'checked_solver',lambda c:(exe,{'solver_sha256':sha(exe)}))
    monkeypatch.setattr(cap,'code_fingerprint',lambda r:{'fixture':'x'})
    calls=[]
    def logged(cmd,cwd,path):
        assert 'tools.smoke' in cmd and str(exe)!=str(cmd[0])
        calls.append(cmd)
        save(Path(cmd[cmd.index('--report')+1]),{'status':'passed','cases':['still_fixture','slide_fixture']})
    monkeypatch.setattr(cap,'logged',logged)
    def prepared(session,*a):
        (session/'inputs').mkdir();(session/'inputs/x').write_text('mock input')
        return BASE_SETUP,{}, {'status':'passed'}
    monkeypatch.setattr(cap,'prepare_session',prepared)
    session=cap.preflight(root)
    assert len(calls)==1
    assert load(session/'preflight.json')['new_lituya_integrations']==0
    assert load(session/'preflight.json')['status']=='passed'
    assert (root/'comparison_results/latest_preflight.json').is_file()
    def broken(*a):raise RuntimeError('synthetic smoke failed')
    monkeypatch.setattr(cap,'logged',broken)
    with pytest.raises(RuntimeError):cap.preflight(root)
    latest=load(root/'comparison_results/latest_attempt.json')
    assert load(root/latest['session']/'preflight.json')['status']=='failed'
    # Failed preflight must not replace the last passed preflight pointer.
    assert load(root/'comparison_results/latest_preflight.json')['session']==session.relative_to(root).as_posix()
    with pytest.raises(cap.IntegrityError,match='fallback'):cap.current_session(root)


def test_checked_solver_error_mentions_new_launcher(monkeypatch):
    def broken(c):raise RuntimeError('Use bash run.sh --build.')
    monkeypatch.setattr(cap,'solver',broken)
    with pytest.raises(cap.IntegrityError,match='run_comparison.sh preflight'):
        cap.checked_solver({})


def test_cli_dispatch_errors_and_no_legacy_action(monkeypatch,tmp_path,capsys):
    monkeypatch.setattr(cap,'ROOT',tmp_path)
    monkeypatch.setattr(cap,'collect',lambda:tmp_path/'archive.zip')
    monkeypatch.setattr(cap,'preflight',lambda:tmp_path)
    monkeypatch.setattr(cap,'run_experiment',lambda:(tmp_path,{'status':'completed_with_failures'}))
    assert cap.main([])==0 and cap.main(['collect'])==0 and cap.main(['run'])==3
    with pytest.raises(SystemExit):cap.main(['all'])
    def fail():raise ValueError('invalid input')
    monkeypatch.setattr(cap,'preflight',fail)
    assert cap.main(['preflight'])==2 and 'invalid input' in capsys.readouterr().err


def test_existing_production_claim_refuses_a_second_launch(execution):
    e=execution
    save(e.session/'production_claim.json',{'claimed_utc':'earlier'})
    with pytest.raises(cap.IntegrityError,match='already started'):
        cap.run_experiment(e.root)
    assert not e.calls


def test_common_control_change_is_caught_against_archived_deck(decks):
    session,base,_=decks
    for name in cap.CASE_NAMES:
        f=session/'cases'/name/'claw.data'
        f.write_text(f.read_text()+'\n999 =: unexpected_control\n')
    with pytest.raises(cap.IntegrityError,match='archived baseline'):
        cap.verify_decks(session,base,BASE_SETUP)


def test_final_case_executable_mutation_is_not_accepted(execution,monkeypatch):
    e=execution
    def run(cmd,cwd,path):
        e.logged(cmd,cwd,path)
        if Path(cwd).name=='cap_200':e.exe.write_text('mutated after invocation')
    monkeypatch.setattr(cap,'logged',run)
    with pytest.raises(cap.IntegrityError,match='final case'):
        cap.run_experiment(e.root)
    assert load(e.session/'experiment.json')['status']=='aborted_infrastructure'
    assert all(v is None for v in load(e.session/'comparison_summary.json')['setting_differences'].values())
