import numpy as np
import pytest
from simulation.numerics import integrator, cell_average, write_tt3, read_tt3, write_dtt3, read_dtt3, smoothstep, shifted_thickness

def test_integrals_preserve_constants():
    x = np.arange(-5.0, 6.0)
    edges = np.linspace(-4.9, 4.7, 23)
    w = integrator(x, edges)
    assert np.allclose(w @ np.ones(len(x)), 1, atol=1e-14)

def test_linear_function_integrated_exactly():
    x = np.arange(-5.0, 6.0)
    edges = np.array([-4.4, -2.7, 0.6, 3.1, 4.2])
    w = integrator(x, edges)
    assert np.allclose(w @ x, (edges[:-1] + edges[1:]) / 2, atol=1e-14)

def test_bilinear_field_integrated_exactly():
    x = np.arange(6.0)
    y = np.arange(8.0)
    xx, yy = np.meshgrid(x, y)
    z = 3 + 4 * xx + 2 * yy + 5 * xx * yy
    xe = np.array([0.2, 2.1, 4.6])
    ye = np.array([0.3, 3.4, 6.7])
    xc = (xe[:-1] + xe[1:]) / 2
    yc = (ye[:-1] + ye[1:]) / 2
    xx, yy = np.meshgrid(xc, yc)
    assert np.allclose(cell_average(z, x, y, xe, ye), 3 + 4 * xx + 2 * yy + 5 * xx * yy)

def test_no_extrapolated_integral():
    with pytest.raises(ValueError):
        integrator(np.arange(3.0), [-1, 1])

def test_tt3_orientation(tmp_path):
    x = np.arange(3.0) * 15
    y = np.arange(4.0) * 15
    z = np.arange(12.0).reshape(4, 3)
    p = tmp_path / 'z.tt3'
    write_tt3(p, x, y, z)
    assert np.allclose(np.loadtxt(p, skiprows=6)[0], z[-1])
    xx, yy, b = read_tt3(p)
    assert np.array_equal(z, b)

def test_no_silent_nodata(tmp_path):
    with pytest.raises(ValueError):
        write_tt3(tmp_path / 'z', np.arange(3.0), np.arange(3.0), np.full((3, 3), np.nan))

def test_dtopo_time_and_orientation(tmp_path):
    x = np.arange(3.0) * 15
    y = np.arange(4.0) * 15
    t = np.arange(3.0) * 0.25
    z = np.arange(36.0).reshape(3, 4, 3)
    p = tmp_path / 'z.dtt3'
    write_dtt3(p, x, y, t, z)
    xx, yy, tt, b = read_dtt3(p)
    assert np.array_equal(z, b)
    assert np.array_equal(t, tt)

def test_motion_starts_and_stops_at_rest():
    assert smoothstep(-1) == 0
    assert smoothstep(2) == 1
    assert (smoothstep(1e-05) - smoothstep(0)) / 1e-05 < 1e-06
    assert (smoothstep(1) - smoothstep(1 - 1e-05)) / 1e-05 < 1e-06

def test_translation_preserves_volume():
    s = np.zeros((100, 10))
    s[70:80, 3:7] = np.arange(40).reshape(10, 4) + 1
    cfg = {'travel_negative_y_m': 200.0, 'start_time_s': 0.0, 'travel_duration_s': 30.0}
    for t in np.linspace(0, 30, 31):
        assert np.isclose(shifted_thickness(s, t, cfg, 15).sum(), s.sum(), atol=1e-09)
