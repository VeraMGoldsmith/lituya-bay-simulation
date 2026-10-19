"""Release measurement integration; fixtures are not hydrodynamic solutions."""
import copy
import json
import numpy as np
import pytest
from simulation.monitoring import monitor_specs, monitor_points, read_monitors
from simulation.validate import validate
from simulation.common import load, ROOT


def test_default_retains_legacy_window(config):
    before=copy.deepcopy(config)
    specs,primary=monitor_specs(config)
    assert primary=='legacy' and specs[0]['bounds_xyxy_m']==[900.,900.,2500.,2300.]
    assert config==before


@pytest.mark.parametrize('change', ['empty','duplicate','bad_name','bad_number','bad_bounds','nan_bounds','missing_primary','missing_legacy'])
def test_invalid_monitor_definitions_rejected(config,change):
    specs,primary=monitor_specs(config)
    c=copy.deepcopy(config); c['diagnostics']={'runup_monitors':specs,'primary_runup_monitor':primary}
    if change=='empty':c['diagnostics']['runup_monitors']=[]
    elif change=='duplicate':specs.append(copy.deepcopy(specs[0]))
    elif change=='bad_name':specs[0]['name']='../escape'
    elif change=='bad_number':specs[0]['fgno']=True
    elif change=='bad_bounds':specs[0]['bounds_xyxy_m']=[1.,0.,1.,2.]
    elif change=='nan_bounds':specs[0]['bounds_xyxy_m'][0]=float('nan')
    elif change=='missing_primary':c['diagnostics']['primary_runup_monitor']='other'
    elif change=='missing_legacy':specs[0]['fgno']=2
    with pytest.raises(ValueError):monitor_specs(c)


def test_cell_centres_and_source_separation():
    setup={'domain_xyxy_m':[0.,0.,4.,3.], 'nx':4,'ny':3,'source_bounds_xyxy_m':[0.,2.,4.,3.]}
    spec={'bounds_xyxy_m':[0.,0.,3.,1.]}
    x,y=monitor_points(spec,setup,require_static=True)
    assert x.tolist()==[.5,1.5,2.5] and y.tolist()==[.5,.5,.5]
    with pytest.raises(ValueError,match='overlap'):
        monitor_points({'bounds_xyxy_m':[0.,1.,3.,3.]},setup,require_static=True)
    with pytest.raises(ValueError,match='footprint'):
        monitor_points(spec,{k:v for k,v in setup.items() if k!='source_bounds_xyxy_m'},require_static=True)


@pytest.mark.parametrize('bounds', [[-1.,0.,3.,1.],[0.,0.,5.,3.],[.1,.1,.2,.2]])
def test_no_silent_domain_clipping_or_empty_monitors(bounds):
    setup={'domain_xyxy_m':[0.,0.,4.,3.],'nx':4,'ny':3}
    with pytest.raises(ValueError):monitor_points({'bounds_xyxy_m':bounds},setup)


def test_invalid_grid_rejected():
    with pytest.raises(ValueError,match='grid'):
        monitor_points({'bounds_xyxy_m':[0.,0.,1.,1.]},{'domain_xyxy_m':[0.,0.,1.,1.],'nx':0,'ny':3})


def test_integrated_reader_and_validator_agree(model_factory):
    folder,inputs,c,setup=model_factory()
    measured=read_monitors(folder,inputs,c,setup)
    result=validate(folder,'slide',c,setup,inputs)
    assert result['runup_diagnostics']==measured
    assert result['runup_primary']['maximum_wetted_cell_elevation_m']==2.
    assert result['runup_primary']['peak_touches_monitor_boundary']
    assert result['historically_calibrated'] is False


@pytest.mark.parametrize('problem', ['missing_row','shifted_points','unobserved','missing_mask','missing_second','no_natural_land'])
def test_integrated_measurements_fail_closed(model_factory,problem):
    folder,inputs,c,setup=model_factory()
    m=np.loadtxt(folder/'fgmax0001.txt')
    if problem=='missing_row':m=m[:-1]
    elif problem=='shifted_points':m[:,0]+=.1
    elif problem=='unobserved':m[0,2]=0
    elif problem=='no_natural_land':m[:,3]=-2.
    elif problem=='missing_mask':
        with np.load(inputs/'terrain_arrays.npz') as d:a={k:d[k] for k in d.files if k!='wall'}
        np.savez(inputs/'terrain_arrays.npz',**a)
    elif problem=='missing_second':
        c['diagnostics']['runup_monitors'].append({'name':'expanded','fgno':2,'bounds_xyxy_m':[0.,0.,3.,2.]})
        c['diagnostics']['primary_runup_monitor']='expanded'
    np.savetxt(folder/'fgmax0001.txt',m)
    with pytest.raises(ValueError):validate(folder,'slide',c,setup,inputs)
    result=load(folder/'validation.json')
    assert result['status']=='failed'
    assert result['opposite_SW_slope_max_wetted_cell_elevation_m'] is None


def test_artificial_overlap_cannot_win_the_metric(model_factory):
    folder,inputs,c,setup=model_factory()
    with np.load(inputs/'terrain_arrays.npz') as d:a={k:d[k] for k in d.files}
    a['excluded'][0,3]=True
    np.savez(inputs/'terrain_arrays.npz',**a)
    m=np.loadtxt(folder/'fgmax0001.txt');m[2,3]=1900.;m[2,4]=1.;m[5,4]=.3
    np.savetxt(folder/'fgmax0001.txt',m)
    result=read_monitors(folder,inputs,c,setup)['monitors']['legacy']
    assert result['maximum_wetted_cell_elevation_m']==2.
    assert result['wetted_artificial_monitor_cells']==1


def test_new_primary_does_not_overwrite_legacy_scalar(model_factory):
    folder,inputs,c,setup=model_factory()
    c['diagnostics']['runup_monitors'][0]['bounds_xyxy_m']=[2.,1.,3.,2.]
    c['diagnostics']['runup_monitors'].append({'name':'expanded','fgno':2,'bounds_xyxy_m':[0.,0.,3.,2.]})
    c['diagnostics']['primary_runup_monitor']='expanded'
    m=np.loadtxt(folder/'fgmax0001.txt')
    np.savetxt(folder/'fgmax0002.txt',m)
    np.savetxt(folder/'fgmax0001.txt',m[-1:])
    result=validate(folder,'slide',c,setup,inputs)
    assert result['opposite_SW_slope_max_wetted_cell_elevation_m']==0.
    assert result['runup_primary']['maximum_wetted_cell_elevation_m']==2.
    assert (folder/'runup_expanded_max_depth.csv').is_file()


def test_frozen_release_changes_only_diagnostics(config):
    c=load(ROOT/'release/frozen_baseline_config.json')
    diagnostics=c.pop('diagnostics')
    assert c==config
    assert diagnostics['primary_runup_monitor']=='expanded'
    assert diagnostics['require_static_runup_terrain'] is True


@pytest.mark.reference_data
def test_real_prepared_monitor_geometry_is_expanded_and_static(prepared_inputs):
    inputs,c,setup,checks=prepared_inputs
    release=load(ROOT/'release/frozen_baseline_config.json')
    specs,primary=monitor_specs(release)
    legacy=monitor_points(specs[0],setup,require_static=True)
    expanded=monitor_points(specs[1],setup,require_static=True)
    assert len(legacy[0])==2491
    assert len(expanded[0])>len(legacy[0])
    assert expanded[0].min()<legacy[0].min()
    assert expanded[1].min()<legacy[1].min()
    assert expanded[1].max()==legacy[1].max()


def test_static_bed_mismatch_is_rejected(model_factory):
    folder,inputs,c,setup=model_factory()
    c['diagnostics']['require_static_runup_terrain']=True
    m=np.loadtxt(folder/'fgmax0001.txt');m[2,3]+=1.
    np.savetxt(folder/'fgmax0001.txt',m)
    with pytest.raises(ValueError,match='Static run-up bed'):
        read_monitors(folder,inputs,c,setup)


def test_static_bed_check_accepts_consistent_fixture(model_factory):
    folder,inputs,c,setup=model_factory()
    c['diagnostics']['require_static_runup_terrain']=True
    result=read_monitors(folder,inputs,c,setup)
    assert result['monitors']['legacy']['static_source_separation_checked']


def test_dashboard_uses_named_primary_and_keeps_legacy_distinct():
    from reporting.dashboard import runup_description
    v={'runup_primary':{'name':'expanded','maximum_wetted_cell_elevation_m':123.,'peak_touches_monitor_boundary':True},
       'opposite_SW_slope_max_wetted_cell_elevation_m':100.}
    text=runup_description(v)
    assert '123.00 m' in text and '100.00 m' in text and 'spatially truncated' in text
    v['runup_primary']['peak_touches_monitor_boundary']=False
    assert 'spatially truncated' not in runup_description(v)
