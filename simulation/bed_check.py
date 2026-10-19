"""Check a final bed without confusing a step-start auxiliary value with t_out.

GeoClaw 5.14 updates bed auxiliaries at the beginning of an integration step.
At the stopping instant, the saved bed can therefore precede the final source
sample by one bounded step. Fit ONE interpolation phase for the entire grid;
do not independently excuse errors in individual cells. Later frames must match
the final bed under the original spatial error limit.
"""
from pathlib import Path
import numpy as np
from .numerics import cell_average

# tick.f may enlarge the last step by at most 0.1% to land on an output time.
OUTPUT_STEP_FACTOR = 1.001
TIME_EPS = 1.e-8


def transition_basis(inputs, terrain, expected):
    """Cell-integrated difference of the final two prescribed dtopo samples."""
    with np.load(Path(inputs) / 'source_arrays.npz', allow_pickle=False) as source:
        times = source['times']
        if len(times) < 2 or not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
            raise ValueError('Invalid source sampling times for bed timing check.')
        interval = float(times[-1] - times[-2])
        j, i = map(int, source['global_origin'])
        dz = source['dz']
        if dz.shape[0] != len(times) or not np.isfinite(dz[-2:]).all():
            raise ValueError('Invalid final source samples.')
        ny, nx = dz.shape[1:]
        shape = (len(terrain['y']), len(terrain['x']))
        if min(i, j) < 0 or j + ny > shape[0] or i + nx > shape[1]:
            raise ValueError('Source samples lie outside the terrain grid.')
        values = []
        for z in dz[-2:]:
            full = np.zeros(shape)
            full[j:j+ny, i:i+nx] = z
            values.append(cell_average(full, terrain['x'], terrain['y'], terrain['xe'], terrain['ye']))
        if not np.allclose(values[-1], expected, atol=1.e-7, rtol=0):
            raise ValueError('Final source samples disagree with the expected bed array.')
    return values[0] - values[1], interval, float(times[-1])


def compare_transition(delta, basis, interval, stop, time, max_step):
    """Return a bounded global phase fit, not a larger vertical tolerance."""
    if (delta.shape != basis.shape or not np.isfinite(delta).all()
            or not np.isfinite(basis).all()):
        raise ValueError('Invalid bed arrays for transition comparison.')
    if not np.isfinite([interval, stop, time, max_step]).all() or min(interval, max_step) <= 0:
        raise ValueError('Invalid time controls for transition comparison.')
    allowed_step = max_step * OUTPUT_STEP_FACTOR
    if allowed_step > interval:
        raise ValueError('Bed timing check requires a source interval at least as long as one allowed solver step.')
    if time < stop - TIME_EPS or time > stop + allowed_step + TIME_EPS:
        raise ValueError('Frame is not in the one-step source-stop transition window.')
    alpha_max = max(0., min(1., (stop + allowed_step - time) / interval))
    denominator = float(np.sum(basis * basis))
    raw_alpha = float(np.sum(delta * basis) / denominator) if denominator else 0.
    alpha = float(np.clip(raw_alpha, 0., alpha_max))
    residual = float(np.max(np.abs(delta - alpha * basis)))
    return dict(output_time_s=float(time), maximum_raw_final_bed_error_m=float(np.max(abs(delta))),
                bounded_phase_fraction=alpha, bed_reference_time_s=float(stop - alpha * interval),
                allowed_step_s=float(allowed_step), comparison_residual_m=residual,
                method='single global phase within one permitted step; final two source samples')
