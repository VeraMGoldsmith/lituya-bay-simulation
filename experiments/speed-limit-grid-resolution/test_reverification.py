"""Focused gaps: real deck writer, direct metric fixture, plot data and scratch isolation.

No private data or solver execution. Requires the existing NumPy/Clawpack/Matplotlib
environment (the pinned runtime supplies these). Missing software is an error, not a skip.
"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import experiment as e
import report
import reverify as v


class ReverificationTests(unittest.TestCase):
    def test_area_roundoff_is_distinct_from_a_changed_result(self):
        row = dict(unit='km²', difference='0.1000000000000000344', percent_difference='10.00000000000000344')
        v.check_comparison(row, 1., 1.1)
        for change in ('0.10000001', '0.11'):
            with self.subTest(change=change), self.assertRaises(ValueError):
                v.check_comparison(dict(row, difference=change), 1., 1.1)
        with self.assertRaises(ValueError):
            v.check_comparison(dict(row, unit='m'), 1., 1.1)

    def test_real_generated_decks_propagate_all_six_cap_grid_and_time_settings(self):
        data = e.load(e.HERE/'results.json'); p = e.protocol()
        base = e.load(e.ROOT/'release/frozen_baseline_config.json')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); inputs = root/'inputs'; inputs.mkdir()
            for grid in ('original', 'fine'):
                canonical = []
                for cap in (50, 100, 200):
                    name = f'{grid}_{cap:03d}'; folder = root/name
                    cfg = e.config_for(base, name, p)
                    e.decks(folder, inputs, cfg, data['preflights'][grid], p)
                    claw = v.deck_values(folder/'claw.data')
                    geo = v.deck_values(folder/'geoclaw.data')
                    dtopo = v.deck_values(folder/'dtopo.data')
                    self.assertEqual([int(x) for x in claw['num_cells']], p['grids'][grid])
                    self.assertEqual(float(geo['speed_limit'][0]), cap)
                    for key, expected in [('dt_initial', .02), ('dt_max', .1), ('cfl_desired', .5), ('cfl_max', 1.), ('steps_max', 200000)]:
                        self.assertEqual(float(claw[key][0]), expected)
                    self.assertEqual(float(dtopo['dt_max_dtopo'][0]), .1)
                    self.assertEqual(float(claw['output_times'][-1]), 420.)
                    canonical.append(e.normalized_decks(folder))
                self.assertEqual(canonical[0], canonical[1]); self.assertEqual(canonical[1], canonical[2])

    def test_actual_writer_rejects_invalid_cap(self):
        data = e.load(e.HERE/'results.json')
        with tempfile.TemporaryDirectory() as tmp:
            for cap in (-1, float('nan'), float('inf')):
                cfg = e.config_for(e.load(e.ROOT/'release/frozen_baseline_config.json'), 'original_100', e.protocol())
                cfg['numerics']['water_speed_limit_m_s'] = cap
                with self.subTest(cap=cap), self.assertRaises(ValueError):
                    e.decks(Path(tmp)/'deck', Path(tmp), cfg, data['preflights']['original'], e.protocol())

    def fixture(self):
        return np.array([[1,.5,1,5,.1,1,0], [3,.5,1,20,3,1,0], [5,.5,1,999,50,1,0],
                         [1,1.5,1,-1,70,1,0], [3,1.5,1,40,.09,1,0], [5,1.5,1,30,1,1,0]])

    def test_production_metrics_hand_checkable_land_and_gauges(self):
        mask = np.array([[False,False,True],[False,False,False]])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            np.savez(root/'terrain_arrays.npz', xe=[0,2,4,6], ye=[0,1,2])
            np.savetxt(root/'fgmax0002.txt', self.fixture())
            gauges = []
            for i, label in enumerate(('P2','P3','P5'), 1):
                gauges.append(dict(id=i,label=label))
                np.savetxt(root/f'gauge{i:05d}.txt', [[1,0,100,0,0,6],[1,1,2,0,0,8],[1,2,0,0,0,100]])
            config = dict(geometry=dict(include_published_virtual_wall=True), checks=dict(runup_depth_threshold_m=.1), water=dict(dry_tolerance_m=1e-6))
            setup = dict(domain_xyxy_m=[0,0,6,2], nx=3, ny=2, gauges=gauges)
            valid = dict(runup_primary=dict(maximum_wetted_cell_elevation_m=30., peak_locations=[], peak_touches_monitor_boundary=False), opposite_SW_slope_max_wetted_cell_elevation_m=20.)
            with patch('simulation.runup_metrics.artificial_cell_mask', return_value=mask):
                metrics = e.metrics(root, root, config, setup, valid)
            self.assertEqual(metrics['wetted_eligible_cells'], 3)
            self.assertEqual(metrics['wetted_area_km2'], .000006)
            self.assertEqual(metrics['max_land_depth_m'], 3.)
            self.assertEqual(metrics['runup_expanded_m'], 30.)
            self.assertEqual(metrics['runup_legacy_m'], 20.)
            for label in ('P2','P3','P5'):
                self.assertEqual(metrics[label+'_eta_m'], 8.)
                self.assertEqual(metrics['gauges'][label]['peak_time_s'], 1.)
            direct = v.direct_land_metrics(self.fixture(), [0,2,4,6], [0,1,2], mask, .1)
            self.assertEqual(direct, dict(runup=30., wetted_cells=3, maximum_depth=3., eligible_cells=4))

    def test_independent_reducer_rejects_incomplete_invalid_and_nonfinite_data(self):
        mask = np.zeros((2,3), dtype=bool)
        for column, value in [(2,0), (3,np.nan), (4,-1), (0,100)]:
            m = self.fixture(); m[0,column] = value
            with self.subTest(column=column), self.assertRaises(ValueError):
                v.direct_land_metrics(m, [0,2,4,6], [0,1,2], mask, .1)

    def test_desired_cfl_is_not_acceptance_ceiling(self):
        from simulation.time_steps import audit
        config = dict(source=dict(start_time_s=0, travel_duration_s=0, maximum_solver_step_during_motion_s=.1), run=dict(duration_s=.1))
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for cfl, succeeds in [(.8,True), (1.01,False)]:
                (folder/'fort.amr').write_text(f'AMRCLAW: level 1 CFL = {cfl:.3f} dt = 0.1000 final t = 0.1000\n')
                if succeeds:
                    self.assertEqual(audit(folder, config, 'slide')['status'], 'passed')
                else:
                    with self.assertRaisesRegex(ValueError, 'CFL'):
                        audit(folder, config, 'slide')

    def test_scratch_does_not_link_generated_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); raw = root/'raw'; raw.mkdir()
            for name in ('fort.amr','fgmax0002.txt','gauge00001.txt','validation.json','time_step_check.json','runup_expanded_max_depth.csv'):
                (raw/name).write_text('original')
            scratch = v.isolated_outputs(raw, root/'scratch')
            self.assertEqual({p.name for p in scratch.iterdir()}, {'fort.amr','fgmax0002.txt','gauge00001.txt'})
            (scratch/'validation.json').write_text('new')
            self.assertEqual((raw/'validation.json').read_text(), 'original')

    def test_plot_uses_accepted_values_and_does_not_draw_failed_case_as_zero(self):
        import matplotlib
        matplotlib.use('Agg')
        from matplotlib.figure import Figure
        data = e.load(e.HERE/'results.json')
        data['cases']['fine_200']['status'] = 'checks_failed'
        rows, _ = report.tables(data)
        captured = []
        def inspect(fig, *args, **kwargs):
            captured.extend((list(line.get_xdata()), list(line.get_ydata())) for line in fig.axes[0].lines)
        with patch.object(Figure, 'savefig', inspect):
            report.plot(rows, Path('not_written.png'))
        self.assertEqual(len(captured), 2)
        for grid, line in zip(('original','fine'), captured):
            self.assertEqual(line[0], [50,100,200])
            expected = [r['runup_expanded_m'] for r in rows if r['grid'] == grid]
            for got, wanted in zip(line[1], expected):
                self.assertTrue(np.isnan(got)) if wanted is None else self.assertEqual(got, wanted)


if __name__ == '__main__':
    unittest.main()
