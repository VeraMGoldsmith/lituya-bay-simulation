"""Unit fixtures are synthetic unless explicitly named reconstructed geometry."""
import os
os.environ['MPLBACKEND'] = 'Agg'
os.environ['MPLCONFIGDIR'] = '/tmp/lituya-test-matplotlib'
# Measure the optional triangle sampler's Python body rather than excluding JIT code.
os.environ['NUMBA_DISABLE_JIT'] = '1'

from pathlib import Path
import copy
import numpy as np
import pytest

from simulation.common import ROOT, load, save


@pytest.fixture
def config():
    return load(ROOT / 'config.json')


@pytest.fixture(scope='session')
def prepared_inputs(tmp_path_factory):
    from simulation.prepare import prepare
    path = tmp_path_factory.mktemp('reconstructed_inputs')
    cfg = load(ROOT / 'config.json')
    setup, checks = prepare(cfg, path)
    return path, cfg, setup, checks


def write_frame(folder, index, time, q, xlower=0., ylower=0., dx=1., dy=1.):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    ny, nx, _ = q.shape
    (folder / f'fort.t{index:04d}').write_text(f'{time} time\n4 meqn\n1 ngrids\n0 maux\n2 ndim\n0 nghost\nascii\n')
    with (folder / f'fort.q{index:04d}').open('w') as f:
        f.write(f'1 grid\n1 level\n{nx} nx\n{ny} ny\n{xlower} xlower\n{ylower} ylower\n{dx} dx\n{dy} dy\n')
        np.savetxt(f, q.reshape(-1, 4), fmt='%.15e')


@pytest.fixture
def model_factory(tmp_path, config):
    """Small ASCII fixtures for checking readers/validators, NOT water solutions."""
    def make(case='slide'):
        cfg = copy.deepcopy(config)
        cfg['run'].update(duration_s=4., early_output_until_s=4., early_output_interval_s=2., still_output_interval_s=2.)
        cfg['source']['travel_duration_s'] = 1.
        folder = tmp_path / case
        inputs = tmp_path / ('inputs_' + case)
        inputs.mkdir(exist_ok=True)
        bed = np.array([[-2., -2., 2.], [-2., -2., 2.]])
        xe, ye = np.arange(4.), np.arange(3.)
        np.savez(inputs / 'terrain_arrays.npz', x=xe, y=ye, xe=xe, ye=ye, excluded=np.zeros((3,4),bool), wall=np.zeros((3,4),bool), bcell=bed, expected_final_dz_cells=np.zeros_like(bed))
        cfg['diagnostics'] = {'runup_monitors':[{'name':'legacy', 'fgno':1, 'bounds_xyxy_m':[0.,0.,3.,2.]}], 'primary_runup_monitor':'legacy'}
        setup = {'nx': 3, 'ny': 2, 'domain_xyxy_m': [0., 0., 3., 2.],
                 'source_bounds_xyxy_m': [10., 10., 20., 20.], 'source_stop_s': 1.,
                 'gauges': [{'id': 1, 'label': 'P2', 'required_initially_wet': True}],
                 'terrain_file_sha256': 'unit-terrain'}
        for index, time in enumerate([0., 2., 4.]):
            h = np.maximum(0., -bed)
            if case == 'slide' and index > 0:
                h = h + .2 * (bed < 0)
            q = np.stack([h, np.zeros_like(h), np.zeros_like(h), h + bed], axis=-1)
            write_frame(folder, index, time, q)
        gauge = np.array([[1, 0, 2, 0, 0, 0], [1, 2, 2.2, 0, 0, .2], [1, 4, 2.2, 0, 0, .2]])
        np.savetxt(folder / 'gauge00001.txt', gauge)
        monitor = np.array([[i+.5, j+.5, 1, bed[j,i], (2.2 if i<2 else (.2 if j==0 else .05)), 4., (2. if j==0 else -1.)] for j in range(2) for i in range(3)])
        np.savetxt(folder / 'fgmax0001.txt', monitor)
        return folder, inputs, cfg, setup
    return make


def pytest_addoption(parser):
    parser.addoption('--with-reference-data', action='store_true',
                     help='Verify the private input hashes and include reconstruction-dependent tests.')


def pytest_configure(config):
    if config.getoption('--with-reference-data'):
        from simulation.common import sha
        required = load(ROOT / 'required_private_inputs.json')
        problems = []
        for name, expected in required.items():
            path = ROOT / name
            if not path.is_file():
                problems.append(name + ': missing')
            elif sha(path) != expected:
                problems.append(name + ': checksum mismatch')
        if problems:
            raise pytest.UsageError('Reference-data checks require the exact reviewed inputs. '
                                   'See docs/DATA.md.\n' + '\n'.join(problems))


def pytest_collection_modifyitems(config, items):
    if not config.getoption('--with-reference-data'):
        skipped = pytest.mark.skip(reason='Requires separately supplied reference data; see docs/DATA.md.')
        for item in items:
            if item.get_closest_marker('reference_data'):
                item.add_marker(skipped)
