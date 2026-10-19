import hashlib
from pathlib import Path
import struct
from types import SimpleNamespace
import zipfile

import numpy as np
import pytest

from simulation.common import load, save
from tools import image_manifest, rebuild_reference, smoke, stl_sampling
from conftest import write_frame


def binary_stl(path,vertices):
    data=np.zeros(len(vertices),dtype=stl_sampling.DTYPE)
    data['vertices']=vertices
    path.write_bytes(b'unit fixture'.ljust(80,b' ')+struct.pack('<I',len(vertices))+data.tobytes())


def test_binary_mesh_reader_and_ray_intersections(tmp_path):
    p=tmp_path/'triangle.stl'
    vertices=np.array([[[0,0,1],[2,0,1],[0,2,1]],[[0,0,3],[2,0,3],[0,2,3]],
                       [[0,0,0],[0,0,1],[0,0,2]],[[100,100,9],[101,100,9],[100,101,9]]],dtype=float)
    binary_stl(p,vertices)
    data=stl_sampling.load_stl(p)
    lo,hi=stl_sampling.ray_envelopes(data['vertices'],np.arange(4.),np.arange(4.))
    assert lo[0,0]==1 and hi[0,0]==3
    assert np.isnan(hi[3,3])
    lo,hi=stl_sampling.ray_envelopes(data['vertices'],np.array([0.]),np.array([0.]))
    assert lo.shape==(1,1) and hi[0,0]==3
    p.write_bytes(b'short')
    with pytest.raises(ValueError,match='Truncated'):stl_sampling.load_stl(p)
    p.write_bytes(b'x'*80+struct.pack('<I',2)+b'x')
    with pytest.raises(ValueError,match='binary STL'):stl_sampling.load_stl(p)


def test_mesh_sampler_cli_writes_diagnostics(tmp_path,monkeypatch):
    folder=tmp_path/'stls';folder.mkdir();binary_stl(folder/'unit.stl',np.array([[[0,0,1],[1,0,1],[0,1,1]]]))
    monkeypatch.setattr(stl_sampling,'ray_envelopes',lambda v,x,y:(np.full((len(y),len(x)),np.nan),np.full((len(y),len(x)),np.nan)))
    out=tmp_path/'out';stl_sampling.main(['--stl-dir',str(folder),'--output',str(out)])
    assert len(load(out/'sampling_log.json'))==3
    assert (out/'gilbert_5m.npz').is_file()


def test_rebuild_records_every_original_component(tmp_path,monkeypatch):
    folder=tmp_path/'stls';folder.mkdir()
    names=rebuild_reference.NATURAL+['VirtualWall','DomainRemover','Rockslide','Waterbody']
    for name in names:binary_stl(folder/(name+'.stl'),np.array([[[0,0,1],[1,0,1],[0,1,1]]]))
    monkeypatch.setattr(rebuild_reference,'ray_envelopes',lambda v,x,y:(np.ones((len(y),len(x))),np.ones((len(y),len(x)))*2))
    out=tmp_path/'rebuilt';rebuild_reference.build(folder,out,'unit-archive')
    metadata=load(out/'mesh_sampling.json')
    assert len(metadata['meshes'])==11
    assert metadata['derived_grid_sha256']==rebuild_reference.sha(out/'mesh_surfaces_15m.npz')
    with np.load(out/'mesh_surfaces_15m.npz') as data:assert 'Rockslide_lower' in data


def test_rebuild_archive_integrity_and_safe_extraction(tmp_path,monkeypatch):
    archive=tmp_path/'unit.zip'
    with zipfile.ZipFile(archive,'w') as z:
        for name in rebuild_reference.NATURAL+['VirtualWall','DomainRemover','Rockslide','Waterbody']:
            z.writestr('../../arbitrary/'+name+'.stl',b'unit mesh bytes')
    with pytest.raises(ValueError,match='checksum'):rebuild_reference.main([str(archive),'--output',str(tmp_path/'out')])
    monkeypatch.setattr(rebuild_reference,'ARCHIVE_SHA',rebuild_reference.sha(archive))
    seen=[]
    def build(stls,out,digest):
        seen.append((stls,out,digest));assert len(list(stls.glob('*.stl')))==11
        assert (stls/'Rockslide.stl').read_bytes()==b'unit mesh bytes'
    monkeypatch.setattr(rebuild_reference,'build',build)
    rebuild_reference.main([str(archive),'--output',str(tmp_path/'out')])
    assert len(seen)==1
    with zipfile.ZipFile(archive,'w') as z:z.writestr('Rockslide.stl',b'unit')
    monkeypatch.setattr(rebuild_reference,'ARCHIVE_SHA',rebuild_reference.sha(archive))
    with pytest.raises(ValueError,match='Missing/ambiguous'):rebuild_reference.main([str(archive)])


def test_image_manifest_only_accepts_executed_smoke_record(tmp_path,monkeypatch):
    root=tmp_path/'root';(root/'geoclaw').mkdir(parents=True)
    (root/'geoclaw/Makefile').write_text('unit make');(root/'geoclaw/xgeoclaw').write_bytes(b'unit binary')
    monkeypatch.setattr(image_manifest,'ROOT',root);monkeypatch.setenv('CLAW','/unit/claw')
    monkeypatch.setattr(image_manifest.subprocess,'check_output',lambda args,**k:'gfortran unit\n' if args[0]=='gfortran' else 'unit-version\n')
    monkeypatch.setattr(image_manifest.metadata,'distributions',lambda:[SimpleNamespace(metadata={'Name':'unit-package'},version='1')])
    smoke_path=tmp_path/'smoke.json';save(smoke_path,{'status':'failed'})
    with pytest.raises(ValueError):image_manifest.create(smoke_path,tmp_path/'manifest.json')
    save(smoke_path,{'status':'passed','fixture':'unit mock, not actual solver'})
    image_manifest.main(['--smoke',str(smoke_path),'--output',str(tmp_path/'manifest.json')])
    result=load(tmp_path/'manifest.json')
    assert result['packages']==['unit-package==1']
    assert result['compiler']=='gfortran unit'
    assert result['solver_sha256']==hashlib.sha256(b'unit binary').hexdigest()


@pytest.mark.parametrize('problem',['none','exit','count','negative','end','still_wave','no_signal'])
def test_smoke_harness_with_explicit_fake_executable(tmp_path,monkeypatch,problem):
    def write(folder,*args):folder.mkdir(parents=True,exist_ok=True)
    monkeypatch.setattr(smoke,'write_data',write)
    def run(args,cwd,**kwargs):
        if problem=='exit':return SimpleNamespace(returncode=1,stdout='unit process failure',stderr='')
        count=2 if problem=='count' else 3
        for index in range(count):
            q=np.array([[[20.,0.,0.,0.]]])
            if cwd.name=='slide' and index>0 and problem!='no_signal':q[0,0,3]=.1
            if problem=='negative':q[0,0,0]=-1.
            if problem=='still_wave':q[0,0,3]=1.
            time=index if problem!='end' else index*.5
            write_frame(cwd,index,time,q)
        return SimpleNamespace(returncode=0,stdout='',stderr='')
    monkeypatch.setattr(smoke.subprocess,'run',run)
    args=['--executable',str(tmp_path/'unit_fake_solver'),'--report',str(tmp_path/'report.json')]
    if problem=='none':
        smoke.main(args)
        report=load(tmp_path/'report.json')
        assert report['status']=='passed' and len(report['cases'])==2
    else:
        with pytest.raises((ValueError,RuntimeError)):smoke.main(args)
        assert not (tmp_path/'report.json').exists()
