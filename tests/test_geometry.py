import copy
import numpy as np, pytest
from simulation.common import ROOT, load, sha
from simulation.prepare import reference_fields, prepare, validate_config

@pytest.fixture(scope='module')
def baseline(tmp_path_factory):
    p = tmp_path_factory.mktemp('prepared')
    c = load(ROOT / 'config.json')
    setup, check = prepare(c, p)
    return (c, p, setup, check)

@pytest.mark.reference_data
def test_original_source_is_dry_at_start(baseline):
    c, p, s, ch = baseline
    assert ch['initial_footprint_min_ground_m'] > 200
    assert ch['source_zero_initial_dz_max'] == 0

@pytest.mark.reference_data
def test_original_source_reaches_receiving_inlet(baseline):
    c, p, s, ch = baseline
    assert 0 < ch['source_first_wet_overlap_s'] < 30
    assert ch['source_final_volume_fraction_over_wet_bed'] > 0.95

@pytest.mark.reference_data
def test_source_volume_not_lost_or_invented(baseline):
    assert baseline[3]['source_volume_drift_relative'] < 1e-09
    assert abs(baseline[3]['volume_normalization'] - 1) < 0.001

@pytest.mark.reference_data
def test_published_gauge_positions_retained(baseline):
    points = {p['label']: p for p in baseline[2]['gauges']}
    assert points['P1']['x_m'] == 1550 and points['P1']['y_m'] == 3450
    assert points['P2']['x_m'] == 1550 and points['P2']['y_m'] == 2810
    assert points['R524']['x_m'] == 1422 and points['R524']['y_m'] == 1512

@pytest.mark.reference_data
def test_opposite_slope_change_does_not_change_source(baseline, tmp_path):
    c, p, s, ch = baseline
    cfg = copy.deepcopy(c)
    cfg['geometry']['sw_relief_factor'] = 1.1
    prepare(cfg, tmp_path)
    assert sha(p / 'slide.dtt3') == sha(tmp_path / 'slide.dtt3')
    assert sha(p / 'terrain.tt3') != sha(tmp_path / 'terrain.tt3')
    a = np.load(p / 'terrain_arrays.npz')
    b = np.load(tmp_path / 'terrain_arrays.npz')
    src = np.load(p / 'source_arrays.npz')
    j, i = src['global_origin']
    ny, nx = src['s0'].shape
    assert np.array_equal(a['b0'][j:j + ny, i:i + nx], b['b0'][j:j + ny, i:i + nx])
    assert np.array_equal(a['b0'][a['b0'] <= 0], b['b0'][a['b0'] <= 0])

@pytest.mark.reference_data
def test_resolution_keeps_same_continuous_terrain_and_source(baseline, tmp_path):
    c, p, s, ch = baseline
    cfg = copy.deepcopy(c)
    cfg['run']['target_cell_size_m'] = 15
    new, _ = prepare(cfg, tmp_path)
    assert sha(p / 'terrain.tt3') == sha(tmp_path / 'terrain.tt3')
    assert sha(p / 'slide.dtt3') == sha(tmp_path / 'slide.dtt3')
    assert new['nx'] == 454 and new['ny'] == 905

@pytest.mark.reference_data
def test_terrain_tiff_not_wrong_geographic_crs(baseline):
    import rasterio
    from simulation.numerics import read_tt3
    p = baseline[1]
    x, y, z = read_tt3(p / 'terrain.tt3')
    with rasterio.open(p / 'terrain.tif') as r:
        assert r.crs.to_epsg() is None and 'LOCAL_CS' in r.crs.to_wkt()
        assert np.allclose(r.read(1)[::-1], z, atol=1e-07)
        assert np.allclose(r.xy(0, 0), (x[0], y[-1]))

@pytest.mark.reference_data
def test_missing_active_terrain_is_not_zero_filled():
    c = load(ROOT / 'config.json')
    a, _ = reference_fields(c)
    assert np.isfinite(a['base']).all()
    missing = ~np.isfinite(a['natural'])
    assert np.all(a['excluded'][missing])
    assert np.all(a['base'][missing] == 2000)

@pytest.mark.parametrize('key,value', [('travel_duration_s', -1), ('volume_m3', -1), ('travel_x_m', 100)])
def test_bad_source_fails(key, value):
    c = load(ROOT / 'config.json')
    c['source'][key] = value
    with pytest.raises(ValueError):
        validate_config(c)

@pytest.mark.reference_data
def test_domain_clipping_is_not_allowed(tmp_path):
    c = load(ROOT / 'config.json')
    c['source']['travel_negative_y_m'] = 4000
    with pytest.raises(ValueError):
        prepare(c, tmp_path)

def test_no_unjustified_resolution_upgrade():
    c = load(ROOT / 'config.json')
    c['run']['target_cell_size_m'] = 5
    with pytest.raises(ValueError):
        validate_config(c)
