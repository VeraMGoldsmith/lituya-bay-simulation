from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from conftest import write_frame
from simulation.common import load
from simulation import read_output as reader
from simulation.validate import validate


@pytest.mark.parametrize('text,expected', [('1D+02',100.), ('1d-02',.01), ('1.2-100',1.2e-100), ('-2.5',-2.5), ('1.2+100',1.2e100)])
def test_fortran_numbers(text, expected):
    assert reader.number(text) == expected


def test_patch_coordinates_and_dry_mask():
    q = np.zeros((2, 3, 4)); q[0, 1] = [2, 1, 0, .5]
    p = reader.Patch(1, 1, 3, 2, 10., 20., 2., 3., q)
    assert p.extent == [10,16,20,26]
    assert p.at(12.1,20.1).tolist() == [2,1,0,.5]
    assert p.at(16.,20.) is None
    assert p.eta().mask[0,0] and not p.eta().mask[0,1]


def test_frame_round_trip(tmp_path):
    q = np.arange(24.).reshape(2,3,4)
    write_frame(tmp_path, 1, 2., q, xlower=100, ylower=200, dx=10, dy=20)
    assert reader.frame_numbers(tmp_path) == [1]
    t, patches = reader.read_frame(tmp_path, 1)
    assert t == 2
    np.testing.assert_array_equal(patches[0].q, q)
    assert patches[0].extent == [100,130,200,240]


def test_empty_frames_fail(tmp_path):
    with pytest.raises(FileNotFoundError, match='No GeoClaw frames'):
        reader.frame_numbers(tmp_path)


@pytest.mark.parametrize('change,error', [
    ('short_header','Incomplete'), ('equations','2-D'), ('dimension','2-D'),
    ('binary','ASCII'), ('bad_time','finite'), ('patch_count','one fixed'),
    ('level','single-level'), ('spacing','spacing'), ('columns','four values'),
    ('nan','Non-finite'), ('truncated','Truncated'), ('trailing','trailing'),
])
def test_malformed_frames_rejected(tmp_path, change, error):
    write_frame(tmp_path,0,0.,np.zeros((2,3,4)))
    t=tmp_path/'fort.t0000'; q=tmp_path/'fort.q0000'
    if change=='short_header': t.write_text('0\n4\n')
    elif change=='equations':t.write_text(t.read_text().replace('4 meqn','3 meqn'))
    elif change=='dimension':t.write_text(t.read_text().replace('2 ndim','3 ndim'))
    elif change=='binary':t.write_text(t.read_text().replace('ascii','binary'))
    elif change=='bad_time':t.write_text(t.read_text().replace('0.0 time','nan time'))
    elif change=='patch_count':t.write_text(t.read_text().replace('1 ngrids','2 ngrids'))
    elif change=='level':q.write_text(q.read_text().replace('1 level','2 level'))
    elif change=='spacing':q.write_text(q.read_text().replace('1.0 dx','-1.0 dx'))
    elif change=='columns':q.write_text('\n'.join(q.read_text().splitlines()[:8]+['0 0 0']*6))
    elif change=='nan':q.write_text(q.read_text().replace('0.000000000000000e+00','nan',1))
    elif change=='truncated':q.write_text('\n'.join(q.read_text().splitlines()[:10]))
    elif change=='trailing':q.write_text(q.read_text()+'0 0 0 0\n')
    with pytest.raises(ValueError, match=error):reader.read_frame(tmp_path,0)


@pytest.mark.parametrize('kind', ['missing','empty','bad_columns','nan','reversed'])
def test_bad_gauges(tmp_path,kind):
    p=tmp_path/'gauge00001.txt'
    data={'empty':'# no data\n','bad_columns':'1 0 2\n','nan':'1 0 nan 0 0 0\n',
          'reversed':'1 2 3 0 0 0\n1 1 3 0 0 0\n'}
    if kind!='missing':p.write_text(data[kind])
    with pytest.raises((ValueError,FileNotFoundError)):reader.read_gauge(tmp_path,1)


def test_gauge_comments_are_not_samples(tmp_path):
    (tmp_path/'gauge00001.txt').write_text('# header\n\n1 0 2 0 0 0\n1 2 3 0 0 1\n')
    assert reader.read_gauge(tmp_path,1).shape==(2,6)


@pytest.mark.parametrize('case',['still','slide'])
def test_valid_numerical_fixture(case,model_factory):
    folder,inputs,cfg,setup=model_factory(case)
    result=validate(folder,case,cfg,setup,inputs)
    assert result['status']=='passed_basic_checks'
    assert result['frames_read']==3
    assert result['historically_calibrated'] is False
    if case=='slide':
        assert result['opposite_SW_slope_max_wetted_cell_elevation_m']==2
        assert (folder/'opposite_slope_max_depth.csv').is_file()
    assert (folder/'field_history.csv').read_text().startswith('time_s,')


@pytest.mark.parametrize('problem,match',[
    ('negative','Invalid negative'),('initial_bed','Initial bed'),('not_rest','flat and at rest'),
    ('missing_frame','Missing frames'),('missing_zero','Missing t=0'),('still_wave','Still-water residual'),
    ('bed_change','Bed-change mismatch'),('no_signal','No resolved'),('gauge_dry','starts dry'),
    ('gauge_incomplete','incomplete'),('missing_fgmax','Missing per-timestep'),('bad_fgmax','Unexpected fgmax'),
])
def test_validation_failure_is_recorded(problem,match,model_factory):
    case='still' if problem=='still_wave' else 'slide'
    folder,inputs,cfg,setup=model_factory(case)
    if problem in {'negative','not_rest','still_wave','bed_change','no_signal'}:
        for index in range(3):
            time,patches=reader.read_frame(folder,index);q=patches[0].q.copy()
            if problem=='negative' and index==1:q[0,0,0]=-1.
            elif problem=='not_rest' and index==0:q[0,0,1]=1.
            elif problem=='still_wave' and index==1:q[0,0,0]+=.1;q[0,0,3]+=.1
            elif problem=='bed_change' and index==2:q[0,0,3]+=.5
            elif problem=='no_signal':q[:,:2,0]=2.;q[:,:2,3]=0.
            write_frame(folder,index,time,q)
    elif problem=='initial_bed':
        with np.load(inputs/'terrain_arrays.npz') as a:d={k:a[k] for k in a.files}
        d['bcell']=d['bcell']+.1;np.savez(inputs/'terrain_arrays.npz',**d)
    elif problem=='missing_frame':(folder/'fort.t0002').unlink()
    elif problem=='missing_zero':
        time,patches=reader.read_frame(folder,0);write_frame(folder,0,.1,patches[0].q)
    elif problem=='gauge_dry':
        g=np.loadtxt(folder/'gauge00001.txt');g[0,2]=0.;np.savetxt(folder/'gauge00001.txt',g)
    elif problem=='gauge_incomplete':
        g=np.loadtxt(folder/'gauge00001.txt');g[:,1]=[.1,.2,.3];np.savetxt(folder/'gauge00001.txt',g)
    elif problem=='missing_fgmax':(folder/'fgmax0001.txt').unlink()
    elif problem=='bad_fgmax':(folder/'fgmax0001.txt').write_text('1 2 3\n4 5 6\n')
    with pytest.raises(ValueError,match=match):validate(folder,case,cfg,setup,inputs)
    report=load(folder/'validation.json')
    assert report['status']=='failed' and report['errors']


def test_validation_wrong_grid_and_multiple_patches(model_factory,monkeypatch):
    import simulation.validate as module
    folder,inputs,cfg,setup=model_factory()
    setup['nx']=999
    with pytest.raises(ValueError,match='grid differs'):validate(folder,'slide',cfg,setup,inputs)
    monkeypatch.setattr(module,'read_frame',lambda f,n:(0,[None,None]))
    with pytest.raises(ValueError,match='exactly one'):validate(folder,'slide',cfg,setup,inputs)


def test_no_land_wetting_reports_zero_not_missing(model_factory):
    folder,inputs,cfg,setup=model_factory()
    monitor=np.loadtxt(folder/'fgmax0001.txt');monitor[:,4]=0.;np.savetxt(folder/'fgmax0001.txt',monitor)
    result=validate(folder,'slide',cfg,setup,inputs)
    assert result['opposite_SW_slope_max_wetted_cell_elevation_m']==0.
