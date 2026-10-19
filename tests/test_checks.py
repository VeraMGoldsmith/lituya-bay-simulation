import numpy as np, pytest
from simulation.common import ROOT, load
from simulation.validate import negative_depth_issues

def make(h, bed=2, momentum=0):
    q = np.zeros((1, 1, 4))
    q[0, 0] = [h, momentum, 0, h + bed]
    return q

@pytest.mark.parametrize('h,bed,mom,violates', [(-2e-07, 2.0, 0.0, False), (-2e-07, -2.0, 0.0, True), (-2e-07, 2.0, 0.0001, True), (-2e-06, 2.0, 0.0, True), (0.0, 2.0, 0.0, False), (-1e-11, 2.0, 0.0, False)])
def test_dry_negative_tolerance_is_constrained(h, bed, mom, violates):
    c = load(ROOT / 'config.json')['checks']
    bad, records = negative_depth_issues(make(h, bed, mom), c, [1], [2], 3)
    assert bad.any() == violates
    if h < -c['negative_depth_limit_m']:
        assert records[0]['x_m'] == 1 and records[0]['y_m'] == 2 and (records[0]['t_s'] == 3)

def test_snapshot_times_include_end():
    from geoclaw.setrun import output_times
    c = load(ROOT / 'config.json')
    for case in ['still', 'slide']:
        t = output_times(c, case)
        assert t[0] == 0 and t[-1] == 420 and np.all(np.diff(t) > 0)

def test_snapshot_reader_real_fortran_exponents():
    from simulation.read_output import number
    assert number('0.1234-100') == pytest.approx(1.234e-101, abs=1e-115)
    assert number('1.25D+02') == 125

def test_no_simulation_images_before_validation(tmp_path):
    from simulation.common import save
    from reporting.plots import results
    save(tmp_path / 'status.json', {'status': 'failed'})
    save(tmp_path / 'inputs/config.json', {})
    save(tmp_path / 'inputs/setup.json', {})
    with pytest.raises(ValueError, match='No wave plots'):
        results(tmp_path)
