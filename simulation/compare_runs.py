"""Summarize completed runs without changing, calibrating, or launching a model.

Only runs with identical source files and water settings are comparable here.
Different grid sizes are labelled resolution comparisons, not geometry evidence.
"""
from pathlib import Path
import argparse, csv
from .common import ROOT, load

def compare(folders, destination):
    records = []
    sources = set()
    water = set()
    dimensions = set()
    for folder in folders:
        folder = Path(folder)
        if not folder.is_dir():
            raise ValueError(f'Run directory not found: {folder}')
        status = load(folder / 'status.json')
        if status.get('status') != 'completed_basic_checks':
            raise ValueError(f'Not a completed numerical run: {folder.name}')
        c = load(folder / 'inputs/config.json')
        s = load(folder / 'inputs/setup.json')
        v = load(folder / 'slide/validation.json')
        if v.get('status') != 'passed_basic_checks':
            raise ValueError('Missing passed run validation.')
        sources.add(s['source_file_sha256'])
        water.add(tuple(sorted(c['water'].items())))
        dimensions.add((s['nx'], s['ny']))
        records.append(dict(run=folder.name, grid_nx=s['nx'], grid_ny=s['ny'], sw_relief_factor=c['geometry']['sw_relief_factor'], source_sha256=s['source_file_sha256'], opposite_slope_wetted_ground_m=v['opposite_SW_slope_max_wetted_cell_elevation_m'], maximum_eta_outside_source_m=v['maximum_wave_outside_source_m'], historically_calibrated=False))
    if not records:
        raise ValueError('Give at least one completed run directory.')
    if len(sources) != 1 or len(water) != 1:
        raise ValueError('Source or water settings changed: these are not geometry-only comparisons.')
    for r in records:
        r['comparison_type'] = 'resolution_and_or_geometry' if len(dimensions) > 1 else 'fixed_grid_geometry_candidates'
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(records[0]))
        w.writeheader()
        w.writerows(records)
    return records
if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('runs', nargs='+', type=Path)
    p.add_argument('--output', type=Path, default=ROOT / 'results/comparison.csv')
    a = p.parse_args()
    compare(a.runs, a.output)
    print(a.output)
