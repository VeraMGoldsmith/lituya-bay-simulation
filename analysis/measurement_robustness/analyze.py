#!/usr/bin/env python3
"""Reanalyse published summaries only. Standard library; no solver or raw inputs.

Run from the repository root:
    python3 -B analysis/measurement_robustness/analyze.py
"""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal, InvalidOperation, getcontext
import hashlib
from html import escape
import io
import json
from pathlib import Path
import subprocess
import sys

getcontext().prec = 28
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RECORD = "experiments/2026-10-19-speed-caps/"
RESULTS = RECORD + "results.json"
FIGURES = "docs/figures/figure_provenance.json"
MONITORS = "monitor_diagnostics_not_valid_runup_if_case_failed"
GAUGES = "gauges_diagnostic_only_if_invalid"
RUNUP = "maximum_wetted_cell_elevation_m"
CASES = ("cap_050", "cap_100")
INPUTS = (RESULTS, FIGURES, RECORD + "results.csv", RECORD + "provenance.json",
          "simulation/runup_metrics.py", "simulation/monitoring.py",
          "simulation/read_output.py", "simulation/validate.py", "simulation/numerics.py",
          "simulation/__init__.py", RECORD + "plot_figures.py", "docs/DATA.md",
          "release/frozen_baseline_config.json", "simulation/cap_comparison.py")


class RecordError(ValueError):
    """Missing, invalid or inconsistent archived evidence; never impute a result."""


def require(ok, message):
    if not ok:
        raise RecordError(message)


def number(value, name="value", *, nonnegative=False, positive=False):
    require(value is not None and not isinstance(value, bool), f"{name}: missing/invalid number")
    try:
        x = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise RecordError(f"{name}: invalid number") from None
    require(x.is_finite(), f"{name}: nonfinite number")
    require(not nonnegative or x >= 0, f"{name}: negative value")
    require(not positive or x > 0, f"{name}: must be positive")
    return x


def integer(value, name):
    x = number(value, name, nonnegative=True)
    require(x == x.to_integral_value(), f"{name}: must be an integer")
    return int(x)


def difference(a, b):
    a, b = number(a), number(b)
    delta = b - a
    # Ratios to zero/negative elevations are not meaningful here. Crossing zero
    # is also unsuitable for this simple descriptive percentage convention.
    return delta, (100 * delta / a if a > 0 and b >= 0 else None)


def area_km2(count, dx, dy):
    return (Decimal(integer(count, "wetted cell count")) * number(dx, "dx", positive=True)
            * number(dy, "dy", positive=True) / Decimal(1000000))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(), parse_float=Decimal,
                      parse_constant=lambda x: number(x, "JSON constant"))


def verify_inputs(root):
    """Check public seals; do not open private files named inside the manifests."""
    hashes = {name: sha(root / name) for name in INPUTS}
    results, figures, seal = (load(root / name) for name in
                              (RESULTS, FIGURES, RECORD + "provenance.json"))
    require(results["session"] == figures["session"] == seal["session"], "Session mismatch")
    require(hashes[RECORD + "provenance.json"] == figures["experiment_provenance_sha256"],
            "Experiment provenance hash mismatch")
    for name, expected in figures["result_files_sha256"].items():
        require(expected == seal["result_files_sha256"].get(name) == sha(root / RECORD / name),
                f"Result hash mismatch: {name}; investigate before generating comparisons")
    for name, expected in figures["reader_sha256"].items():
        require(expected == seal["sealed_code_sha256"].get(name) == sha(root / name),
                f"Measurement definition hash mismatch: {name}")
    require(hashes[RECORD + "plot_figures.py"] == figures["script_sha256"], "Plot-script hash mismatch")
    frozen = load(root / "release/frozen_baseline_config.json")
    require(frozen["diagnostics"]["runup_monitors"] == figures["simulation_settings"]["monitor_specs"],
            "Monitor definitions disagree with frozen release configuration")
    require(frozen["checks"]["runup_depth_threshold_m"] == figures["simulation_settings"]["runup_depth_threshold_m"],
            "Reporting threshold differs from frozen configuration")
    require(frozen["diagnostics"]["require_static_runup_terrain"] is True,
            "Static run-up terrain not required in frozen configuration")
    require(frozen["run"]["duration_s"] == figures["simulation_settings"]["duration_s"],
            "Duration differs from frozen configuration")
    with (root / RECORD / "results.csv").open(newline="") as f:
        published = list(csv.DictReader(f))
    require([x["case"] for x in published] == [x["case"] for x in results["summary"]["cases"]],
            "Published CSV case order/identity mismatch")
    for row, recorded in zip(published, results["summary"]["cases"]):
        for key in ("runup_legacy_m", "runup_expanded_m", "water_speed_limit_m_s"):
            require((None if row[key] == "" else number(row[key])) == recorded[key],
                    f"Published CSV disagrees: {row['case']}/{key}")
        require(row["status"] == recorded["status"], "Published CSV status mismatch")
    return results, figures, hashes


def grid_and_monitors(settings):
    require(settings["coordinates"]["system"] == "native local Cartesian metres", "Unverified coordinate units")
    require(number(settings["model_sea_level_m"]) == 0, "Unexpected model sea level")
    domain = [number(x) for x in settings["domain_xyxy_m"]]
    require(len(domain) == 4 and domain[2] > domain[0] and domain[3] > domain[1], "Invalid domain")
    nx, ny = [integer(x, "grid cells") for x in settings["grid_cells"]]
    require(nx > 0 and ny > 0, "Empty grid")
    dx, dy = [number(settings[k], k, positive=True) for k in ("dx_m", "dy_m")]
    require(abs(dx - (domain[2]-domain[0])/nx) < Decimal("1e-9") and
            abs(dy - (domain[3]-domain[1])/ny) < Decimal("1e-9"), "Grid spacing/domain mismatch")
    specs = settings["monitor_specs"]
    require(len(specs) == 2 and {s["name"] for s in specs} == {"legacy", "expanded"}, "Unexpected monitors")
    bounds = {s["name"]: [number(x) for x in s["bounds_xyxy_m"]] for s in specs}
    for name, b in bounds.items():
        require(len(b) == 4 and domain[0] <= b[0] < b[2] <= domain[2] and
                domain[1] <= b[1] < b[3] <= domain[3], f"Invalid {name} bounds")
    small, big = bounds["legacy"], bounds["expanded"]
    require(big[0] <= small[0] and big[1] <= small[1] and big[2] >= small[2] and big[3] >= small[3],
            "Legacy area is not contained in expanded area")
    return dx, dy, bounds


def threshold_bound(metric, *, lower, upper, bounds, duration, evidence_supported):
    """Conditional set-inclusion deduction from at least one surviving peak cell.

    Peak lists come from measure_runup's equality to the maximum *ground*
    elevation. A maximum water depth elsewhere cannot be used as a witness.
    Missing premises return an explicit unsupported result, not an assertion.
    """
    result = dict(status="not established from available records", reason="", peak=None)
    try:
        lo, hi = number(lower, positive=True), number(upper, positive=True)
        require(hi >= lo, "Reversed threshold interval")
        require(evidence_supported is True, "Matching case, static terrain and archived verification not established")
        require(metric.get("all_points_observed") is True and
                metric.get("metric_scope") == "provided_monitor_only", "Monitor scope/coverage not established")
        require(number(metric.get("depth_threshold_m")) == lo, "Baseline threshold mismatch")
        require(number(metric.get(RUNUP), positive=True) > 0, "No positive run-up peak")
        peaks = metric.get("peak_locations")
        require(isinstance(peaks, list) and bool(peaks), "No archived run-up-maximizing cells")
        valid = []
        for p in peaks:
            x, y = number(p.get("x_m")), number(p.get("y_m"))
            h = number(p.get("maximum_depth_m"), nonnegative=True)
            t = number(p.get("time_at_maximum_depth_s"), nonnegative=True)
            require(bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3], "Peak outside monitoring area")
            require(t <= duration and h >= lo, "Peak depth/time inconsistent with baseline")
            if h >= hi:
                valid.append(p)
        require(bool(valid), "No archived maximizing cell remains wet at the upper threshold")
        result.update(status="established from archived peak-cell information",
                      reason="At least one baseline maximum survives the entire requested interval.",
                      peak=max(valid, key=lambda p: number(p["maximum_depth_m"])))
    except (RecordError, KeyError, TypeError) as exc:
        result["reason"] = str(exc)
    return result


def compare_records(results, figures):
    require(results["session"] == figures["session"], "Session mismatch")
    settings = figures["simulation_settings"]
    dx, dy, bounds = grid_and_monitors(settings)
    duration = number(settings["duration_s"], positive=True)
    threshold = number(settings["runup_depth_threshold_m"], positive=True)
    require(threshold == Decimal("0.1"), "Expected the archived 0.1 m reporting threshold")
    rows = results["summary"]["cases"]
    require(len(rows) == 3 and {x["case"] for x in rows} == {*CASES, "cap_200"}, "Unexpected summary cases")
    summary = {x["case"]: x for x in rows}
    accepted = {k for k, v in results["cases"].items() if v.get("valid_for_comparison") is True}
    require(accepted == set(CASES), "Only accepted 50 and 100 m/s cases may be compared")
    failed = results["cases"]["cap_200"]
    require(failed.get("valid_for_comparison") is False and failed["status"] == "checks_failed" and
            failed["cap_m_s"] == summary["cap_200"]["water_speed_limit_m_s"] == 200 and
            summary["cap_200"]["status"] == "checks_failed" and
            failed["time_step_check"]["status"] == "failed" and
            any("CFL" in e for e in failed["time_step_check"]["errors"]), "Missing failed 200 m/s evidence")
    require(all(summary["cap_200"][k] is None for k in ("runup_legacy_m", "runup_expanded_m")),
            "Failed case has an accepted run-up value")
    excluded = figures["excluded_case"]
    require(excluded["case"] == "cap_200" and excluded["accepted_runup_m"] is None and
            excluded["recorded_errors"] == failed["time_step_check"]["errors"], "Exclusion records disagree")
    vals, coverage, bound_rows, peak_evidence = {}, [], [], {}
    for case, cap in zip(CASES, (50, 100)):
        c, s = results["cases"][case], summary[case]
        require(c["cap_m_s"] == s["water_speed_limit_m_s"] == cap, f"{case}: cap mismatch")
        require(c["status"] == s["status"] == "completed_basic_checks" and
                c["field_validation_status"] == "passed_basic_checks" and
                c["time_step_check"]["status"] == "passed" and not c["time_step_check"]["errors"] and
                not c["trace_statistics"]["cfl_violations"], f"{case}: failed basic checks")
        require(number(c["last_time_s"]) == number(c["time_step_check"]["last_time_s"]) == duration and
                integer(c["frames"], "frame count") > 0, f"{case}: incomplete coverage")
        vals[case] = {}
        for area in ("legacy", "expanded"):
            m, f = c[MONITORS][area], figures["runup_metrics"][case][area]
            for key in m.keys() & f.keys():
                require(m[key] == f[key], f"Cross-file discrepancy: {case}/{area}/{key}")
            r = number(s[f"runup_{area}_m"], f"{case}/{area} run-up", nonnegative=True)
            require(r == number(m[RUNUP]) == number(f[RUNUP]), f"Run-up discrepancy: {case}/{area}")
            require(m["depth_threshold_m"] == f["depth_threshold_m"] == threshold, "Threshold mismatch")
            require(m["metric_scope"] == f["metric_scope"] == "provided_monitor_only", "Wrong metric scope")
            require(m["all_points_observed"] is True and f["all_points_observed"] is True and
                    integer(m["observed_points"], "observed points") == integer(m["monitor_points"], "monitor points"),
                    "Incomplete monitoring coverage")
            eligible = integer(m["eligible_natural_land_cells"], "eligible cells")
            require(0 < eligible <= m["monitor_points"], "Invalid eligible cell count")
            require(eligible == integer(f["eligible_natural_land_cells"], "figure eligible cells"), "Eligibility disagreement")
            vals[case][area] = r
        f = figures["runup_metrics"][case]["expanded"]
        count = integer(f["wetted_eligible_cells"], "wetted cells")
        require(0 <= count <= f["eligible_natural_land_cells"], "Wetted cell count exceeds eligible cells")
        vals[case]["area"] = area_km2(count, dx, dy)
        vals[case]["depth"] = number(f["maximum_depth_on_wetted_eligible_land_m"], "maximum land depth", nonnegative=True)
        require(count > 0 and vals[case]["depth"] >= threshold, "Inconsistent wetted count/depth")
        for gauge in ("P2", "P3", "P5"):
            g = c[GAUGES][gauge]
            vals[case][gauge] = number(g["maximum_eta_m"], f"{case}/{gauge} peak eta")
            start, end, peak = (number(g[k]) for k in ("first_time_s", "last_time_s", "time_at_maximum_eta_s"))
            require(0 == start <= peak <= end <= duration and integer(g["samples"], "gauge samples") > 0,
                    f"{case}/{gauge}: invalid gauge times/count")
            coverage.append(dict(case=case, gauge=gauge, first_time_s=start, last_time_s=end,
                                 peak_time_s=peak, samples=g["samples"]))
        m = c[MONITORS]["expanded"]
        evidence = (all(figures["verification"].get(k) is True for k in
                        ("raw_monitors_remeasured", "raw_metrics_equal_recorded_metrics", "static_monitor_beds_verified", "all_hashes_match"))
                    and results["verification"].get("raw_monitors_remeasured") is True
                    and m.get("peak_locations") == f.get("peak_locations")
                    and "peak_locations" in m and "peak_locations" in f)
        bound = threshold_bound(m, lower=threshold, upper=1, bounds=bounds["expanded"],
                                duration=duration, evidence_supported=evidence)
        peak = bound["peak"]
        # All archived peaks remain in provenance even if no valid witness exists.
        # No general land-depth maximum is substituted for a run-up peak depth.
        raw_peaks = m.get("peak_locations", [])
        depth = peak["maximum_depth_m"] if peak else None
        bound_rows.append(dict(case=case, runup_m=vals[case]["expanded"],
                               peak_cell_depth_m=depth, threshold_min_m=threshold if peak else None,
                               threshold_max_m=Decimal(1) if peak else None, status=bound["status"]))
        peak_evidence[case] = dict(archived_peak_locations=raw_peaks, bound_reason=bound["reason"],
                                   premises_supported=evidence, selected_witness=peak)
    for area in ("legacy", "expanded"):
        a, b = [results["cases"][c][MONITORS][area] for c in CASES]
        for key in ("eligible_natural_land_cells", "monitor_points", "artificial_monitor_cells", "depth_threshold_m"):
            require(a[key] == b[key], f"Different measurement definitions between cases: {area}/{key}")
    require(vals[CASES[1]]["expanded"] - vals[CASES[0]]["expanded"] ==
            number(results["summary"]["setting_differences"]["R100_minus_R50_m"]), "Recorded difference mismatch")
    require(figures["presentation"]["sensitivity_displayed_cases"] == list(CASES) and
            figures["presentation"]["sensitivity_bar_heights_m"] == [vals[c]["expanded"] for c in CASES],
            "Figure sensitivity values/case order disagree with accepted measurements")
    definitions = (
        ("legacy", "Highest monitored run-up — original area", "m"),
        ("expanded", "Highest monitored run-up — expanded area", "m"),
        ("area", "Eligible natural land wetted at any time — expanded area", "km²"),
        ("depth", "Maximum water depth on eligible natural land — expanded area", "m"),
        ("P2", "Peak water-surface elevation at P2", "m"),
        ("P3", "Peak water-surface elevation at P3", "m"),
        ("P5", "Peak water-surface elevation at P5", "m"))
    comparison = []
    for key, label, unit in definitions:
        a, b = [vals[c][key] for c in CASES]
        delta, percent = difference(a, b)
        comparison.append(dict(metric=key, quantity=label, unit=unit, value_50=a, value_100=b,
                               difference=delta, percent_difference=percent))
    area_choice = []
    for case in CASES:
        a, b = vals[case]["legacy"], vals[case]["expanded"]
        require(b >= a, "Expanded maximum smaller than the nested original maximum")
        delta, percent = difference(a, b)
        area_choice.append(dict(case=case, original_runup_m=a, expanded_runup_m=b,
                                difference_m=delta, percent_difference=percent))
    return dict(comparison=comparison, monitoring_choice=area_choice, threshold_bound=bound_rows,
                peak_evidence=peak_evidence, gauge_coverage=coverage, dx_m=dx, dy_m=dy,
                cell_area_m2=dx*dy, monitor_bounds=bounds, session=results["session"], duration_s=duration,
                wetted_cells={c: figures["runup_metrics"][c]["expanded"]["wetted_eligible_cells"] for c in CASES},
                boundary_flags={c: {a: results["cases"][c][MONITORS][a]["peak_touches_monitor_boundary"]
                                    for a in ("legacy", "expanded")} for c in CASES})


TABLES = {
    "comparison": ("Recorded-quantity comparison", [
        ("quantity", "Quantity", None), ("unit", "Unit", None), ("value_50", "50 m/s", 3),
        ("value_100", "100 m/s", 3), ("difference", "100 − 50", 3), ("percent_difference", "Change (%)", 2)]),
    "monitoring_choice": ("Effect of expanding the monitoring area within each case", [
        ("case", "Case", None), ("original_runup_m", "Original (m)", 2),
        ("expanded_runup_m", "Expanded (m)", 2), ("difference_m", "Expanded − original (m)", 2),
        ("percent_difference", "Change (%)", 2)]),
    "threshold_bound": ("Threshold bound deduced from archived peak cells — not a threshold sweep", [
        ("case", "Case", None), ("runup_m", "Run-up (m)", 2), ("peak_cell_depth_m", "Depth at peak cell (m)", 6),
        ("threshold_min_m", "Threshold from (m)", 1), ("threshold_max_m", "Through (m)", 1), ("status", "Evidence", None)])}


def raw(value):
    return "" if value is None else str(value)


def display(row, key, digits):
    value = row[key]
    if value is None:
        return "Not established" if key != "percent_difference" else "Not applicable"
    if key == "case":
        return {"cap_050": "50 m/s", "cap_100": "100 m/s"}[value]
    if digits is None:
        return str(value)
    if row.get("unit") == "km²" and key != "percent_difference":
        digits = 6
    return f"{value:.{digits}f}"


def report_sections(data, starting_commit):
    r = {x["metric"]: x for x in data["comparison"]}
    area = data["monitoring_choice"]
    d = lambda k: f"{r[k]['percent_difference']:.2f}%" if r[k]['percent_difference'] is not None else "not applicable"
    supported = all(x["threshold_max_m"] == 1 for x in data["threshold_bound"])
    bounds_text = "; ".join(f"{label}: X = {b[0]}–{b[2]} m, Y = {b[1]}–{b[3]} m"
                            for label, b in (("original (legacy)", data["monitor_bounds"]["legacy"]),
                                             ("expanded", data["monitor_bounds"]["expanded"])))
    ranges = {}
    for g in data["gauge_coverage"]:
        ranges.setdefault((g["case"], g["first_time_s"], g["last_time_s"]), []).append(g["gauge"])
    gauge_text = "; ".join(f"{case} ({', '.join(gauges)}): {start}–{end} s"
                           for (case, start, end), gauges in ranges.items())
    boundary_text = "; ".join(f"{case}: original {'yes' if flags['legacy'] else 'no'}, expanded {'yes' if flags['expanded'] else 'no'}"
                              for case, flags in data["boundary_flags"].items())
    p2_text = ("P2 has equal recorded peaks" if r['P2']['difference'] == 0 else f"P2 changes by {d('P2')}")
    return [
        ("Question and scope", [
            "How does the apparent sensitivity to the numerical water-speed limit depend on the reported quantity and the measurement definition?",
            f"This preliminary analysis uses published summaries for session {data['session']}, covering {data['duration_s']} s. "
            "Only the 50 and 100 m/s cases passed the recorded basic checks. The 200 m/s case remains excluded because it failed the recorded CFL/time-step checks.",
            f"Provenance base commit: {starting_commit}. The analysis-folder README records the inspected starting state and history comparison."]),
        ("Recorded quantities", [
            "Differences are 100 m/s minus 50 m/s. Percentages divide that difference by the 50 m/s value. "
            "They describe sensitivity, not error relative to reality, statistical uncertainty, or significance. Zero/negative baselines and comparisons crossing zero have no percentage here.",
            "Run-up and gauge elevations are relative to model sea level (0 m). Water depth is measured above local ground. Different maxima may occur at different times and locations. "
            "CSV files retain the recorded decimal precision and unrounded calculations (28 significant-digit decimal arithmetic); table rounding is for display only."]),
        ("Measurement definitions", [
            "Run-up is the highest eligible ground elevation reached by at least 0.1 m of water. Eligibility requires an observed level-1 monitor cell, "
            "ground elevation greater than zero, and exclusion of cells with any positive bilinear overlap with artificial geometry or an enabled virtual wall. "
            "The monitoring terrain is static. These masks and definitions are inherited from the archived measurement code, not recomputed or changed here.",
            f"Wetted land means eligible land wetted at any time during the recorded period, not simultaneous inundation. "
            f"The expanded monitor records {data['wetted_cells']['cap_050']} and {data['wetted_cells']['cap_100']} wetted eligible cells. "
            f"The fixed spacing is {data['dx_m']} × {data['dy_m']} m, giving {data['cell_area_m2']} m² per cell. "
            "Area is count × dx × dy / 1,000,000. Spacing is checked against the domain and grid dimensions; no 30 × 30 m approximation is used.",
            "Gauge values are simulated peak water-surface elevations, not historical observations or peak-to-trough wave heights. "
            f"Recorded sampling ranges: {gauge_text}. "
            "The report uses those recorded samples without extrapolation to the final field time; per-gauge sample counts and peak times are retained in provenance."]),
        ("Monitoring-area choice", [
            f"Local monitoring bounds: {bounds_text}. "
            "Comparisons between speed limits use the same area, threshold and eligibility rules. The original area is contained in the expanded area: these are overlapping coverage choices, not independent replications.",
            f"The cap-related run-up increase persists in both areas: {r['legacy']['difference']:.2f} m ({d('legacy')}) in the original area and "
            f"{r['expanded']['difference']:.2f} m ({d('expanded')}) in the expanded area. Expanding coverage changes the 50 m/s maximum by "
            f"{area[0]['difference_m']:.2f} m and the 100 m/s maximum by {area[1]['difference_m']:.2f} m ({area[1]['percent_difference']:.2f}%).",
            f"Recorded boundary-touch flags: {boundary_text}. The additional coverage changes the 100 m/s measurement slightly, "
            "but does not remove the difference between settings. This is not evidence of a bay-wide maximum."]),
        ("Supported wet-depth-threshold bound", [
            ("For both cases, the recorded expanded-area run-up is unchanged for every reporting threshold from 0.1 through 1.0 m, conditional on the archived evidence and fixed eligible cells."
             if supported else "The requested 0.1–1.0 m bound is not established for every case from the available records; see the evidence status and provenance reasons."),
            "Raising the threshold can only remove qualifying cells, so the maximum ground elevation cannot increase. A cell attaining the existing maximum "
            "remains qualified if its archived maximum depth reaches the new threshold. At least one such surviving cell gives the same lower bound, proving equality. "
            "The witness depths come specifically from the run-up-maximizing peak_locations entries, cross-checked between results and figure provenance, not the maximum depth elsewhere on land.",
            "This is a set-inclusion deduction from archived peak-cell information, not a newly executed threshold sweep. The published provenance records prior raw-monitor remeasurement "
            "and static-bed verification; this reanalysis verifies those records and source hashes but does not independently recheck the raw fields. "
            "It establishes neither unchanged wetted area nor behavior outside the interval, grid convergence, or physical accuracy."]),
        ("Interpretation and limits", [
            f"The response depends on the reported quantity. Expanded-area run-up changes by {d('expanded')}, wetted land area by {d('area')}, "
            f"and maximum land depth by {d('depth')}. {p2_text}; P3 changes by {d('P3')}, and P5 by {d('P5')}. "
            "Equal P2 peaks do not establish identical time series. The small decrease at P5 complicates a blanket claim that every response increases with the speed limit.",
            "This is a preliminary analysis of one configuration. Neither accepted speed limit is established as physically correct or optimal. "
            "The results do not establish historical accuracy or grid convergence. Artificial-boundary effects remain despite exclusion of artificial cells from measurements. "
            "Reanalysis of published summaries is distinct from independently reproducing the underlying simulations."]),
        ("Sources and regeneration", [
            "Run-up and gauge peaks: experiments/2026-10-19-speed-caps/results.json (accepted summary run-up values, with matching case diagnostics). "
            "Wetted cell counts, land-depth maxima, grid and monitoring definitions: docs/figures/figure_provenance.json. "
            "Matching run-up values, thresholds, coverage counts and peak-cell metadata agree across those files; the published results.csv and archived seals also agree.",
            "Metric definitions: simulation/runup_metrics.py, monitoring.py, read_output.py, validate.py and the original plot_figures.py. "
            "Terrain attribution: Franco et al. (2020), https://doi.org/10.5194/nhess-20-2255-2020; access and redistribution limits remain in docs/DATA.md. "
            "No private reference inputs or raw production fields are needed by this analysis.",
            "From the repository root: python3 -B analysis/measurement_robustness/analyze.py. "
            "Open report.html directly in a browser. The neighbouring README.md documents tests, provenance and output handling."])]


def write_reports(data, output, starting_commit):
    output.mkdir(parents=True, exist_ok=True)
    md = ["# Measurement robustness of archived Lituya Bay results", ""]
    report_note = ("Generated technical analysis report. AI-assisted software implementation, testing, analysis and documentation "
                   "were used to prepare this report; it is not an independently written PhD application writing sample. "
                   "Review of the generated calculations and conclusions is pending. HTML visual review is pending because "
                   "the browser policy blocked local-file inspection; structural and data checks are separate from visual review.")
    md += [report_note, "", "Generated by [analyze.py](analyze.py) from the published "
           "[results](../../experiments/2026-10-19-speed-caps/results.json) and "
           "[figure provenance](../../docs/figures/figure_provenance.json). See the repository's "
           "[research-authorship and AI-assistance statement](../../README.md#research-authorship).", ""]
    html = ["<!doctype html><html lang='en'><meta charset='utf-8'>",
            "<meta name='viewport' content='width=device-width, initial-scale=1'>",
            "<title>Lituya Bay — measurement robustness</title><style>",
            "body{font:16px/1.6 system-ui,sans-serif;color:#24313b;margin:0;background:#f4f5f6}"
            "main{max-width:1080px;margin:36px auto;padding:32px 42px;background:white}"
            "h1{font-size:30px;line-height:1.2}h2{font-size:21px;margin-top:32px}p{max-width:90ch}"
            "table{border-collapse:collapse;width:100%;font-size:14px;line-height:1.4;margin:22px 0}"
            "caption{text-align:left;font-weight:600;margin-bottom:10px}th,td{padding:10px 12px;border-bottom:1px solid #cdd3d8;text-align:left;vertical-align:top}"
            "thead{background:#eef1f3}td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}"
            "th.num{text-align:right}a{color:#254f72}code{overflow-wrap:anywhere}"
            ".table-wrap{overflow-x:auto}footer{font-size:13px;border-top:1px solid #cdd3d8;margin-top:30px;padding-top:16px}"
            "@media(max-width:650px){main{margin:0;padding:22px 16px}h1{font-size:25px}}"
            "@media print{@page{size:A4 landscape;margin:14mm}body{background:white;font-size:10pt}main{max-width:none;margin:0;padding:0}"
            "h2{break-after:avoid}p{orphans:3;widows:3}table{font-size:9pt}tr{break-inside:avoid}thead{display:table-header-group}"
            ".table-wrap{overflow:visible}a{color:inherit;text-decoration:none}th,td{padding:7px}}",
            "</style><main><h1>Measurement robustness of archived Lituya Bay results</h1>"]
    html += [f"<p>{escape(report_note)}</p>", "<p>Generated by <a href='analyze.py'>analyze.py</a> from the published "
             "<a href='../../experiments/2026-10-19-speed-caps/results.json'>results</a> and "
             "<a href='../../docs/figures/figure_provenance.json'>figure provenance</a>. See the repository's "
             "<a href='../../README.md#research-authorship'>research-authorship and AI-assistance statement</a>.</p>"]
    slots = {"Recorded quantities": "comparison", "Monitoring-area choice": "monitoring_choice",
             "Supported wet-depth-threshold bound": "threshold_bound"}
    for title, paragraphs in report_sections(data, starting_commit):
        md += [f"## {title}", ""]
        html.append(f"<section><h2>{escape(title)}</h2>")
        for text in paragraphs:
            md += [text, ""]
            html.append(f"<p>{escape(text)}</p>")
        if title in slots:
            key = slots[title]
            caption, columns = TABLES[key]
            rows = data[key]
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows({k: raw(v) for k, v in row.items()} for row in rows)
            (output / f"{key}.csv").write_text(stream.getvalue())
            md += [f"**{caption}**", "", "| " + " | ".join(c[1] for c in columns) + " |",
                   "| " + " | ".join("---:" if c[2] is not None else "---" for c in columns) + " |"]
            html.append(f"<div class='table-wrap'><table id='{key}'><caption>{escape(caption)}</caption><thead><tr>")
            for _, label, digits in columns:
                html.append(f"<th scope='col' class='{'num' if digits is not None else ''}'>{escape(label)}</th>")
            html.append("</tr></thead><tbody>")
            for row in rows:
                texts = [display(row, k, n) for k, _, n in columns]
                md.append("| " + " | ".join(texts) + " |")
                html.append("<tr>")
                for (k, _, digits), text in zip(columns, texts):
                    html.append(f"<td class='{'num' if digits is not None else ''}' data-key='{k}' "
                                f"data-value='{escape(raw(row[k]), quote=True)}'>{escape(text)}</td>")
                html.append("</tr>")
            html.append("</tbody></table></div>")
            md += ["", f"[Full-precision CSV]({key}.csv)", ""]
            html.append(f"<p><a href='{key}.csv'>Full-precision CSV</a></p>")
        html.append("</section>")
    md += ["[Analysis provenance](provenance.json)", ""]
    html.append("<footer>Source hashes, peak-cell evidence and working-tree context: <a href='provenance.json'>provenance.json</a>. "
                "All analysis content and styles are embedded; no external assets are required.</footer></main></html>")
    (output / "report.md").write_text("\n".join(md))
    (output / "report.html").write_text("\n".join(html))


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def provenance(root, hashes, data, starting_commit):
    changed = git(root, "diff", "--name-only", starting_commit).splitlines()
    untracked = git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    outside = {p: sha(root / p) for p in untracked if not p.startswith("analysis/measurement_robustness/") and (root/p).is_file()}
    return dict(schema=1, starting_commit=starting_commit, head_at_generation=git(root, "rev-parse", "HEAD"),
                branch=git(root, "branch", "--show-current"), session=data["session"],
                input_sha256=hashes, analysis_script_sha256=sha(Path(__file__)),
                tracked_changes_since_start=changed, preserved_untracked_files_sha256=outside,
                analysis_code_uncommitted="analysis/measurement_robustness/analyze.py" in untracked or
                                          "analysis/measurement_robustness/analyze.py" in changed,
                archived_hash_checks="passed; public source/summary seals checked, raw fields not accessed",
                analysis_starts_solver=False, raw_fields_remeasured=False, decimal_precision=28,
                area_conversion=dict(dx_m=data["dx_m"], dy_m=data["dy_m"], cell_area_m2=data["cell_area_m2"],
                                     wetted_cells=data["wetted_cells"], formula="count * dx_m * dy_m / 1000000"),
                threshold_bound_evidence=data["peak_evidence"], gauge_coverage=data["gauge_coverage"],
                source_paths=dict(runup=RESULTS + ": summary.cases; checked against case monitor diagnostics and figure runup_metrics",
                                  gauges=RESULTS + ": cases.<case>." + GAUGES,
                                  area_depth=FIGURES + ": runup_metrics.<case>.expanded",
                                  grid=FIGURES + ": simulation_settings"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=HERE)
    parser.add_argument("--starting-commit", default=None, help="Provenance base; defaults to current HEAD")
    args = parser.parse_args(argv)
    try:
        output = args.output_dir.resolve()
        # Only generated report names are written, never input files or figures.
        require(output == HERE or not output.is_relative_to(ROOT),
                "Output must be the analysis folder or a directory outside the repository")
        starting = git(ROOT, "rev-parse", (args.starting_commit or "HEAD") + "^{commit}")
        results, figures, hashes = verify_inputs(ROOT)
        data = compare_records(results, figures)
        manifest = provenance(ROOT, hashes, data, starting)
        write_reports(data, output, starting)
        names = ("comparison.csv", "monitoring_choice.csv", "threshold_bound.csv", "report.md", "report.html")
        manifest["output_sha256"] = {name: sha(output / name) for name in names}
        (output / "provenance.json").write_text(json.dumps(manifest, indent=2, default=str, allow_nan=False) + "\n")
        print(f"Verified published records; wrote {len(names)+1} outputs to {output}")
    except (RecordError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Analysis stopped: {exc}\n")


if __name__ == "__main__":
    main()
