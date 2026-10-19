"""Rebuild the packaged sampled geometry from the unchanged Franco ZIP.

Optional provenance/regridding step; not required for the first run.
Needs NumPy + Numba. Does not download, execute archived code, or change meshes.
"""
from pathlib import Path
import sys, argparse, zipfile, shutil, tempfile, json, hashlib
import numpy as np
from .stl_sampling import load_stl, ray_envelopes
NATURAL = ['Bathimetry', 'GilbertGlacier', 'DeltasGilbertInlet', 'CrillonInlet', 'SlopeGilbertNE', 'SlopesGilbertSW', 'Topography']
ARCHIVE_SHA = 'db4b7a598f6a1565a2e954d76873aa74ca4141fbdb7821e947498ae2708cd098'

def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()

def build(stls, out, archive_hash):
    x = np.arange(-1070.0, 5860.0 + 0.01, 15.0)
    y = np.arange(-8835.0, 4860.0 + 0.01, 15.0)
    arrays = {'x': x, 'y': y}
    log = []
    for name in NATURAL + ['VirtualWall', 'DomainRemover', 'Rockslide', 'Waterbody']:
        p = stls / (name + '.stl')
        m = load_stl(p)
        low, high = ray_envelopes(m['vertices'], x, y)
        arrays[name + '_upper'] = high
        if name in ['Rockslide', 'DomainRemover', 'Waterbody']:
            arrays[name + '_lower'] = low
        entry = {'file': name + '.stl', 'sha256': sha(p), 'triangles': len(m), 'valid_rays': int(np.isfinite(high).sum())}
        log.append(entry)
        print(name, entry['valid_rays'], flush=True)
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / 'mesh_surfaces_15m.npz', **arrays)
    (out / 'mesh_sampling.json').write_text(json.dumps({'archive_sha256': archive_hash, 'derived_grid_sha256': sha(out / 'mesh_surfaces_15m.npz'), 'native_water_level_m': 220.0, 'units': 'local Cartesian metres, NOT latitude/longitude', 'spacing_m': 15.0, 'method': 'Vertical ray intersections with original binary STL triangles; unmatched samples retained as NaN. Role-aware assembly occurs later in prepare.py.', 'meshes': log}, indent=2))

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('archive', type=Path)
    p.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'data/reference')
    a = p.parse_args(argv)
    digest = sha(a.archive)
    if digest != ARCHIVE_SHA:
        raise ValueError('Archive checksum does not match the reviewed Franco record. No files changed.')
    with tempfile.TemporaryDirectory(prefix='franco-stl-') as tmp:
        dest = Path(tmp)
        with zipfile.ZipFile(a.archive) as z:
            for name in NATURAL + ['VirtualWall', 'DomainRemover', 'Rockslide', 'Waterbody']:
                members = [n for n in z.namelist() if Path(n).name == name + '.stl']
                if len(members) != 1:
                    raise ValueError('Missing/ambiguous mesh: ' + name)
                with z.open(members[0]) as src, (dest / (name + '.stl')).open('wb') as dst:
                    shutil.copyfileobj(src, dst, 8 * 1024 * 1024)
        build(dest, a.output, digest)
if __name__ == '__main__':
    main()
