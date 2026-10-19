"""Synthetic fixtures test diagnostics, never stand in for a water simulation."""
import copy
import numpy as np
import pytest
from simulation.runup_metrics import artificial_cell_mask, measure_runup


def terrain():
    return dict(x=np.arange(4.), y=np.arange(4.), xe=np.arange(4.), ye=np.arange(4.),
                excluded=np.zeros((4, 4), dtype=bool), wall=np.zeros((4, 4), dtype=bool))


def monitor():
    x, y = np.meshgrid(np.arange(3.)+.5, np.arange(3.)+.5)
    m = np.column_stack([x.ravel(), y.ravel(), np.ones(9), np.full(9, 100.),
                         np.full(9, .2), np.full(9, 10.), np.full(9, 5.)])
    m[4, 3] = 400.
    return m


def measure(m=None, mask=None, **kw):
    return measure_runup(monitor() if m is None else m, np.arange(4.), np.arange(4.),
                         np.zeros((3, 3), dtype=bool) if mask is None else mask, **kw)


def test_interior_peak_and_permuted_rows():
    a = measure(); b = measure(monitor()[::-1])
    assert a == b
    assert a['maximum_wetted_cell_elevation_m'] == 400.
    assert a['peak_locations'][0]['x_m'] == 1.5
    assert not a['peak_touches_monitor_boundary']
    assert a['metric_scope'] == 'provided_monitor_only'
    assert not a['historically_validated']


def test_partial_artificial_overlap_not_elevation_threshold():
    a = terrain(); a['excluded'][1, 1] = True
    mask = artificial_cell_mask(a)
    assert mask.sum() == 4  # All four adjoining bilinear cell integrals are positive.
    m = monitor(); m[4, 3] = 1900.  # Would pass the old <1999 elevation-only rule.
    result = measure(m, mask)
    assert result['maximum_wetted_cell_elevation_m'] == 100.
    assert result['wetted_artificial_monitor_cells'] == 4


def test_virtual_wall_only_excluded_when_enabled():
    a = terrain(); a['wall'][1, 1] = True
    assert artificial_cell_mask(a).sum() == 4
    assert not artificial_cell_mask(a, include_virtual_wall=False).any()


def test_all_tied_peaks_retained_and_any_boundary_flagged():
    m = monitor(); m[3, 3] = 400.
    result = measure(m)
    assert len(result['peak_locations']) == 2
    assert result['peak_touches_monitor_boundary']


def test_no_wetting_is_zero_but_no_observations_is_unknown():
    m = monitor(); m[:, 4] = 0
    assert measure(m)['maximum_wetted_cell_elevation_m'] == 0
    m[:, 2] = 0; m[:, 4:] = -9.9999e98
    result = measure(m)
    assert result['maximum_wetted_cell_elevation_m'] is None
    assert not result['all_points_observed']
    assert not result['peak_locations']


def test_masked_all_land_does_not_claim_zero_runup():
    assert measure(mask=np.ones((3, 3), dtype=bool))['maximum_wetted_cell_elevation_m'] is None


def test_threshold_and_seabed():
    m = monitor(); m[4, 4] = .05; m[0, 3] = -10
    assert measure(m)['maximum_wetted_cell_elevation_m'] == 100.
    assert measure(m, depth_threshold_m=.01)['maximum_wetted_cell_elevation_m'] == 400.


def test_ascii_coordinate_rounding_allowed():
    m = monitor(); m[:, :2] += 1e-6
    assert measure(m)['maximum_wetted_cell_elevation_m'] == 400.


@pytest.mark.parametrize('bad', [0, -1, np.nan, np.inf])
def test_invalid_depth_threshold(bad):
    with pytest.raises(ValueError, match='threshold'): measure(depth_threshold_m=bad)


@pytest.mark.parametrize('kind', ['columns','empty','nan','outside','offcentre','duplicate','missing','level','negative_depth'])
def test_bad_monitors_fail_closed(kind):
    m = monitor()
    if kind=='columns': m=m[:, :6]
    elif kind=='empty': m=m[:0]
    elif kind=='nan': m[0, 4]=np.nan
    elif kind=='outside': m[0, 0]=-1.
    elif kind=='offcentre': m[0, 0]=.6
    elif kind=='duplicate': m[0]=m[1]
    elif kind=='missing': m=np.delete(m, 4, axis=0)
    elif kind=='level': m[0, 2]=2
    elif kind=='negative_depth': m[0, 4]=-1
    with pytest.raises(ValueError): measure(m)


@pytest.mark.parametrize('kind', ['missing','shape','binary','axis','coverage'])
def test_bad_terrain_fails_closed(kind):
    a=terrain()
    if kind=='missing': del a['excluded']
    elif kind=='shape': a['wall']=a['wall'][:2]
    elif kind=='binary': a['excluded']=np.full((4, 4), np.nan)
    elif kind=='axis': a['x'][1]=a['x'][0]
    elif kind=='coverage': a['xe'][0]=-1
    with pytest.raises(ValueError): artificial_cell_mask(a)


@pytest.mark.parametrize('mask', [np.zeros((2, 2), dtype=bool), np.zeros((3, 3))])
def test_wrong_cell_mask_rejected(mask):
    with pytest.raises(ValueError, match='boolean'): measure(mask=mask)


def test_inputs_are_not_modified():
    a=terrain(); before=copy.deepcopy(a); m=monitor(); saved=m.copy()
    mask=artificial_cell_mask(a); measure(m, mask)
    for k in a: np.testing.assert_array_equal(a[k], before[k])
    np.testing.assert_array_equal(m, saved)
