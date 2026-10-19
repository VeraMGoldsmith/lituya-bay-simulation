"""Inspect binary STL surfaces in the authors' local SI coordinates.

Creates geometry-inspection arrays, NOT solver-ready terrain. Upper/lower ray
intersections do not implement FLOW-3D FAVOR, domain removal or fluid clipping.
All unmatched grid samples remain NaN; no elevation is invented.
"""
from pathlib import Path
import argparse
import json
import struct
import time
import numpy as np
from numba import njit
DTYPE = np.dtype([('normal', '<f4', (3,)), ('vertices', '<f4', (3, 3)), ('attribute', '<u2')])

def load_stl(path: Path):
    with path.open('rb') as f:
        f.seek(80)
        raw = f.read(4)
    if len(raw) != 4:
        raise ValueError(f'Truncated STL: {path}')
    count = struct.unpack('<I', raw)[0]
    if path.stat().st_size != 84 + 50 * count:
        raise ValueError(f'Not a supported binary STL: {path}')
    return np.memmap(path, mode='r', dtype=DTYPE, offset=84, shape=(count,))

@njit(cache=True)
def ray_envelopes(vs, x, y):
    """Vertical-ray/triangle intersections, sampled at exact grid coordinates."""
    nx, ny = (len(x), len(y))
    lo = np.full((ny, nx), np.inf)
    hi = np.full((ny, nx), -np.inf)
    dx = x[1] - x[0] if nx > 1 else 1.0
    dy = y[1] - y[0] if ny > 1 else 1.0
    for k in range(vs.shape[0]):
        ax, ay, az = (float(vs[k, 0, 0]), float(vs[k, 0, 1]), float(vs[k, 0, 2]))
        bx, by, bz = (float(vs[k, 1, 0]), float(vs[k, 1, 1]), float(vs[k, 1, 2]))
        cx, cy, cz = (float(vs[k, 2, 0]), float(vs[k, 2, 1]), float(vs[k, 2, 2]))
        xmin, xmax = (min(ax, bx, cx), max(ax, bx, cx))
        ymin, ymax = (min(ay, by, cy), max(ay, by, cy))
        if xmax < x[0] or xmin > x[-1] or ymax < y[0] or (ymin > y[-1]):
            continue
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-12:
            continue
        i0 = max(0, int(np.ceil((xmin - x[0]) / dx - 1e-09)))
        i1 = min(nx - 1, int(np.floor((xmax - x[0]) / dx + 1e-09)))
        j0 = max(0, int(np.ceil((ymin - y[0]) / dy - 1e-09)))
        j1 = min(ny - 1, int(np.floor((ymax - y[0]) / dy + 1e-09)))
        for j in range(j0, j1 + 1):
            for i in range(i0, i1 + 1):
                a = ((by - cy) * (x[i] - cx) + (cx - bx) * (y[j] - cy)) / den
                b = ((cy - ay) * (x[i] - cx) + (ax - cx) * (y[j] - cy)) / den
                c = 1.0 - a - b
                if a >= -1e-08 and b >= -1e-08 and (c >= -1e-08):
                    z = a * az + b * bz + c * cz
                    hi[j, i] = max(hi[j, i], z)
                    lo[j, i] = min(lo[j, i], z)
    for j in range(ny):
        for i in range(nx):
            if not np.isfinite(hi[j, i]):
                hi[j, i] = np.nan
            if not np.isfinite(lo[j, i]):
                lo[j, i] = np.nan
    return (lo, hi)

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stl-dir', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    grids = {'whole_bay_30m': (np.arange(-995.0, 5800.0, 30.0), np.arange(-8760.0, 4800.0, 30.0)), 'gilbert_5m': (np.arange(302.5, 2600.0, 5.0), np.arange(1002.5, 4800.0, 5.0)), 'cross_section_x1550': (np.array([1550.0]), np.arange(1000.5, 4850.0, 1.0))}
    summary = []
    for name, (x, y) in grids.items():
        out = {'x': x, 'y': y}
        for path in sorted(args.stl_dir.glob('*.stl')):
            t = time.monotonic()
            mm = load_stl(path)
            lo, hi = ray_envelopes(mm['vertices'], x, y)
            out[path.stem + '_lower'] = lo
            out[path.stem + '_upper'] = hi
            summary.append({'grid': name, 'file': path.name, 'finite_samples': int(np.isfinite(hi).sum()), 'elapsed_seconds': time.monotonic() - t})
            print(name, path.name, int(np.isfinite(hi).sum()), round(time.monotonic() - t, 2), flush=True)
            del mm
        np.savez_compressed(args.output / (name + '.npz'), **out)
    (args.output / 'sampling_log.json').write_text(json.dumps(summary, indent=2))
if __name__ == '__main__':
    main()
