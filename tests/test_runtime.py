import copy
import io
import os
from pathlib import Path
import signal
import subprocess
import sys
from types import SimpleNamespace

import pytest

from simulation import runtime
from simulation.common import load, save, sha


@pytest.fixture
def solver_environment(tmp_path,monkeypatch,config):
    root=tmp_path/'root';root.mkdir()
    exe=root/'solver';exe.write_bytes(b'unit-test placeholder, not an executable')
    claw=root/'claw';(claw/'geoclaw/src/2d/shallow').mkdir(parents=True)
    (claw/'geoclaw/src/2d/shallow/Makefile.geoclaw').write_text('unit')
    manifest=root/'manifest.json'
    data={'clawpack_tag':config['clawpack_tag'],'makefile_sha256':'recipe',
          'solver_sha256':sha(exe),'synthetic_solver_smoke_test':{'status':'passed'}}
    save(manifest,data);save(root/'environment/compatible_recipes.json',{'allowed_makefile_sha256':['recipe']})
    monkeypatch.setattr(runtime,'ROOT',root)
    monkeypatch.setenv('LITUYA_SOLVER',str(exe));monkeypatch.setenv('LITUYA_BUILD_MANIFEST',str(manifest));monkeypatch.setenv('CLAW',str(claw))
    monkeypatch.setattr(runtime.subprocess,'check_output',lambda args,**k: config['clawpack_tag']+'\n' if 'describe' in args else ' 123abc submodule\n')
    return root,exe,manifest,data,claw


def test_solver_fingerprint(config,solver_environment):
    _,exe,_,record,_=solver_environment
    got,data=runtime.solver(config)
    assert got==exe and data==record


@pytest.mark.parametrize('failure',['missing_exe','missing_manifest','tag','recipe','hash','smoke','tree','source_tag','submodule'])
def test_solver_refuses_unverified_environment(config,solver_environment,monkeypatch,failure):
    root,exe,manifest,record,claw=solver_environment
    if failure=='missing_exe':exe.unlink()
    elif failure=='missing_manifest':manifest.unlink()
    elif failure in ['tag','recipe','hash','smoke']:
        key={'tag':'clawpack_tag','recipe':'makefile_sha256','hash':'solver_sha256','smoke':'synthetic_solver_smoke_test'}[failure]
        record[key]={} if failure=='smoke' else 'wrong';save(manifest,record)
    elif failure=='tree':(claw/'geoclaw/src/2d/shallow/Makefile.geoclaw').unlink()
    elif failure=='source_tag':monkeypatch.setattr(runtime.subprocess,'check_output',lambda *a,**k:'v0\n')
    elif failure=='submodule':monkeypatch.setattr(runtime.subprocess,'check_output',lambda args,**k:config['clawpack_tag'] if 'describe' in args else '+changed hash')
    with pytest.raises(RuntimeError):runtime.solver(config)


def test_logged_captures_real_process_output_and_failure(tmp_path):
    path=tmp_path/'log'
    runtime.logged([sys.executable,'-c',"print('unit subprocess output')"],tmp_path,path)
    assert 'unit subprocess output' in path.read_text()
    with pytest.raises(RuntimeError,match='exit 7'):
        runtime.logged([sys.executable,'-c','raise SystemExit(7)'],tmp_path,path)


@pytest.mark.parametrize('termination',['normal','timeout','already_gone'])
def test_logged_terminates_process_group_on_interrupt(tmp_path,monkeypatch,termination):
    class BrokenOutput:
        def __iter__(self):raise KeyboardInterrupt()
    class Process:
        pid=123456
        stdout=BrokenOutput()
        def wait(self,timeout=None):
            if termination=='timeout' and timeout is not None:raise subprocess.TimeoutExpired('unit',timeout)
            return 0
    signals=[]
    def kill(pid,sig):
        signals.append(sig)
        if termination=='already_gone':raise ProcessLookupError()
    monkeypatch.setattr(runtime.subprocess,'Popen',lambda *a,**k:Process())
    monkeypatch.setattr(runtime.os,'killpg',kill)
    with pytest.raises(KeyboardInterrupt):runtime.logged(['unit'],tmp_path,tmp_path/'log')
    assert signals[0]==signal.SIGTERM
    if termination=='timeout':assert signals[-1]==signal.SIGKILL


@pytest.fixture
def mocked_cases(tmp_path,config,monkeypatch):
    setup={'nx':3,'ny':2,'domain_xyxy_m':[0,0,3,2],'gauges':[], 'terrain_file_sha256':'same-bed'}
    image={'solver_sha256':'unit-executable'}
    calls=[]
    monkeypatch.setattr(runtime,'solver',lambda c:(Path('/unit/solver'),image))
    def write_data(folder,*args):folder.mkdir(parents=True,exist_ok=True)
    monkeypatch.setattr(runtime,'write_data',write_data)
    def logged(args,folder,path):
        calls.append(folder.name);path.write_text('unit mocked solver log')
    monkeypatch.setattr(runtime,'logged',logged)
    # Unit orchestration fixture; real step-trace validation has dedicated tests.
    monkeypatch.setattr(runtime,'audit_time_steps',lambda *args: {'status':'passed'})
    def validation(folder,case,cfg,settings,inputs,baseline):
        if case=='slide':assert baseline['status']=='passed_basic_checks'
        return {'status':'passed_basic_checks','max_abs_eta_deep_m':0.,'case':case}
    monkeypatch.setattr(runtime,'validate',validation)
    return setup,image,calls


def test_control_reuse_removes_only_duplicate_stationary_solve(tmp_path,config,mocked_cases):
    setup,image,calls=mocked_cases
    baseline=tmp_path/'baseline';baseline.mkdir()
    state=runtime.run_cases(config,setup,baseline)
    assert state['status']=='completed_basic_checks' and calls==['still','slide']
    candidate=tmp_path/'candidate';candidate.mkdir()
    changed=copy.deepcopy(config);changed['source'].update(travel_duration_s=12.,travel_negative_y_m=1600.)
    assert runtime.control_key(config,setup,image)==runtime.control_key(changed,setup,image)
    runtime.run_cases(changed,setup,candidate,control=baseline)
    assert calls==['still','slide','slide']
    assert load(candidate/'still/reused_control.json')['solver_integration_performed_here'] is False
    assert not (candidate/'still/solver.log').exists()


@pytest.mark.parametrize('what',['water','grid','terrain','solver','run','step','checks','geometry'])
def test_control_fingerprint_covers_stationary_inputs(config,mocked_cases,what):
    setup,image,_=mocked_cases
    before=runtime.control_key(config,setup,image)
    c=copy.deepcopy(config);s=copy.deepcopy(setup);i=copy.deepcopy(image)
    if what=='water':c['water']['manning_n']=.2
    elif what=='grid':s['nx']=4
    elif what=='terrain':s['terrain_file_sha256']='new'
    elif what=='solver':i['solver_sha256']='new'
    elif what=='run':c['run']['duration_s']=600.
    elif what=='step':c['source']['maximum_solver_step_during_motion_s']=.05
    elif what=='checks':c['checks']['runup_depth_threshold_m']=.2
    elif what=='geometry':c['geometry']['sw_relief_factor']=1.1
    assert runtime.control_key(c,s,i)!=before


@pytest.mark.parametrize('problem',['changed','failed','empty','mismatch'])
def test_control_reuse_requires_unchanged_passed_outputs(tmp_path,config,mocked_cases,problem):
    setup,image,_=mocked_cases
    baseline=tmp_path/'base';baseline.mkdir();runtime.run_cases(config,setup,baseline)
    if problem=='changed':(baseline/'still/solver.log').write_text('changed')
    elif problem=='failed':save(baseline/'still/validation.json',{'status':'failed'})
    elif problem=='empty':
        s=load(baseline/'control_signature.json');s['files']={};save(baseline/'control_signature.json',s)
    elif problem=='mismatch':config['run']['duration_s']=600.
    with pytest.raises(ValueError):runtime.checked_control(baseline,config,setup,image)


def test_run_cases_records_failure_before_propagating(tmp_path,config,mocked_cases,monkeypatch):
    setup,_,_=mocked_cases
    def fail(*args):raise ValueError('unit numerical failure')
    monkeypatch.setattr(runtime,'validate',fail)
    with pytest.raises(ValueError):runtime.run_cases(config,setup,tmp_path)
    assert load(tmp_path/'status.json')['status']=='failed'
