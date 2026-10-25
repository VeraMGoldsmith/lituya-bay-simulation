#!/usr/bin/env python3
"""Replay acceptance and measurements from existing outputs; never run the solver.

Run in the pinned image with repository, references, archive and session mounted
read-only. --output must be a new, separate scratch directory. See REVERIFICATION.md.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import experiment as e
import report


def equal(actual, expected, label):
    e.require(actual == expected, 'Mismatch: ' + label)


def deck_values(path):
    """Read numeric/control values without relying on column alignment."""
    values = {}
    for line in Path(path).read_text().splitlines():
        if '=:' in line:
            value, label = line.split('=:', 1)
            values[label.split()[0]] = value.strip().split()
    return values


def canonical_decks(folder, inputs):
    result = {}
    for path in sorted(folder.glob('*.data')):
        text = path.read_text()
        if path.name in ('topo.data', 'dtopo.data'):
            def replace(match):
                target = (folder / match[1]).resolve()
                e.require(target.parent == inputs.resolve(), 'Unexpected physical input path')
                return "'@INPUT/" + target.name + "'"
            text = re.sub(r"'([^']+\.(?:tt3|dtt3))'", replace, text)
        result[path.name] = text
    return result


def isolated_outputs(source, destination):
    """Only link original solver files. Validator-generated files stay in scratch."""
    destination.mkdir(parents=True, exist_ok=False)
    for pattern in ('fort.*', 'fgmax*.txt', 'gauge*.txt'):
        for path in source.glob(pattern):
            (destination / path.name).symlink_to(path.resolve())
    return destination


def direct_land_metrics(monitor, xe, ye, artificial, threshold):
    """Independent scalar reduction of validated monitor rows, including exclusions."""
    import numpy as np
    m = np.asarray(monitor)
    e.require(m.ndim == 2 and m.shape[1] == 7 and len(m) > 0 and np.isfinite(m).all(),
              'Invalid monitor data')
    e.require(np.isfinite(threshold) and threshold > 0, 'Invalid threshold')
    e.require(np.all(m[:, 2] == 1), 'Incomplete observed coverage')
    e.require(np.all(m[:, 4] >= 0), 'Negative maximum depth')
    heights, depths = [], []
    eligible = 0
    for x, y, level, bed, depth, _, __ in m:
        i = int(np.searchsorted(xe, x, side='right') - 1)
        j = int(np.searchsorted(ye, y, side='right') - 1)
        e.require(0 <= i < len(xe)-1 and 0 <= j < len(ye)-1, 'Outside grid')
        if bed > 0 and not artificial[j, i]:
            eligible += 1
            if depth >= threshold:
                heights.append(float(bed)); depths.append(float(depth))
    return dict(runup=max(heights) if heights else (0.0 if eligible else None),
                wetted_cells=len(heights), maximum_depth=max(depths) if depths else None,
                eligible_cells=eligible)


def direct_metrics(folder, inputs, config, setup):
    import numpy as np
    from simulation.runup_metrics import artificial_cell_mask
    from simulation.read_output import read_gauge
    with np.load(inputs/'terrain_arrays.npz') as f:
        terrain = {key: f[key] for key in f.files}
    mask = artificial_cell_mask(terrain, include_virtual_wall=config['geometry']['include_published_virtual_wall'])
    land = [direct_land_metrics(np.loadtxt(folder/f'fgmax{i:04d}.txt', ndmin=2),
            terrain['xe'], terrain['ye'], mask, config['checks']['runup_depth_threshold_m']) for i in (1, 2)]
    west, south, east, north = setup['domain_xyxy_m']
    # Decimal cross-check avoids silently copying the production area expression.
    area = Decimal(land[1]['wetted_cells'])*Decimal(str(east-west))*Decimal(str(north-south))
    area /= Decimal(setup['nx']*setup['ny']*1000000)
    result = dict(runup_legacy_m=land[0]['runup'], runup_expanded_m=land[1]['runup'],
                  wetted_eligible_cells=land[1]['wetted_cells'], wetted_area_km2=float(area),
                  max_land_depth_m=land[1]['maximum_depth'])
    for gauge in setup['gauges']:
        if gauge['label'] in ('P2', 'P3', 'P5'):
            rows = read_gauge(folder, gauge['id'])
            wet = [float(row[5]) for row in rows if row[2] > config['water']['dry_tolerance_m']]
            e.require(bool(wet), 'No wet gauge samples')
            result[gauge['label']+'_eta_m'] = max(wet)
    return result


def compare_metrics(actual, expected, label):
    for key, value in actual.items():
        if key == 'wetted_area_km2':
            # Only floating-point evaluation order differs; < 1e-8 m² in area.
            e.require(abs(value-float(expected[key])) < 1e-14, 'Area mismatch: '+label)
        else:
            equal(Decimal(str(value)), Decimal(str(expected[key])), label+'/'+key)


def check_comparison(row, left, right):
    """Exact stored-value arithmetic; only area evaluation-order roundoff is allowed.

    Archived area uses decimalized recorded dx/dy; direct reanalysis uses physical
    extent divided by integer cell counts. This is floating-point representation,
    not an acceptance/physical-similarity tolerance.
    """
    a, b = Decimal(str(left)), Decimal(str(right))
    delta, percent = b-a, 100*(b-a)/a
    difference_error = abs(Decimal(row['difference'])-delta)
    percent_error = abs(Decimal(row['percent_difference'])-percent)
    area = row['unit'] == 'km²'
    e.require(difference_error <= (Decimal('1e-14') if area else 0), 'Independent difference mismatch')
    e.require(percent_error <= (Decimal('1e-12') if area else 0), 'Independent percentage mismatch')
    return dict(difference_roundoff=str(difference_error), percent_roundoff=str(percent_error))


def check_refinement(session, archive, config, p):
    import numpy as np
    from simulation.numerics import cell_average
    from simulation.runup_metrics import artificial_cell_mask
    from simulation.monitoring import monitor_specs, monitor_points
    arrays = {}
    records = {}
    for grid in ('original', 'fine'):
        inputs = session/'inputs'/grid
        pre = e.load(session/f'preflight_{grid}.json')
        setup = e.load(inputs/'setup.json')
        archived_setup = e.load(archive/'inputs/setup.json')
        for key in ('domain_xyxy_m', 'source_bounds_xyxy_m'):
            equal(setup[key], archived_setup[key], grid+' physical '+key)
        for actual, original in zip(setup['gauges'], archived_setup['gauges']):
            equal({k:v for k,v in actual.items() if k != 'initial_cell_bed_m'},
                  {k:v for k,v in original.items() if k != 'initial_cell_bed_m'}, grid+' physical gauge definition')
        equal([setup['nx'], setup['ny']], p['grids'][grid], grid+' dimensions')
        for filename in ('terrain.tt3', 'slide.dtt3', 'source_arrays.npz', 'source_history.csv'):
            equal(e.sha(inputs/filename), e.sha(archive/'inputs'/filename), grid+'/'+filename)
        with np.load(inputs/'terrain_arrays.npz') as f:
            a = {key: f[key] for key in f.files}
        arrays[grid] = a
        w, s, east, n = setup['domain_xyxy_m']
        for key, expected in [('xe', np.linspace(w, east, setup['nx']+1)),
                              ('ye', np.linspace(s, n, setup['ny']+1))]:
            e.require(np.array_equal(a[key], expected), grid+'/'+key)
        bed = cell_average(a['b0'], a['x'], a['y'], a['xe'], a['ye'])
        e.require(np.array_equal(bed, a['bcell']), grid+' recomputed bed integration')
        with np.load(inputs/'source_arrays.npz') as src:
            dz = np.zeros_like(a['b0']); j, i = src['global_origin']; d = src['dz'][-1]
            dz[j:j+d.shape[0], i:i+d.shape[1]] = d
        final = cell_average(dz, a['x'], a['y'], a['xe'], a['ye'])
        e.require(np.array_equal(final, a['expected_final_dz_cells']), grid+' final source integration')
        mask = artificial_cell_mask(a, include_virtual_wall=config['geometry']['include_published_virtual_wall'])
        counts = {}
        for spec in monitor_specs(config)[0]:
            x, y = monitor_points(spec, setup, require_static=True)
            i = np.searchsorted(a['xe'], x, side='right')-1
            j = np.searchsorted(a['ye'], y, side='right')-1
            saved = pre['monitors'][spec['name']]
            equal(len(x), saved['points'], grid+' monitoring coverage')
            eligible = int(np.sum((a['bcell'][j, i] > 0) & ~mask[j, i]))
            equal(eligible, saved['eligible_natural_land_cells'], grid+' eligibility')
            equal(spec['bounds_xyxy_m'], saved['requested_bounds_xyxy_m'], grid+' monitor bounds')
            counts[spec['name']] = dict(points=len(x), eligible_natural_land_cells=eligible)
        records[grid] = dict(status='passed', dimensions=p['grids'][grid], monitors=counts)
    for key in ('x', 'y', 'base', 'b0', 's0', 'excluded', 'wall', 'geometry_weight'):
        e.require(np.array_equal(arrays['original'][key], arrays['fine'][key], equal_nan=True), 'Changed nodal '+key)
    nx, ny = p['grids']['original']
    for key in ('bcell', 'expected_final_dz_cells'):
        delta = arrays['fine'][key].reshape(ny, 2, nx, 2).mean(axis=(1, 3))-arrays['original'][key]
        error = float(np.max(np.abs(delta)))
        e.require(error <= 1e-8, 'Coarse-average preservation: '+key)
        records[key+'_maximum_coarse_average_error_m'] = error
    return records


def verify(session, archive, output):
    from simulation.time_steps import audit, STEP
    from simulation.validate import validate
    from simulation.cap_comparison import verify_monitor_deck, reset_summary
    p = e.protocol()
    base, _ = e.verify_session(session, archive, p)
    published = e.load(e.HERE/'results.json')
    collected, provenance = report.collect(session)  # Rehash every sealed run file.
    equal(collected, published, 'public records versus sealed local run evidence')
    equal(provenance['case_evidence'], e.load(e.HERE/'provenance.json')['case_evidence'], 'public case seals')
    result = dict(started_utc=datetime.now(timezone.utc).isoformat(), status='running',
                  solver_launched=False, runtime_image=p['runtime_image'], solver_sha256=p['solver_sha256'],
                  checkpoint=p['checkpoint'], source_sha256={f:e.sha(e.HERE/f) for f in
                  ('reverify.py', 'experiment.py', 'report.py', 'protocol.json')}, cases={},
                  refinement=check_refinement(session, archive, base, p))
    e.save(output/'reverification.json', result)
    inodes, fingerprints, starts = {}, set(), set()
    for name in p['stage1']+p['stage2']:
        print('Rechecking '+name, flush=True)
        try:
            grid, cap = e.case_parts(name, p)
            raw = session/'cases'/name; inputs = session/'inputs'/grid
            setup = e.load(inputs/'setup.json'); config = e.load(raw/'config.json')
            record = e.load(raw/'record.json')
            equal(config, e.config_for(base, name, p), name+' physical/config settings')
            equal(record['case'], name, 'case identity'); equal(record['cap_m_s'], cap, 'cap identity')
            e.require(record['solver_exit_code'] == 0, 'Nonzero recorded solver exit')
            claim = e.load(raw/'claim.json')
            e.require(claim['started_utc'] <= record['started_utc'] < record['completed_utc'], 'Execution times')
            e.require(record['started_utc'] not in starts, 'Duplicate execution start'); starts.add(record['started_utc'])
            regenerated = output/'decks'/name
            e.decks(regenerated, inputs, config, setup, p)
            equal(canonical_decks(regenerated, inputs), canonical_decks(raw, inputs), name+' actual executed decks')
            monitor_deck = verify_monitor_deck(raw, config, setup)
            hashes = {f:h for f,h in record['files_sha256'].items() if f.startswith(('fort.q', 'gauge', 'fgmax')) or f == 'fort.amr'}
            fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
            e.require(fingerprint not in fingerprints, 'Duplicate complete-run fingerprint'); fingerprints.add(fingerprint)
            for filename in hashes:
                path = raw/filename
                e.require(not path.is_symlink(), 'Unexpected raw-output symlink')
                st = path.stat(); inode = (st.st_dev, st.st_ino)
                e.require(inode not in inodes, 'Raw-output file shared across cases')
                inodes[inode] = name+'/'+filename
            scratch = isolated_outputs(raw, output/'cases'/name)
            time_check = audit(scratch, config, 'slide')
            policy = e.policy_trace((raw/'fort.amr').read_text(), p['time_policy']['dt_max_s'])
            validation = validate(scratch, 'slide', config, setup, inputs, baseline=None)
            equal(time_check, e.load(raw/'time_step_check.json'), name+' time audit')
            equal(policy, e.load(raw/'policy_check.json'), name+' policy audit')
            equal(validation, record['field_validation'], name+' field/monitor audit')
            measured = e.metrics(scratch, inputs, config, setup, validation)
            equal(measured, record['metrics'], name+' full recorded metrics')
            independent = direct_metrics(scratch, inputs, config, setup)
            compare_metrics(independent, measured, name)
            limiter = reset_summary(raw)
            equal(limiter, record['limiter'], name+' limiter diagnostic')
            cfl = max(float(m[2].replace('D', 'E')) for m in STEP.finditer((raw/'fort.amr').read_text()))
            result['cases'][name] = dict(status='passed', configuration='regenerated decks match executed files',
                checks={key:'passed' for key in ('CFL/time_steps', 'declared_global_step', 'fields', 'monitor_coverage', 'input_consistency', 'metrics', 'run_identity')},
                frames=validation['frames_read'], last_time_s=time_check['last_time_s'], maximum_printed_cfl=cfl,
                desired_cfl=p['time_policy']['cfl_desired'], acceptance_cfl_ceiling=p['time_policy']['cfl_max'],
                maximum_printed_dt_s=policy['maximum_printed_dt_s'], metrics=measured,
                raw_run_fingerprint_sha256=fingerprint, sealed_file_count=len(record['files_sha256']),
                limiter=limiter)
        except (ValueError, KeyError, OSError, AssertionError) as exc:
            result['cases'][name] = dict(status='failed', error=str(exc))
        e.save(output/'reverification.json', result)
        print(name+': '+result['cases'][name]['status'], flush=True)
    # Independently check the archived policy comparison and the failed exclusion.
    archive_seals = e.load(e.BASE/'provenance.json')['experiment_file_sha256']
    archive_files = {}
    for case in ('cap_100', 'cap_200'):
        for path in (archive/'cases'/case).iterdir():
            if path.name.startswith(('fgmax', 'gauge')) or path.name in ('fort.amr', 'config.json'):
                relative = str(path.relative_to(archive))
                digest = e.sha(path)
                equal(digest, archive_seals[p['archived_session']+'/'+relative], 'archived evidence '+relative)
                archive_files[relative] = digest
    result['archived_evidence_sha256'] = archive_files
    cfg = e.load(archive/'cases/cap_100/config.json') if (archive/'cases/cap_100/config.json').exists() else base
    setup = e.load(archive/'inputs/setup.json')
    old = isolated_outputs(archive/'cases/cap_100', output/'archive_100')
    audit(old, cfg, 'slide')
    from simulation.monitoring import read_monitors
    read_monitors(old, archive/'inputs', cfg, setup)
    baseline = direct_metrics(old, archive/'inputs', cfg, setup)
    compare_metrics({k:baseline[k] for k,_,_ in report.METRICS}, published['archived_100_metrics'], 'archived 100')
    result['archived_100'] = dict(status='passed', metrics=baseline)
    bad = isolated_outputs(archive/'cases/cap_200', output/'archive_200')
    try:
        audit(bad, base, 'slide')
    except ValueError:
        failed = e.load(bad/'time_step_check.json')
        e.require(any('CFL' in error for error in failed['errors']), 'Expected archived CFL failure absent')
        result['archived_200'] = dict(status='excluded', rechecked_time_audit=failed)
    else:
        raise ValueError('Archived 200 unexpectedly passes its recorded failed audit')
    e.require(all(r['status'] == 'passed' for r in result['cases'].values()), 'One or more rechecks failed; see partial record')
    rows, comparisons = report.tables(published)
    lookup = {name:r['metrics'] for name,r in result['cases'].items()}
    lookup['archived_100'] = baseline
    keys = {quantity:key for key,quantity,_ in report.METRICS}
    arithmetic_checks = []
    for row in comparisons:
        key = keys[row['quantity']]
        arithmetic_checks.append(check_comparison(row, lookup[row['from_case']][key], lookup[row['to_case']][key]))
    result['pairwise_comparisons_verified'] = len(comparisons)
    result['independent_area_roundoff'] = dict(
        maximum_difference_km2=str(max(Decimal(r['difference_roundoff']) for r in arithmetic_checks)),
        maximum_percentage_points=str(max(Decimal(r['percent_roundoff']) for r in arithmetic_checks)),
        note='Only independent area conversion permits 1e-14 km² / 1e-12 percentage-point arithmetic roundoff. Other metric comparisons are exact; simulation acceptance limits are unchanged.')
    # Regenerate public reports in scratch with the current generator, preserving originals.
    regenerated = output/'public'; regenerated.mkdir()
    report.render(published, regenerated)
    generated = ('results.csv', 'comparisons.csv', 'case_status.csv', 'report.md', 'report.html', 'runup_vs_speed_limit.png')
    for filename in generated:
        equal(e.sha(regenerated/filename), e.sha(e.HERE/filename), 'regenerated '+filename)
    result['regenerated_files_identical'] = {f:e.sha(regenerated/f) for f in generated}
    result['html_visual_review'] = 'Not performed: local-file browser navigation denied by browser URL policy; structural/data checks are separate.'
    result['limitations'] = ['Hashes and consistent execution evidence detect no mixing; solver speed limit is recorded in sealed geoclaw.data, not separately echoed by fort.geo.',
        'Field validity is checked at all saved frames; this is not an audit of every unsaved field state.',
        'Gauge outputs end near 419.9 s and pass the existing coverage tolerance; no exact 420 s gauge sample is invented.',
        'No historical accuracy, grid convergence, optimal speed limit or independent solver reproduction is established.']
    result.update(status='passed', completed_utc=datetime.now(timezone.utc).isoformat())
    e.save(output/'reverification.json', result)
    print('All six run audits, archived comparison, 56 metric comparisons and regenerated artifacts agree.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    for protected in (args.session.resolve(), args.archive.resolve(), e.ROOT.resolve()):
        e.require(not out.is_relative_to(protected), 'Scratch output must be outside protected inputs/repository')
    out.mkdir(parents=True, exist_ok=False)
    verify(args.session.resolve(), args.archive.resolve(), out)


if __name__ == '__main__':
    main()
