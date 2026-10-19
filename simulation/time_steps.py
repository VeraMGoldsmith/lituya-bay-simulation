"""Audit actual single-level GeoClaw time steps, not just requested settings."""
from pathlib import Path
import re
import numpy as np
from .common import save
from .bed_check import OUTPUT_STEP_FACTOR

NUMBER = r'[+\-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+\-]?\d+)?'
STEP = re.compile(r'AMRCLAW:\s*level\s+(\d+)\s+CFL\s*=\s*(' + NUMBER +
                  r')\s+dt\s*=\s*(' + NUMBER + r')\s+final t\s*=\s*(' + NUMBER + r')')


def parsed_number(token):
    value = float(token.replace('D', 'E').replace('d', 'e'))
    # Half of one last printed decimal unit: audit formatted Fortran output.
    mantissa, _, exponent = token.lower().replace('d', 'e').partition('e')
    decimals = len(mantissa.split('.')[1]) if '.' in mantissa else 0
    quantum = 10. ** (int(exponent or 0) - decimals)
    return value, quantum / 2.


def audit(folder, config, case):
    """Require a continuous step trace and enforce the declared limits.

    amrdata.tprint=True writes this trace to fort.amr, not the terminal.
    The 0.1% output-time adjustment is explicitly permitted by tick.f.
    """
    folder = Path(folder)
    trace = folder / 'fort.amr'
    errors, count, previous, previous_precision = [], 0, 0., 0.
    speed_resets = 0
    maxima = {'all_steps_s': 0., 'steps_starting_before_source_stop_s': 0.}
    stop = config['source']['start_time_s'] + config['source']['travel_duration_s']
    cap = config['source']['maximum_solver_step_during_motion_s']
    if not trace.is_file():
        errors.append('Missing fort.amr step trace. Enable amrdata.tprint; do not skip this check.')
    else:
        with trace.open() as stream:
            for line in stream:
                if 'reset s =' in line:
                    speed_resets += 1
                if 'AMRCLAW: level' not in line:
                    continue
                match = STEP.search(line)
                if match is None:
                    errors.append('Unreadable integration step in fort.amr.')
                    break
                level = int(match[1])
                cfl, _ = parsed_number(match[2])
                dt, dp = parsed_number(match[3])
                end, ep = parsed_number(match[4])
                if level != 1 or dt <= 0 or end <= previous or not np.isfinite([dt, end, cfl]).all():
                    errors.append('Invalid or non-single-level integration trace.')
                    break
                if abs(end - previous - dt) > previous_precision + ep + dp + 1.e-8:
                    errors.append('Missing or inconsistent consecutive integration steps.')
                    break
                moving = case == 'slide' and previous < stop - previous_precision - 1.e-8
                bound = cap if moving else 2.0  # matches setrun.py d.dt_max
                if dt - dp > bound * OUTPUT_STEP_FACTOR + 1.e-8:
                    errors.append(f'Actual time step {dt:g} s exceeds {bound:g} s control at t={previous:g} s.')
                if cfl > 1.001:
                    errors.append(f'Actual CFL {cfl:g} exceeds the configured maximum.')
                maxima['all_steps_s'] = max(maxima['all_steps_s'], dt)
                if moving:
                    maxima['steps_starting_before_source_stop_s'] = max(maxima['steps_starting_before_source_stop_s'], dt)
                count += 1
                previous, previous_precision = end, ep
    if count == 0 or abs(previous - config['run']['duration_s']) > previous_precision + 1.e-8:
        errors.append('Step trace does not reach the requested final time.')
    record = dict(status='passed' if not errors else 'failed', case=case, steps=count,
                  last_time_s=previous, requested_source_step_cap_s=cap,
                  output_time_step_factor=OUTPUT_STEP_FACTOR, maxima=maxima, errors=errors,
                  logged_speed_resets=speed_resets,
                  speed_limit_sensitivity_validated=False)
    save(folder / 'time_step_check.json', record)
    if errors:
        raise ValueError('\n'.join(errors[:10]))
    return record
