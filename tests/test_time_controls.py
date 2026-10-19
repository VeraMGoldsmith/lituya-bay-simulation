"""Regression coverage for step-start bed output and enforced source time steps."""
import copy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from simulation.bed_check import compare_transition, transition_basis
from simulation.time_steps import audit, parsed_number
from simulation.common import load
from simulation.validate import validate
from simulation import runtime
from conftest import write_frame


def test_bounded_phase_accepts_one_shared_step_start():
    basis = np.array([[2., -3.], [.2, 0.]])
    result = compare_transition(.3 * basis, basis, .25, 12., 12., .1)
    assert result['comparison_residual_m'] < 1.e-14
    assert result['bed_reference_time_s'] == pytest.approx(11.925)
    assert result['maximum_raw_final_bed_error_m'] == pytest.approx(.9)


def test_independent_cell_errors_are_not_excused():
    basis = np.ones((2, 2))
    delta = np.array([[.2, .2], [.2, .8]])
    assert compare_transition(delta, basis, .25, 12., 12., .1)['comparison_residual_m'] > .02


@pytest.mark.parametrize('alpha',[-.4,.8])
def test_out_of_window_lag_is_not_accepted(alpha):
    b = np.ones((2, 2))
    assert compare_transition(alpha*b,b,.25,12,12,.1)['comparison_residual_m'] > .02


def test_zero_source_basis_and_shifted_output():
    z = np.zeros((2, 2))
    assert compare_transition(z,z,.25,12,12,.1)['comparison_residual_m'] == 0
    b = np.ones((2,2))
    r = compare_transition(.1*b,b,.25,12,12.05,.1)
    assert r['bounded_phase_fraction'] == pytest.approx(.1)


@pytest.mark.parametrize('kind',['shape','nan','time_nan','nonpositive','too_large_step','before','after'])
def test_bad_transition_inputs_fail(kind):
    d = np.ones((2,2)); b=d.copy(); interval=.25; stop=12.; time=12.; step=.1
    if kind=='shape':b=np.ones((1,1))
    if kind=='nan':d[0,0]=np.nan
    if kind=='time_nan':time=np.nan
    if kind=='nonpositive':interval=0
    if kind=='too_large_step':step=.5
    if kind=='before':time=11.9
    if kind=='after':time=12.2
    with pytest.raises(ValueError):compare_transition(d,b,interval,stop,time,step)


def source_fixture(tmp_path, bad=None):
    times=np.array([0.,.25]);dz=np.array([np.zeros((3,4)),np.ones((3,4))])
    origin=[0,0]
    terrain=dict(x=np.arange(4.),y=np.arange(3.),xe=np.arange(4.),ye=np.arange(3.))
    expected=np.ones((2,3))
    if bad=='times':times=np.array([0.,0.])
    if bad=='samples':dz[1,0,0]=np.nan
    if bad=='origin':origin=[-1,0]
    if bad=='disagreement':expected*=2
    np.savez(tmp_path/'source_arrays.npz',times=times,dz=dz,global_origin=origin)
    return terrain,expected


def test_source_basis_uses_integrals(tmp_path):
    a,e=source_fixture(tmp_path)
    b,interval,end=transition_basis(tmp_path,a,e)
    np.testing.assert_allclose(b,-np.ones((2,3)))
    assert interval==end==.25


@pytest.mark.parametrize('bad',['times','samples','origin','disagreement'])
def test_bad_source_history_fails(tmp_path,bad):
    a,e=source_fixture(tmp_path,bad)
    with pytest.raises(ValueError):transition_basis(tmp_path,a,e)


def test_transition_check_integrated_and_persistent_error_still_fails(model_factory):
    folder,inputs,cfg,setup=model_factory()
    cfg['source']['travel_duration_s']=2.;setup['source_stop_s']=2.
    with np.load(inputs/'terrain_arrays.npz') as a:terrain={k:a[k] for k in a.files}
    terrain.update(x=np.arange(4.),y=np.arange(3.))
    terrain['expected_final_dz_cells']=np.ones((2,3))*.2
    np.savez(inputs/'terrain_arrays.npz',**terrain)
    np.savez(inputs/'source_arrays.npz',times=[1.75,2.],
             dz=np.array([np.zeros((3,4)),np.ones((3,4))*.2]),global_origin=[0,0])
    from simulation.read_output import read_frame
    for idx,delta in [(1,.14),(2,.2)]:
        t,p=read_frame(folder,idx);q=p[0].q.copy();q[:,:,3]+=delta;write_frame(folder,idx,t,q)
    report=validate(folder,'slide',cfg,setup,inputs)
    assert len(report['bed_timing_check']['transition_frames'])==1
    assert report['bed_timing_check']['fully_post_source_frames_checked']==1
    assert report['final_bed_change_max_error_m'] < 1.e-12
    t,p=read_frame(folder,2);q=p[0].q.copy();q[0,0,3]+=.1;write_frame(folder,2,t,q)
    with pytest.raises(ValueError,match='Bed-change mismatch'):validate(folder,'slide',cfg,setup,inputs)


def test_no_post_source_frame_cannot_get_pass(model_factory):
    folder,inputs,cfg,setup=model_factory()
    setup['source_stop_s']=5.
    with pytest.raises(ValueError,match='No fully post-source frame'):validate(folder,'slide',cfg,setup,inputs)


def step_line(dt,end,level=1,cfl=.75):
    return f' AMRCLAW: level {level:2d}  CFL = {cfl:8.3E}  dt = {dt:10.4E}  final t = {end:12.6E}\n'


def test_step_audit_trace(tmp_path,config):
    config=copy.deepcopy(config);config['run']['duration_s']=.4;config['source']['travel_duration_s']=.2
    (tmp_path/'fort.amr').write_text('header\nreset s = 55.0\n'+''.join(step_line(dt,end) for dt,end in [(.1,.1),(.1,.2),(.2,.4)]))
    r=audit(tmp_path,config,'slide')
    assert r['status']=='passed' and r['steps']==3
    assert r['logged_speed_resets']==1
    assert r['speed_limit_sensitivity_validated'] is False
    assert r['maxima']['steps_starting_before_source_stop_s']==.1
    assert load(tmp_path/'time_step_check.json')==r


@pytest.mark.parametrize('case',['still','slide'])
def test_large_post_stop_step_is_bounded(tmp_path,config,case):
    config['run']['duration_s']=2.1;config['source']['travel_duration_s']=.1
    (tmp_path/'fort.amr').write_text(step_line(.1,.1)+step_line(2.,2.1))
    assert audit(tmp_path,config,case)['status']=='passed'


@pytest.mark.parametrize('bad',['missing','empty','oversize','global_oversize','format','level','nonpositive','gap','cfl','unfinished'])
def test_time_audit_refuses_unverified_steps(tmp_path,config,bad):
    config['run']['duration_s']=.2;config['source']['travel_duration_s']=.2
    text=step_line(.1,.1)+step_line(.1,.2)
    if bad=='empty':text='no trace'
    if bad=='oversize':text=step_line(.2,.2)
    if bad=='global_oversize':
        config['source']['travel_duration_s']=.1;config['run']['duration_s']=3.1
        text=step_line(.1,.1)+step_line(3.,3.1)
    if bad=='format':text=' AMRCLAW: level 1 CFL = ***\n'
    if bad=='level':text=step_line(.1,.1,level=2)
    if bad=='nonpositive':text=step_line(0.,0.)
    if bad=='gap':text=step_line(.1,.1)+step_line(.1,.3)
    if bad=='cfl':text=step_line(.1,.1,cfl=1.1)+step_line(.1,.2)
    if bad=='unfinished':text=step_line(.1,.1)
    if bad!='missing':(tmp_path/'fort.amr').write_text(text)
    with pytest.raises(ValueError):audit(tmp_path,config,'slide')
    assert load(tmp_path/'time_step_check.json')['status']=='failed'


def test_output_step_adjustment_is_not_a_broad_relaxation(tmp_path,config):
    config['run']['duration_s']=.10009
    (tmp_path/'fort.amr').write_text(step_line(.10009,.10009))
    assert audit(tmp_path,config,'slide')['status']=='passed'
    config['run']['duration_s']=.1002
    (tmp_path/'fort.amr').write_text(step_line(.1002,.1002))
    with pytest.raises(ValueError,match='Actual time step'):audit(tmp_path,config,'slide')


def test_fortran_print_precision():
    assert parsed_number('0.1000D+00') == pytest.approx((.1,.00005))
    assert parsed_number('2') == (2.,.5)


def test_runtime_stops_before_scoring_if_time_audit_fails(tmp_path,config,mocked_cases,monkeypatch):
    # Fixture supplied locally below to keep cross-module fixture resolution explicit.
    setup,_,_=mocked_cases
    def bad(*args):raise ValueError('actual timestep exceeds limit')
    monkeypatch.setattr(runtime,'audit_time_steps',bad)
    with pytest.raises(ValueError,match='actual timestep'):runtime.run_cases(config,setup,tmp_path)
    assert load(tmp_path/'status.json')['status']=='failed'

# Reuse the existing explicit mocked orchestration fixture, not a real solver.
from test_runtime import mocked_cases


def test_source_stop_metadata_must_match_samples(model_factory,monkeypatch):
    import simulation.validate as module
    folder,inputs,cfg,setup=model_factory()
    setup['source_stop_s']=2.
    monkeypatch.setattr(module,'transition_basis',lambda *a:(np.zeros((2,3)),.25,3.))
    with pytest.raises(ValueError,match='stopping time disagrees'):
        validate(folder,'slide',cfg,setup,inputs)
