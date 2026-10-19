"""Small, strict reader for this bundle's GeoClaw 5.14 ASCII output.

GeoClaw fort.q rows are h, hu, hv, eta, progressing WEST to EAST and SOUTH
to NORTH. That is not the north-first ordering of a topography input raster.
Refinement levels other than 1 are deliberately rejected in this starter.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import re
import numpy as np

def number(text):
    value = text.strip().replace('D', 'E').replace('d', 'e')
    if 'e' not in value.lower():
        value = re.sub('(?<=\\d)([+-]\\d{3})$', 'E\\1', value)
    return float(value)

@dataclass
class Patch:
    grid_number: int
    level: int
    nx: int
    ny: int
    xlower: float
    ylower: float
    dx: float
    dy: float
    q: np.ndarray

    @property
    def extent(self):
        return [self.xlower, self.xlower + self.nx * self.dx, self.ylower, self.ylower + self.ny * self.dy]

    def eta(self, dry_tolerance=0.001):
        return np.ma.masked_where(self.q[:, :, 0] <= dry_tolerance, self.q[:, :, 3])

    def at(self, x_m, y_m):
        i = int(np.floor((x_m - self.xlower) / self.dx))
        j = int(np.floor((y_m - self.ylower) / self.dy))
        if 0 <= i < self.nx and 0 <= j < self.ny:
            return self.q[j, i]
        return None

def frame_numbers(folder):
    files = sorted(Path(folder).glob('fort.t[0-9][0-9][0-9][0-9]'))
    if not files:
        raise FileNotFoundError('No GeoClaw frames. A guide or input file is not a simulation result. Run the solver first.')
    return [int(p.name[-4:]) for p in files]

def read_frame(folder, frame):
    folder = Path(folder)
    header = [s for s in (folder / f'fort.t{frame:04d}').read_text().splitlines() if s.strip()]
    if len(header) < 5:
        raise ValueError('Incomplete fort.t header.')
    time = number(header[0].split()[0])
    neq = int(number(header[1].split()[0]))
    count = int(number(header[2].split()[0]))
    if neq != 4 or int(number(header[4].split()[0])) != 2:
        raise ValueError('Expected the 2-D shallow-water output h, hu, hv, eta.')
    if len(header) >= 7 and header[6].split()[0].strip('\'"').lower() != 'ascii':
        raise ValueError('Only ASCII output is supported by this teaching reader.')
    if not np.isfinite(time) or time < 0 or count != 1:
        raise ValueError('Expected one fixed-grid patch at a finite nonnegative time.')
    lines = iter((s.strip() for s in (folder / f'fort.q{frame:04d}').read_text().splitlines() if s.strip()))
    patches = []
    try:
        for _ in range(count):
            h = [number(next(lines).split()[0]) for __ in range(8)]
            grid, level, nx, ny = map(int, h[:4])
            if not np.isfinite(h).all() or h[6] <= 0 or h[7] <= 0:
                raise ValueError('Invalid patch coordinates or cell spacing.')
            if level != 1 or nx < 1 or ny < 1:
                raise ValueError("This reader is limited to this bundle's single-level configuration.")
            values = []
            for __ in range(nx * ny):
                row = [number(t) for t in next(lines).split()]
                if len(row) != 4:
                    raise ValueError('Expected four values per GeoClaw cell.')
                values.append(row)
            q = np.array(values).reshape(ny, nx, 4)
            if not np.all(np.isfinite(q)):
                raise ValueError('Non-finite values in solver output.')
            patches.append(Patch(grid, level, nx, ny, *h[4:], q))
        if next(lines, None) is not None:
            raise ValueError('Unexpected trailing data in fort.q file.')
    except StopIteration as exc:
        raise ValueError('Truncated GeoClaw output file.') from exc
    return (time, patches)

def read_gauge(folder, number_):
    path = Path(folder) / f'gauge{number_:05d}.txt'
    if not path.is_file():
        raise FileNotFoundError(f'Missing gauge output {path.name}.')
    rows = []
    for line in path.read_text().splitlines():
        if line.strip() and (not line.lstrip().startswith('#')):
            rows.append([number(t) for t in line.split()])
    a = np.array(rows, dtype=float)
    if a.ndim != 2 or a.shape[1] != 6 or (not np.isfinite(a).all()):
        raise ValueError('Expected finite ASCII gauge columns: level, time, h, hu, hv, eta.')
    if np.any(np.diff(a[:, 1]) < 0):
        raise ValueError('Gauge time is not monotone; check for mixed/restarted results.')
    return a
