"""Nodal topography/dtopo conventions and exact bilinear cell integrals.

Internal arrays: [y,x], increasing local Y. Files: highest Y row first.
STL/terrain sampling spacing is not the solver resolution.
"""
import numpy as np
from scipy.sparse import csr_matrix
from scipy.ndimage import shift

def smoothstep(u):
    u = np.clip(u, 0.0, 1.0)
    return u * u * u * (10.0 + u * (-15.0 + 6.0 * u))

def movement(t, source):
    u = (np.asarray(t) - source['start_time_s']) / source['travel_duration_s']
    return source['travel_negative_y_m'] * smoothstep(u)

def shifted_thickness(s0, t, source, dy):
    return shift(s0, shift=(-float(movement(t, source)) / dy, 0), order=1, mode='constant', cval=0.0, prefilter=False)

def integrator(nodes, edges):
    """CSR matrix of integrals of 1-D piecewise-linear basis functions / cell width."""
    nodes = np.asarray(nodes, dtype=float)
    edges = np.asarray(edges, dtype=float)
    if len(nodes) < 2 or np.any(np.diff(nodes) <= 0) or np.any(np.diff(edges) <= 0):
        raise ValueError('Grid must increase.')
    if edges[0] < nodes[0] - 1e-08 or edges[-1] > nodes[-1] + 1e-08:
        raise ValueError('Terrain/source grid does not cover requested integral.')
    rows = []
    cols = []
    vals = []
    for j, (left, right) in enumerate(zip(edges[:-1], edges[1:])):
        i = max(0, min(len(nodes) - 2, np.searchsorted(nodes, left, side='right') - 1))
        while i < len(nodes) - 1 and nodes[i] < right - 1e-12:
            a = max(left, nodes[i])
            b = min(right, nodes[i + 1])
            dx = nodes[i + 1] - nodes[i]
            if b > a:
                weight_right = ((b - nodes[i]) ** 2 - (a - nodes[i]) ** 2) / (2 * dx * (right - left))
                rows.extend([j, j])
                cols.extend([i, i + 1])
                vals.extend([(b - a) / (right - left) - weight_right, weight_right])
            i += 1
    return csr_matrix((vals, (rows, cols)), shape=(len(edges) - 1, len(nodes)))

def cell_average(z, x, y, xe, ye):
    wx = integrator(x, xe)
    wy = integrator(y, ye)
    return (wx @ (wy @ z).T).T

def write_tt3(path, x, y, z):
    dx = x[1] - x[0]
    dy = y[1] - y[0]
    if not np.isclose(dx, dy, rtol=0, atol=1e-10):
        raise ValueError('This exporter uses square terrain nodes.')
    if not np.isfinite(z).all():
        raise ValueError('NoData may not be silently replaced in a solver file.')
    with open(path, 'w') as f:
        f.write(f'{len(x)} ncols\n{len(y)} nrows\n{x[0]:.12f} xlower\n{y[0]:.12f} ylower\n{dx:.12f} cellsize\n-99999 nodata_value\n')
        np.savetxt(f, z[::-1], fmt='%.10e')

def write_dtt3(path, x, y, times, dz):
    if not np.isfinite(dz).all() or dz.shape != (len(times), len(y), len(x)):
        raise ValueError('Bad moving-bed array.')
    with open(path, 'w') as f:
        for v, k in [(len(x), 'mx'), (len(y), 'my'), (len(times), 'mt'), (x[0], 'xlower'), (y[0], 'ylower'), (times[0], 't0'), (x[1] - x[0], 'dx'), (y[1] - y[0], 'dy'), (times[1] - times[0], 'dt')]:
            f.write(f'{v:.12g} {k}\n')
        for z in dz:
            np.savetxt(f, z[::-1], fmt='%.10e')

def read_tt3(path):
    with open(path) as f:
        nx, ny = (int(f.readline().split()[0]), int(f.readline().split()[0]))
        x0, y0, dx, _ = [float(f.readline().split()[0]) for k in range(4)]
        z = np.loadtxt(f)
    if z.shape != (ny, nx):
        raise ValueError('Wrong raster dimensions.')
    return (x0 + np.arange(nx) * dx, y0 + np.arange(ny) * dx, z[::-1])

def read_dtt3(path):
    with open(path) as f:
        h = [float(f.readline().split()[0]) for _ in range(9)]
        v = np.loadtxt(f)
    nx, ny, nt = map(int, h[:3])
    z = v.reshape(nt, ny, nx)[:, ::-1]
    return (h[3] + np.arange(nx) * h[6], h[4] + np.arange(ny) * h[7], h[5] + np.arange(nt) * h[8], z)
