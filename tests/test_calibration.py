import copy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from calibration import search
from simulation.common import ROOT, load, save


@pytest.fixture
def targets():return load(ROOT/'calibration/targets.json')


@pytest.fixture
def spec():return load(ROOT/'calibration/search.json')


def test_nine_candidates_are_explicit_and_unique(spec):
    values=search.candidates(spec)
    assert len(values)==9
    assert values[0]==('D12_L1200',12.,1200.)
    assert values[-1]==('D18_L1600',18.,1600.)


@pytest.mark.parametrize('durations,distances',[([], [1200]),([12], []),([0],[1200]),([float('nan')],[1200]),([12,12],[1200])])
def test_bad_candidate_spec(durations,distances):
    with pytest.raises(ValueError):search.candidates({'durations_s':durations,'travel_distances_m':distances})


def test_preparation_does_not_mutate_base_and_records_rejection(tmp_path,config,spec,monkeypatch):
    original=copy.deepcopy(config);seen=[]
    def prepare(cfg,out):
        seen.append(copy.deepcopy(cfg))
        if cfg['source']['travel_negative_y_m']==1200:raise ValueError('unit input rejection')
        return {'nx':3},{}
    monkeypatch.setattr(search,'prepare',prepare)
    prepared,rejected=search.prepare_candidates(config,tmp_path,spec)
    assert config==original
    assert len(prepared)==6 and len(rejected)==3
    assert {c['source']['volume_m3'] for c in seen}=={original['source']['volume_m3']}
    assert all(c['geometry']==original['geometry'] for c in seen)
    assert load(tmp_path/'D12_L1200/status.json')['status']=='rejected_inputs'


def test_one_shared_receiving_mask_excludes_every_source_grid(tmp_path):
    np.savez(tmp_path/'terrain_arrays.npz',xe=np.arange(5.),ye=np.arange(3.),bcell=np.full((2,4),-10.))
    setups=[{'source_bounds_xyxy_m':[0,0,1,2]},{'source_bounds_xyxy_m':[2,0,3,2]}]
    spec={'receiver_bounds_xyxy_m':[0,0,4,2]}
    mask=search.receiver_mask(tmp_path,setups,spec)
    assert mask.tolist()==[[False,True,False,True]]*2
    with pytest.raises(ValueError,match='No common'):
        search.receiver_mask(tmp_path,[{'source_bounds_xyxy_m':[0,0,4,2]}],spec)


def test_score_has_known_values_and_rejects_nan(targets):
    metrics={t:{'max_positive_eta_m':v} for t,v in targets['temporal'].items()}
    assert search.rms_score(metrics,523.9,30.,targets)==0.
    assert search.rms_score(metrics,523.9,None,targets)==pytest.approx(np.sqrt(4/5))
    metrics['8']['max_positive_eta_m']*=2
    assert search.rms_score(metrics,523.9,30.,targets)==pytest.approx(np.sqrt(1/5))
    metrics['8']['max_positive_eta_m']=float('nan')
    with pytest.raises(ValueError,match='Nonfinite'):search.rms_score(metrics,523.9,30.,targets)


def test_selection_preserves_baseline_on_tie_and_never_promotes_nan():
    baseline={'candidate':'baseline','status':'completed','score':.3}
    other={'candidate':'new','status':'completed','score':.3}
    bad={'candidate':'nan','status':'completed','score':float('nan')}
    assert search.select([baseline,other,bad]) is baseline
    other['score']=.2;assert search.select([baseline,other,bad]) is other
    with pytest.raises(ValueError):search.select([bad,{'status':'failed'}])


@pytest.fixture
def fake_frames(monkeypatch):
    times=[0.,8.,10.,20.]
    values={8.:272.4,10.:251.1,20.:161.5,0.:0.}
    def read(folder,index):
        q=np.zeros((2,3,4));q[:,:,0]=2.;q[:,:,3]=values[times[index]]
        return times[index],[SimpleNamespace(q=q)]
    monkeypatch.setattr(search,'frame_numbers',lambda f:list(range(4)))
    monkeypatch.setattr(search,'read_frame',read)
    return times,values


def test_frame_metrics_require_actual_target_times_and_same_grid(tmp_path,fake_frames):
    mask=np.ones((2,3),dtype=bool)
    actual=search.frame_metric(tmp_path,mask,['8','10','20'],1e-6)
    assert actual['8']=={'frame_time_s':8.,'max_positive_eta_m':272.4}
    with pytest.raises(ValueError,match='required time'):search.frame_metric(tmp_path,mask,['9'],1e-6)
    with pytest.raises(ValueError,match='grid differs'):search.frame_metric(tmp_path,np.ones((2,2),bool),['8'],1e-6)
    with pytest.raises(ValueError,match='finite receiving'):search.frame_metric(tmp_path,np.zeros((2,3),bool),['8'],1e-6)
    fake_frames[1][8.]=-1.
    assert search.frame_metric(tmp_path,mask,['8'],1e-6)['8']['max_positive_eta_m']==0.


def write_monitor(folder,rows):
    np.savetxt(folder/'opposite_slope_max_depth.csv',rows,delimiter=',',header='x,y,level,B,h,t,arrival',comments='')


def test_arrival_excludes_initially_wet_points_and_unwetted_land(tmp_path,config):
    rows=np.array([[1,1,1,-20,20,0,0],[2,1,1,10,.01,5,1],[3,1,1,20,.5,40,30],[4,1,1,2000,.5,40,2]])
    write_monitor(tmp_path,rows)
    assert search.opposite_arrival(tmp_path,config)==30.
    write_monitor(tmp_path,rows[:1]);assert search.opposite_arrival(tmp_path,config) is None
    write_monitor(tmp_path,np.ones((2,3)))
    with pytest.raises(ValueError,match='Invalid'):search.opposite_arrival(tmp_path,config)
    (tmp_path/'opposite_slope_max_depth.csv').unlink()
    with pytest.raises(ValueError,match='Missing'):search.opposite_arrival(tmp_path,config)


def test_measure_requires_validation_and_retains_source_placement(tmp_path,config,targets,fake_frames):
    save(tmp_path/'slide/validation.json',{'status':'failed'})
    with pytest.raises(ValueError):search.measure(tmp_path,'unit',config,np.ones((2,3),bool),targets)
    save(tmp_path/'slide/validation.json',{'status':'passed_basic_checks','opposite_SW_slope_max_wetted_cell_elevation_m':523.9})
    save(tmp_path/'inputs/source_placement.json',{'unit_fixture':True})
    write_monitor(tmp_path/'slide',np.array([[1,1,1,20,.5,40,30]]))
    result=search.measure(tmp_path,'unit',config,np.ones((2,3),bool),targets)
    assert result['score']==0.
    assert result['placement']=={'unit_fixture':True}


@pytest.mark.parametrize('failure',['none','one_failed','all_rejected','baseline_best'])
def test_search_runs_each_slide_against_same_control_and_keeps_records(tmp_path,config,targets,spec,monkeypatch,failure):
    baseline=tmp_path/'baseline';baseline.mkdir()
    destination=tmp_path/'calibration'
    setup={'source_bounds_xyxy_m':[1,1,2,2]}
    def prepared(base,out,spec):
        if failure=='all_rejected':return [],[{'candidate':'c1','status':'rejected_inputs','error':'unit'}]
        result=[]
        for name in ['c1','c2']:
            case=out/name;case.mkdir(parents=True)
            result.append({'candidate':name,'case':case,'config':copy.deepcopy(config),'setup':setup})
        return result,[]
    monkeypatch.setattr(search,'prepare_candidates',prepared)
    monkeypatch.setattr(search,'receiver_mask',lambda *args:np.ones((2,3),bool))
    controls=[]
    def run(cfg,settings,case,control):
        controls.append(control)
        if failure=='one_failed' and case.name=='c2':raise ValueError('unit solver failure')
    monkeypatch.setattr(search,'run_cases',run)
    def measure(case,name,*args):
        score=.1 if name=='baseline' and failure=='baseline_best' else (.5 if name=='baseline' else .2)
        return {'candidate':name,'status':'completed','score':score}
    monkeypatch.setattr(search,'measure',measure)
    if failure=='all_rejected':
        with pytest.raises(ValueError,match='Every source candidate'):search.run_search(config,baseline,setup,destination,spec,targets)
        return
    selected,records=search.run_search(config,baseline,setup,destination,spec,targets)
    assert controls==[baseline,baseline]
    assert selected==(baseline if failure=='baseline_best' else destination/'c1')
    assert len(records)==3
    summary=load(destination/'selection.json')
    assert summary['improved_proxy_score']==(failure!='baseline_best')
    assert summary['incomplete_candidates']==(1 if failure=='one_failed' else 0)
    if failure=='one_failed':assert (destination/'c2/last_error.txt').exists()
