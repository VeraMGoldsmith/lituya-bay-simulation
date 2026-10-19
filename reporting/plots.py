"""Maps of prepared geometry; water plots ONLY from validated GeoClaw output."""
from pathlib import Path
import csv, json
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter
from simulation.common import load, save
from simulation.placement import centroid
from simulation.read_output import read_frame, frame_numbers, read_gauge

def source_outlines(ax, a, src, c):
    x, y = (src['x'], src['y'])
    initial = src['s0']
    final = src['dz'][-1] + initial
    ax.contour(x, y, initial, levels=[1.0], linewidths=1.3, linestyles='--')
    ax.contour(x, y, final, levels=[1.0], linewidths=1.3, linestyles=':')
    x0, y0 = centroid(initial, x, y)
    ax.annotate('', xy=(x0, y0 - c['source']['travel_negative_y_m']), xytext=(x0, y0), arrowprops={'arrowstyle': '->', 'linewidth': 1.6})

def input_previews(inputs, dest):
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    inputs = Path(inputs)
    a = np.load(inputs / 'terrain_arrays.npz')
    src = np.load(inputs / 'source_arrays.npz')
    setup = load(inputs / 'setup.json')
    c = load(inputs / 'config.json')
    for name, bounds in [('basin_setup', [-1010, 5800, -8775, 4800]), ('inlet_setup', [600, 2800, 800, 4800])]:
        fig, ax = plt.subplots(figsize=(8.5, 9), layout='constrained')
        z = a['base']
        excluded = a['excluded']
        masked = np.ma.masked_where((z >= 0) | excluded, z)
        im = ax.pcolormesh(a['x'], a['y'], masked, shading='nearest')
        ax.contour(a['x'], a['y'], np.ma.masked_where(excluded, z), levels=[0], linewidths=0.8)
        if name == 'inlet_setup':
            cs = ax.contour(a['x'], a['y'], np.ma.masked_where(excluded, z), levels=[100, 300, 500, 700, 900], linestyles='dotted', linewidths=0.5)
            ax.clabel(cs, fontsize=7, fmt='%d m')
            ax.text(1870, 4550, 'Original slide footprint', fontsize=9, ha='center')
            ax.text(1760, 2980, 'Gilbert Inlet', fontsize=11)
            ax.text(1530, 1200, 'Opposite SW slope', fontsize=10, ha='center')
            ax.contourf(a['x'], a['y'], a['wall'].astype(float), levels=[0.5, 1.5], alpha=0.35, hatches=['///'])
        source_outlines(ax, a, src, c)
        for p in setup['gauges']:
            x, y = (p['x_m'], p['y_m'])
            if bounds[0] <= x <= bounds[1] and bounds[2] <= y <= bounds[3]:
                ax.plot(x, y, 'o', markersize=4)
                ax.annotate(p['label'], (x, y), xytext=(5, 5), textcoords='offset points', fontsize=8)
        ax.set_xlim(bounds[:2])
        ax.set_ylim(bounds[2:])
        ax.set_aspect('equal')
        ax.set_xlabel('Native local X (m) — not longitude')
        ax.set_ylabel('Native local Y (m) — not geographic north')
        ax.set_title('Published reconstructed basin + prescribed-slide adaptation\nINPUT ONLY — dashed: initial slide; dotted: final footprint', fontsize=12)
        fig.colorbar(im, ax=ax, shrink=0.65, label='Static bed elevation relative to nominal water level (m)')
        fig.savefig(dest / (name + '.png'), dpi=160)
        plt.close(fig)
    i = int(np.argmin(abs(a['x'] - 1550.0)))
    y = a['y']
    mask = (y >= 1000) & (y <= 4800)
    q = y[mask]
    b = a['base'][mask, i]
    s0 = a['s0'][mask, i]
    dist = 4800 - q
    fig, ax = plt.subplots(figsize=(10, 5.5), layout='constrained')
    ax.fill_between(dist, -260, b, alpha=0.25, label='Stationary reconstructed terrain')
    ax.fill_between(dist, b, 0, where=b < 0, alpha=0.55, label='Initially resting water')
    ax.fill_between(dist, b, b + s0, alpha=0.7, label='Projected original slide thickness')
    ax.axhline(0, linestyle='--', linewidth=0.8)
    ax.set_xlim(0, 3800)
    ax.set_ylim(-260, 1050)
    ax.set_xlabel('Distance from local Y = 4800 m towards decreasing Y (m)')
    ax.set_ylabel('Elevation relative to nominal water (m)')
    ax.set_title('Source → NE shoreline → Gilbert Inlet → opposite SW slope\nPrepared model section near local X = 1550 m; not a wave result')
    ax.legend(fontsize=8, loc='upper right')
    fig.savefig(dest / 'source_section.png', dpi=170)
    plt.close(fig)

def results(session):
    session = Path(session)
    dest = session / 'plots'
    dest.mkdir(exist_ok=True)
    inp = session / 'inputs'
    c = load(inp / 'config.json')
    setup = load(inp / 'setup.json')
    status = load(session / 'status.json')
    if status.get('status') != 'completed_basic_checks':
        raise ValueError('No wave plots after a failed or incomplete numerical run.')
    for case in ('still', 'slide'):
        if load(session / case / 'validation.json')['status'] != 'passed_basic_checks':
            raise ValueError('A case lacks passed basic checks.')
    frames = frame_numbers(session / 'slide')
    fields = []
    times = []
    for n in frames:
        t, p = read_frame(session / 'slide', n)
        times.append(t)
        fields.append(p[0].q)
    q = np.array(fields)
    p = p[0]
    xe = np.linspace(p.xlower, p.xlower + p.nx * p.dx, p.nx + 1)
    ye = np.linspace(p.ylower, p.ylower + p.ny * p.dy, p.ny + 1)
    xc = (xe[:-1] + xe[1:]) / 2
    yc = (ye[:-1] + ye[1:]) / 2
    wet = q[:, :, :, 0] > 0.01
    eta = np.ma.masked_where(~wet, q[:, :, :, 3])
    peak = max(float(np.max(abs(eta))), 1.0)
    a = np.load(inp / 'terrain_arrays.npz')
    src = np.load(inp / 'source_arrays.npz')
    for name, bounds in [('basin', [-1010, 5800, -8775, 4800]), ('inlet', [600, 2800, 800, 4800])]:
        fig, ax = plt.subplots(figsize=(8, 9), layout='constrained')
        im = ax.pcolormesh(xe, ye, eta[0], shading='flat', vmin=-peak, vmax=peak)
        ax.contour(xc, yc, q[0, :, :, 3] - q[0, :, :, 0], levels=[0], linewidths=0.6)
        source_outlines(ax, a, src, c)
        for point in setup['gauges']:
            if bounds[0] <= point['x_m'] <= bounds[1] and bounds[2] <= point['y_m'] <= bounds[3]:
                ax.plot(point['x_m'], point['y_m'], 'o', markersize=3)
                ax.annotate(point['label'], (point['x_m'], point['y_m']), xytext=(4, 3), textcoords='offset points', fontsize=7)
        ax.set_xlim(bounds[:2])
        ax.set_ylim(bounds[2:])
        ax.set_aspect('equal')
        ax.set_xlabel('Native local X (m)')
        ax.set_ylabel('Native local Y (m)')
        title = ax.set_title('GeoClaw on published geometry — prescribed source candidate\nModel time 0 s; playback is not real time', fontsize=11)
        fig.colorbar(im, ax=ax, shrink=0.65, label='Water-surface elevation η (m above/below nominal water)')

        def update(k):
            im.set_array(eta[k].ravel())
            title.set_text(f'GeoClaw on published geometry — prescribed source candidate\nModel time {times[k]:g} s; playback is not real time')
            return (im, title)
        animation = FuncAnimation(fig, update, frames=len(times), interval=180, blit=False)
        animation.save(dest / (name + '_wave.gif'), writer=PillowWriter(fps=6), dpi=100)
        for seconds in [20, 40, 80, 200, c['run']['duration_s']]:
            k = int(np.argmin(abs(np.array(times) - seconds)))
            update(k)
            fig.savefig(dest / f'{name}_{times[k]:06.1f}s.png', dpi=130)
        plt.close(fig)
    rows = []
    gauge_data = {}
    for point in setup['gauges']:
        g = read_gauge(session / 'slide', point['id'])
        gauge_data[point['label']] = g
        for row in g:
            level, t, h, hu, hv, eta_ = row
            eta_value = eta_ if h > 0.01 else ''
            rows.append([point['id'], point['label'], point['x_m'], point['y_m'], t, h, hu, hv, eta_value])
    with (dest / 'gauges.csv').open('w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['id', 'label', 'x_m', 'y_m', 'time_s', 'depth_m', 'hu_m2_s', 'hv_m2_s', 'eta_m_blank_when_dry'])
        w.writerows(rows)
    for name, names in [('inlet_gauges', ['P1', 'P2', 'P3']), ('bay_gauges', ['P4', 'P5', 'P6', 'P8', 'P9'])]:
        fig, ax = plt.subplots(figsize=(10, 5.5), layout='constrained')
        for key in names:
            g = gauge_data[key]
            v = np.ma.masked_where(g[:, 2] <= 0.01, g[:, 5])
            ax.plot(g[:, 1], v, label=key)
        ax.set_xlabel('Simulated time (s)')
        ax.set_ylabel('Water-surface elevation (m)')
        ax.set_title('Actual GeoClaw gauge histories — prescribed-source adaptation')
        ax.legend()
        fig.savefig(dest / (name + '.png'), dpi=160)
        plt.close(fig)
    result = load(session / 'slide/validation.json')
    fg = np.loadtxt(session / 'slide/opposite_slope_max_depth.csv', delimiter=',', skiprows=1, ndmin=2)
    fig, ax = plt.subplots(figsize=(7, 7), layout='constrained')
    m = (fg[:, 2] >= 1) & (fg[:, 3] < 1900)
    im = ax.scatter(fg[m, 0], fg[m, 1], c=np.maximum(fg[m, 4], 0), s=10, marker='s')
    ax.plot(1422, 1512, '*', markersize=10, label='Authors’ 524 m observation location')
    ax.set_aspect('equal')
    ax.set_xlabel('Native local X (m)')
    ax.set_ylabel('Native local Y (m)')
    ax.set_title('Opposite slope: maximum water depth monitored each step\nThis plot is not a calibrated historical prediction', fontsize=11)
    ax.legend(fontsize=8)
    fig.colorbar(im, ax=ax, label='Maximum water depth above the ground (m)')
    fig.savefig(dest / 'opposite_slope_max_depth.png', dpi=160)
    plt.close(fig)
    return dest
