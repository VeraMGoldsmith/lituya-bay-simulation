import copy
from pathlib import Path
from types import SimpleNamespace
import sys

import numpy as np
import pytest

from simulation import common, numerics
from simulation.placement import centroid
from simulation.prepare import validate_config
from geoclaw import setrun as geo


def test_common_atomic_records_and_paths(tmp_path,monkeypatch):
    p=tmp_path/'nested/config.json'
    common.save(p,{'x':1}); assert common.load(p)=={'x':1}
    first=common.sha(p);common.save(p,{'x':2});assert common.sha(p)!=first
    assert common.hash_json({'b':2,'a':1})==common.hash_json({'a':1,'b':2})
    with pytest.raises(ValueError):common.save(p,{'x':float('nan')})
    assert common.load(p)=={'x':2}
    assert '+00:00' in common.now()
    session=common.new_session(tmp_path)
    assert session.parent==tmp_path/'runs'
    assert common.inside(tmp_path,'runs/'+session.name)==session
    for name in ['../bad','/tmp/bad','']:
        with pytest.raises(ValueError):common.inside(tmp_path,name)
    outside=tmp_path.parent/'outside';outside.mkdir(exist_ok=True)
    (tmp_path/'escape').symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError):common.inside(tmp_path,'escape/file')
    def fail(*args):raise OSError('rename failed')
    monkeypatch.setattr(common.os,'replace',fail)
    with pytest.raises(OSError):common.save(p,{'x':3})
    assert not list(p.parent.glob('.config.json*'))


@pytest.mark.parametrize('part,key,value',[
    ('source','travel_negative_y_m',0),('source','maximum_solver_step_during_motion_s',float('nan')),
    ('run','early_output_interval_s',0),('run','early_output_until_s',-1),
    ('run','early_output_until_s',float('inf')),('geometry','sw_relief_factor',1.3),
    ('water','sea_level_m',1),('coordinates','native_reference_water_z_m',200),
    ('source','start_time_s',420),('source','start_time_s',415),
])
def test_configuration_boundaries(config,part,key,value):
    config[part][key]=value
    with pytest.raises(ValueError):validate_config(config)


def test_numeric_failures_and_centroid(tmp_path):
    for nodes,edges in [([0],[0,1]),([1,0],[0,1]),([0,1],[1,0])]:
        with pytest.raises(ValueError):numerics.integrator(nodes,edges)
    with pytest.raises(ValueError,match='square'):
        numerics.write_tt3(tmp_path/'a',np.arange(2.),np.arange(2.)*2,np.ones((2,2)))
    with pytest.raises(ValueError):numerics.write_dtt3(tmp_path/'a',np.arange(2.),np.arange(2.),np.arange(2.),np.ones((1,2,2)))
    p=tmp_path/'a';numerics.write_tt3(p,np.arange(2.),np.arange(2.),np.ones((2,2)))
    p.write_text(p.read_text().replace('2 nrows','3 nrows'))
    with pytest.raises(ValueError,match='dimensions'):numerics.read_tt3(p)
    assert centroid(np.array([[0,1],[0,1]]),np.array([5,10]),np.array([20,30]))==[10.,25.]
    for a in [np.zeros((2,2)),np.full((2,2),np.nan),np.full((2,2),-1.)]:
        with pytest.raises(ValueError):centroid(a,np.arange(2.),np.arange(2.))


@pytest.fixture
def fake_claw(monkeypatch):
    class Data:
        def __init__(self,*args):
            for name in ['clawdata','amrdata','regiondata','refinement_data','geo_data','topo_data','dtopo_data','qinit_data','gaugedata']:
                setattr(self,name,SimpleNamespace())
            self.fgmax_data=SimpleNamespace(fgmax_grids=[])
    modules={'clawpack':SimpleNamespace(), 'clawpack.clawutil':SimpleNamespace(),
             'clawpack.clawutil.data':SimpleNamespace(ClawRunData=Data),
             'clawpack.geoclaw':SimpleNamespace(),
             'clawpack.geoclaw.fgmax_tools':SimpleNamespace(FGmaxGrid=SimpleNamespace)}
    for name,mod in modules.items():monkeypatch.setitem(sys.modules,name,mod)
    return Data


def test_setrun_controls_and_source(config,fake_claw,tmp_path):
    setup={'domain_xyxy_m':[0,0,3000,3000],'nx':30,'ny':30,'gauges':[{'id':1,'x_m':1500,'y_m':2000}]}
    still=geo.setrun(config,setup,'still',tmp_path)
    slide=geo.setrun(config,setup,'slide',tmp_path)
    assert still.dtopo_data.dtopofiles==[]
    assert slide.dtopo_data.dtopofiles==[[3,str(tmp_path/'slide.dtt3')]]
    assert slide.qinit_data.qinit_type==0
    assert slide.clawdata.bc_upper==['extrap','wall']
    assert slide.amrdata.amr_levels_max==1
    assert slide.refinement_data.variable_dt_refinement_ratios is True
    assert slide.amrdata.tprint is True
    assert slide.dtopo_data.dt_max_dtopo == config["source"]["maximum_solver_step_during_motion_s"]
    assert slide.fgmax_data.fgmax_grids[0].npts>0
    assert slide.clawdata.output_times[0]==0 and slide.clawdata.output_times[-1]==420
    setup['synthetic_smoke_test']=True
    assert geo.setrun(config,setup,'still',tmp_path).fgmax_data.fgmax_grids==[]
    with pytest.raises(ValueError,match='Unknown case'):geo.setrun(config,setup,'other',tmp_path)


def test_write_data_makes_relative_paths_and_restores_cwd(tmp_path,config,monkeypatch):
    inputs=tmp_path/'inputs';inputs.mkdir()
    original=Path.cwd()
    def write():
        for name in ['topo.data','dtopo.data']:Path(name).write_text(str(inputs)+'/terrain.tt3')
    monkeypatch.setattr(geo,'setrun',lambda *a:SimpleNamespace(write=write))
    geo.write_data(tmp_path/'case',inputs,config,{},'still')
    assert (tmp_path/'case/topo.data').read_text()=='../inputs/terrain.tt3'
    assert Path.cwd()==original
    def fail():raise RuntimeError('unit failure')
    monkeypatch.setattr(geo,'setrun',lambda *a:SimpleNamespace(write=fail))
    with pytest.raises(RuntimeError):geo.write_data(tmp_path/'failed',inputs,config,{},'still')
    assert Path.cwd()==original


def test_release_uses_two_separate_perstep_monitors(config,fake_claw,tmp_path):
    from simulation.common import load,ROOT
    c=load(ROOT/'release/frozen_baseline_config.json')
    setup={'domain_xyxy_m':[-1010.,-8775.,5800.,4800.], 'nx':227,'ny':453,'gauges':[],
           'source_bounds_xyxy_m':[1120.,2370.,2200.,4725.]}
    r=geo.setrun(c,setup,'slide',tmp_path)
    assert [f.fgno for f in r.fgmax_data.fgmax_grids]==[1,2]
    assert r.fgmax_data.fgmax_grids[0].npts==2491
    assert r.fgmax_data.fgmax_grids[1].npts>2491
    assert all(f.dt_check==0 and f.interp_method==0 for f in r.fgmax_data.fgmax_grids)
