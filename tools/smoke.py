"""Build-time test of the ACTUAL executable on a tiny synthetic water pool.
This fixture is not Lituya terrain or a claimed landslide/1958 result.
"""
import sys, os, json, tempfile, argparse, time, subprocess
from pathlib import Path
import numpy as np
from simulation.common import ROOT, load, save
from simulation.numerics import write_tt3, write_dtt3
from simulation.read_output import read_frame, frame_numbers
from geoclaw.setrun import write_data

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--executable', required=True, type=Path)
    p.add_argument('--report', required=True, type=Path)
    a = p.parse_args(argv)
    records = []
    with tempfile.TemporaryDirectory(prefix='franco-solver-smoke-') as work:
        work = Path(work)
        inp = work / 'inputs'
        inp.mkdir()
        c = load(ROOT / 'config.json')
        c['run'].update(duration_s=2.0, still_output_interval_s=1.0, early_output_until_s=2.0, early_output_interval_s=1.0)
        c['source']['maximum_solver_step_during_motion_s'] = 0.05
        x = y = np.arange(-120.0, 121.0, 10.0)
        xx, yy = np.meshgrid(x, y)
        z = np.full(xx.shape, -20.0)
        write_tt3(inp / 'terrain.tt3', x, y, z)
        sx = sy = np.arange(-60.0, 61.0, 10.0)
        xx, yy = np.meshgrid(sx, sy)
        r2 = (xx / 40.0) ** 2 + (yy / 40.0) ** 2
        shape = np.where(r2 < 1, 0.1 * (1 - r2) ** 2, 0.0)
        t = np.arange(0, 1.001, 0.25)
        write_dtt3(inp / 'slide.dtt3', sx, sy, t, np.array([v * shape for v in t]))
        setup = dict(domain_xyxy_m=[-100.0, -100.0, 100.0, 100.0], nx=20, ny=20, gauges=[], synthetic_smoke_test=True)
        for case in ['still', 'slide']:
            folder = work / case
            write_data(folder, inp, c, setup, case)
            start = time.monotonic()
            r = subprocess.run([str(a.executable.resolve())], cwd=folder, capture_output=True, text=True, timeout=120)
            if r.returncode:
                raise RuntimeError(r.stdout[-4000:] + r.stderr[-4000:])
            indices = frame_numbers(folder)
            if len(indices) != 3:
                raise ValueError('Synthetic test has wrong frame count.')
            maxeta = 0.0
            for index in indices:
                tt, pp = read_frame(folder, index)
                q = pp[0].q
                if q[:, :, 0].min() < -1e-09:
                    raise ValueError('Synthetic test has negative depth.')
                maxeta = max(maxeta, float(np.max(abs(q[:, :, 3]))))
            if abs(tt - 2) > 1e-08:
                raise ValueError('Synthetic test did not finish.')
            if case == 'still' and maxeta > 1e-05:
                raise ValueError('Synthetic resting pool failed.')
            if case == 'slide' and maxeta < 0.0001:
                raise ValueError('Moving-bed signal was not applied.')
            records.append(dict(case=case, max_eta_m=maxeta, solver_wall_seconds_measured=time.monotonic() - start))
    save(a.report, dict(status='passed', fixture='synthetic flat-water/moving-bed software test, NOT Lituya', cases=records))
if __name__ == '__main__':
    main()
