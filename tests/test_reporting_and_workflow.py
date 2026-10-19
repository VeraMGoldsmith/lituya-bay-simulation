"""Plot/HTML fixtures below are synthetic software tests, not tsunami results."""
import copy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import numpy as np
import pytest

from reporting import dashboard, plots
from simulation.common import ROOT, load, save
from simulation.compare_runs import compare
import workflow


@pytest.mark.reference_data
def test_real_reconstructed_input_previews(prepared_inputs,tmp_path):
    path,_,_,_=prepared_inputs
    plots.input_previews(path,tmp_path)
    for name in ['basin_setup.png','inlet_setup.png','source_section.png']:
        assert (tmp_path/name).read_bytes().startswith(b'\x89PNG')


@pytest.mark.reference_data
def test_plotter_creates_all_products_from_explicit_synthetic_output(prepared_inputs,tmp_path,monkeypatch):
    path,cfg,setup,_=prepared_inputs
    session=tmp_path/'synthetic_plot_test';session.mkdir();shutil.copytree(path,session/'inputs')
    save(session/'status.json',{'status':'completed_basic_checks'})
    for case in ['still','slide']:save(session/case/'validation.json',{'status':'passed_basic_checks'})
    x=np.linspace(-1010,5800,21);y=np.linspace(-8775,4800,31)
    xx,yy=np.meshgrid((x[:-1]+x[1:])/2,(y[:-1]+y[1:])/2)
    b=(xx-3400)/20;h=np.maximum(0,-b)
    q=np.stack([h,np.zeros_like(h),np.zeros_like(h),h+b],axis=-1)
    def frame(folder,index):
        v=q.copy();v[:,:,3]+=index*.05*(h>0);v[:,:,0]+=index*.05*(h>0)
        return (index*420.,[SimpleNamespace(q=v,nx=20,ny=30,xlower=x[0],ylower=y[0],dx=x[1]-x[0],dy=y[1]-y[0])])
    monkeypatch.setattr(plots,'frame_numbers',lambda f:[0,1]);monkeypatch.setattr(plots,'read_frame',frame)
    monkeypatch.setattr(plots,'read_gauge',lambda f,i:np.array([[1,0,10,0,0,0],[1,420,10.05,0,0,.05]]))
    np.savetxt(session/'slide/opposite_slope_max_depth.csv',np.array([[1422,1512,1,524,.2,80,60],[1550,2200,1,2,.3,60,40]]),delimiter=',',header='x,y,level,B,h,t,arrival',comments='')
    result=plots.results(session)
    assert result==session/'plots'
    for name in ['inlet_wave.gif','basin_wave.gif','inlet_gauges.png','bay_gauges.png','gauges.csv','opposite_slope_max_depth.png']:
        assert (result/name).stat().st_size>100
    assert list(result.glob('inlet_*s.png'))
    save(session/'still/validation.json',{'status':'failed'})
    with pytest.raises(ValueError,match='case lacks'):plots.results(session)


@pytest.fixture
def report_case(tmp_path):
    session=tmp_path/'runs/unit_case';session.mkdir(parents=True)
    case=session/'baseline'
    save(case/'status.json',{'status':'completed_basic_checks'})
    for name in ['still','slide']:
        save(case/name/'validation.json',{'status':'passed_basic_checks','opposite_SW_slope_max_wetted_cell_elevation_m':12.,'runup_depth_threshold_m':.1})
    save(session/'workflow.json',{'status':'completed','selected_directory':'baseline','records':[
        {'candidate':'baseline','status':'completed','duration_s':30.,'travel_negative_y_m':1400.,'score':.9,'runup_m':12.,'placement':{'prescribed_final_centroid_xy_m':[10.,20.]}},
        {'candidate':'bad <candidate>','status':'failed','error':'failure <detail>'},
    ]})
    (case/'plots').mkdir();(case/'input_preview').mkdir()
    for name in ['inlet_wave.gif','snapshot & 20.png','gauge.csv']:(case/'plots'/name).write_bytes(b'unit fixture')
    return tmp_path,session,case


def test_dashboard_includes_every_saved_figure_and_escapes_names(report_case):
    root,session,case=report_case
    outside=root/'outside.png';outside.write_bytes(b'private unit fixture')
    (case/'plots/escape.png').symlink_to(outside)
    page=dashboard.render(session,root=root).read_text()
    assert 'snapshot%20%26%2020.png' in page
    assert 'snapshot &amp; 20.png' in page
    assert 'escape.png' not in page
    assert 'bad &lt;candidate&gt;' in page and 'failure &lt;detail&gt;' in page
    assert 'historical accuracy' in page and '12.00 m' in page
    assert page.index('inlet_wave.gif')<page.index('snapshot%20')


@pytest.mark.parametrize('state',['failed','prepared_not_simulated','preparing','partial'])
def test_dashboard_keeps_states_separate(report_case,state):
    root,session,case=report_case
    record=load(session/'workflow.json');record['status']=state;record['error']='unit <failure>';save(session/'workflow.json',record)
    page=dashboard.render(session,root=root).read_text()
    expected={'failed':'Stopped','prepared_not_simulated':'no water simulation','preparing':'Work in progress','partial':'Partial search'}[state]
    assert expected in page
    if state in ['failed','prepared_not_simulated','preparing']:assert 'inlet_wave.gif' not in page


def test_dashboard_refuses_invalid_selection_and_failed_cases(report_case):
    root,session,case=report_case
    record=load(session/'workflow.json');record['selected_directory']='../outside';save(session/'workflow.json',record)
    with pytest.raises(ValueError):dashboard.render(session,root=root)
    record['selected_directory']='baseline';save(session/'workflow.json',record)
    save(case/'status.json',{'status':'failed'})
    with pytest.raises(ValueError,match='not complete'):dashboard.render(session,root=root)
    save(case/'status.json',{'status':'completed_basic_checks'});save(case/'still/validation.json',{'status':'failed'})
    with pytest.raises(ValueError,match='lacks passed'):dashboard.render(session,root=root)
    with pytest.raises(ValueError,match='repository'):dashboard.render(root,root=root)


def test_refresh_never_guesses_an_older_success(report_case):
    root,session,case=report_case
    assert 'Not run yet' in dashboard.refresh(root).read_text()
    save(root/'results/latest_attempt.json',{'run_directory':'runs/unit_case'})
    assert 'Calculation complete' in dashboard.refresh(root).read_text()
    record=load(session/'workflow.json');record['status']='failed';save(session/'workflow.json',record)
    assert 'Stopped' in dashboard.refresh(root).read_text()


@pytest.fixture
def mock_workflow(tmp_path,config,monkeypatch):
    root=tmp_path/'repository';root.mkdir()
    for name in workflow.CODE_DIRS:
        (root/name).mkdir();(root/name/'unit.txt').write_text('unit code snapshot')
    for name in ['workflow.py','run.sh','pyproject.toml']:(root/name).write_text('unit placeholder')
    save(root/'config.json',config)
    shutil.copy2(ROOT/'calibration/search.json',root/'calibration/search.json')
    shutil.copy2(ROOT/'calibration/targets.json',root/'calibration/targets.json')
    monkeypatch.setattr(workflow,'solver',lambda c:(Path('/unit/solver'),{}))
    def prepare(cfg,destination):
        destination.mkdir(parents=True);save(destination/'config.json',cfg)
        save(destination/'source_placement.json',{'unit_fixture':True})
        return {'nx':3,'ny':2},{}
    monkeypatch.setattr(workflow,'prepare',prepare)
    def previews(inputs,dest):dest.mkdir(parents=True,exist_ok=True);(dest/'input.png').write_bytes(b'unit image')
    monkeypatch.setattr(workflow.plots,'input_previews',previews)
    def cases(cfg,setup,session):
        save(session/'status.json',{'status':'completed_basic_checks'})
        for name in ['still','slide']:
            save(session/name/'validation.json',{'status':'passed_basic_checks','opposite_SW_slope_max_wetted_cell_elevation_m':12.,'runup_depth_threshold_m':.1})
    monkeypatch.setattr(workflow,'run_cases',cases)
    def results(session):
        (session/'plots').mkdir();(session/'plots/wave.gif').write_bytes(b'unit fixture')
    monkeypatch.setattr(workflow.plots,'results',results)
    return root,cases


@pytest.mark.parametrize('action',['prepare','baseline','all'])
def test_unified_workflow_writes_final_page_and_code_snapshot(mock_workflow,config,monkeypatch,action):
    root,_=mock_workflow
    monkeypatch.setattr(workflow,'run_search',lambda c,baseline,*a:(baseline,[{'candidate':'baseline','status':'completed','score':.5}]))
    assert workflow.execute(config,action,root)==0
    session=root/load(root/'results/latest_attempt.json')['run_directory']
    record=load(session/'workflow.json')
    assert record['status']==('prepared_not_simulated' if action=='prepare' else 'completed')
    assert (session/'code/workflow.py').exists()
    assert (root/'results/index.html').exists()


def test_partial_search_reports_current_valid_case_but_returns_failure(mock_workflow,config,monkeypatch):
    root,cases=mock_workflow
    def search(cfg,baseline,setup,out,*args):
        candidate=out/'candidate';candidate.mkdir(parents=True)
        cases(cfg,setup,candidate)
        return candidate,[{'candidate':'candidate','status':'completed','score':.2},{'candidate':'failed','status':'failed','error':'unit'}]
    monkeypatch.setattr(workflow,'run_search',search)
    assert workflow.execute(config,'all',root)==1
    session=root/load(root/'results/latest_attempt.json')['run_directory']
    assert load(session/'workflow.json')['status']=='partial'
    assert not (root/'results/latest_success.json').exists()
    assert 'Partial search' in (root/'results/index.html').read_text()


@pytest.mark.parametrize('error,code',[(ValueError('unit failure'),1),(KeyboardInterrupt(),130)])
def test_workflow_failure_has_no_stale_success(mock_workflow,config,monkeypatch,error,code):
    root,_=mock_workflow
    def fail(*a):raise error
    monkeypatch.setattr(workflow,'run_cases',fail)
    assert workflow.execute(config,'baseline',root)==code
    session=root/load(root/'results/latest_attempt.json')['run_directory']
    assert load(session/'workflow.json')['status']=='failed'
    assert (session/'last_error.txt').exists()
    assert 'Stopped' in (root/'results/index.html').read_text()


def test_main_arguments_tests_and_configuration_overrides(tmp_path,config,monkeypatch):
    monkeypatch.setattr(workflow,'ROOT',tmp_path)
    save(tmp_path/'config.json',config)
    monkeypatch.setattr(workflow.subprocess,'call',lambda *a,**k:0)
    seen=[]
    monkeypatch.setattr(workflow,'execute',lambda c,action:seen.append((c,action)) or 0)
    assert workflow.main(['test'])==0
    assert workflow.main(['baseline','--grid','60','--sw-relief-factor','1.1','--travel-m','1600','--duration-s','12'])==0
    cfg,action=seen[-1]
    assert cfg['run']['target_cell_size_m']==60 and cfg['source']['travel_negative_y_m']==1600
    assert cfg['source']['travel_duration_s']==12 and cfg['geometry']['sw_relief_factor']==1.1
    with pytest.raises(ValueError,match='baseline geometry'):workflow.main(['all','--sw-relief-factor','1.1'])
    monkeypatch.setattr(workflow,'solver',lambda c:('/unit/solver',{}))
    assert workflow.main(['check'])==0
    monkeypatch.setattr(workflow.dashboard,'refresh',lambda:'unit report')
    assert workflow.main(['report'])==0
    monkeypatch.setattr(workflow.subprocess,'call',lambda *a,**k:2)
    assert workflow.main(['all'])==2
    with pytest.raises(SystemExit):workflow.arguments(['bad'])


def test_completed_run_comparison_is_controlled(tmp_path,config):
    folders=[]
    for name,grid in [('a',30),('b',30)]:
        folder=tmp_path/name
        save(folder/'status.json',{'status':'completed_basic_checks'})
        save(folder/'inputs/config.json',config)
        save(folder/'inputs/setup.json',{'source_file_sha256':'same-source','nx':grid,'ny':grid})
        save(folder/'slide/validation.json',{'status':'passed_basic_checks','opposite_SW_slope_max_wetted_cell_elevation_m':10.,'maximum_wave_outside_source_m':2.})
        folders.append(folder)
    out=tmp_path/'comparison.csv'
    assert compare(folders,out)[0]['comparison_type']=='fixed_grid_geometry_candidates'
    setup=load(folders[1]/'inputs/setup.json');setup['nx']=60;save(folders[1]/'inputs/setup.json',setup)
    assert compare(folders,out)[0]['comparison_type']=='resolution_and_or_geometry'
    setup['source_file_sha256']='changed';save(folders[1]/'inputs/setup.json',setup)
    with pytest.raises(ValueError,match='Source or water'):compare(folders,out)
    save(folders[0]/'status.json',{'status':'failed'})
    with pytest.raises(ValueError,match='Not a completed'):compare(folders,out)
    save(folders[0]/'status.json',{'status':'completed_basic_checks'})
    save(folders[0]/'slide/validation.json',{'status':'failed'})
    with pytest.raises(ValueError,match='Missing passed'):compare([folders[0]],out)
    with pytest.raises(ValueError,match='at least one'):compare([],out)
    with pytest.raises(ValueError,match='not found'):compare([tmp_path/'missing'],out)


@pytest.mark.parametrize('resets',[0,10])
def test_report_shows_timestep_evidence_and_speed_warning(report_case,resets):
    root,session,case=report_case
    save(case/'slide/time_step_check.json',{'status':'passed','logged_speed_resets':resets})
    page=dashboard.render(session,root=root).read_text()
    assert 'Actual time-step audit' in page
    assert ('Water-speed limiting occurred' in page)==bool(resets)
