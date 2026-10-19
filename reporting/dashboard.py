"""One results page for inputs, candidate scores, and every saved final plot.

The former results-page patch is integrated here. No code is rewritten at run
time. A failed attempt cannot silently fall back to a previous successful run.
"""
from __future__ import annotations

import html
import os
from pathlib import Path
from urllib.parse import quote

from simulation.common import ROOT, inside, load

IMAGE_SUFFIXES = {".png", ".gif", ".jpg", ".jpeg", ".webp"}
PREFERRED = ["inlet_wave.gif", "basin_wave.gif", "inlet_gauges.png", "bay_gauges.png", "opposite_slope_max_depth.png"]


def url(path: Path, output: Path) -> str:
    return html.escape(quote(os.path.relpath(path, output), safe="/"), quote=True)


def gallery(folder: Path, output: Path, title: str) -> str:
    folder = Path(folder)
    files = [p for p in folder.rglob("*") if p.is_file() and not p.is_symlink() and folder.resolve() in p.resolve().parents]
    files.sort(key=lambda p: (PREFERRED.index(p.name) if p.name in PREFERRED else len(PREFERRED), p.relative_to(folder).as_posix()))
    body = f"<h2>{html.escape(title)}</h2>"
    if not files:
        return body + "<p>No files have been generated for this section.</p>"
    for path in files:
        name, link = html.escape(path.relative_to(folder).as_posix()), url(path, output)
        if path.suffix.lower() in IMAGE_SUFFIXES:
            body += f'<figure><a href="{link}"><img src="{link}" loading="lazy" alt="{name}"></a><figcaption>{name}</figcaption></figure>'
        else:
            body += f'<p><a href="{link}">{name}</a></p>'
    return body


def score_table(records: list[dict]) -> str:
    body = '<h2>Source-path search</h2><div class="table"><table><thead><tr><th>Case</th><th>Travel (m)</th><th>Duration (s)</th><th>End centroid X / Y (m)</th><th>Run-up proxy (m)</th><th>Score</th><th>Status</th></tr></thead><tbody>'
    for record in records:
        endpoint = record.get("placement", {}).get("prescribed_final_centroid_xy_m")
        values = [record["candidate"], record.get("travel_negative_y_m"), record.get("duration_s"),
                  " / ".join(f"{v:.1f}" for v in endpoint) if endpoint else None,
                  record.get("runup_m"), record.get("score"), record.get("status")]
        def display(value):
            return "—" if value is None else (f"{value:.4f}" if isinstance(value, float) else str(value))
        body += "<tr>" + "".join("<td>" + html.escape(display(value)) + "</td>" for value in values) + "</tr>"
        if record.get("error"):
            body += '<tr><td colspan="7">' + html.escape(record["error"]) + '</td></tr>'
    return body + '</tbody></table></div><p>Lower is a closer match to the declared proxy targets, not proof of historical accuracy. End centroids describe the prescribed slide footprint, not an observed impact point.</p>'


def runup_description(validation: dict) -> str:
    primary = validation.get("runup_primary")
    if primary:
        height = primary["maximum_wetted_cell_elevation_m"]
        text = (f'<p>Primary run-up monitor: <strong>{html.escape(primary["name"])}</strong>. '
                f'Maximum wetted cell-bed elevation: <strong>{height:.2f} m</strong>. '
                'This is a window-specific diagnostic, not a verified whole-slope maximum.</p>')
        if primary.get("peak_touches_monitor_boundary"):
            text += '<p class="note">The primary peak touches the monitoring boundary; the reported maximum may be spatially truncated.</p>'
        legacy = validation.get("opposite_SW_slope_max_wetted_cell_elevation_m")
        if legacy is not None:
            text += f'<p>Legacy-window comparison: {legacy:.2f} m. Existing legacy-slope plots retain that smaller window.</p>'
        return text
    return (f'<p>Maximum wetted ground elevation in the legacy receiving-slope monitor: '
            f'<strong>{validation["opposite_SW_slope_max_wetted_cell_elevation_m"]:.2f} m</strong>, '
            f'at a {validation["runup_depth_threshold_m"]:g} m depth threshold.</p>')


def render(session: Path | None = None, error: str | None = None, root: Path | None = None) -> Path:
    root = Path(root or ROOT).resolve()
    output = root / "results"
    output.mkdir(parents=True, exist_ok=True)
    body = ""
    if session is None:
        body = '<h2>Not run yet</h2><p>Run <code>bash run.sh</code> from the repository root.</p>'
    else:
        session = Path(session).resolve()
        if (root / "runs").resolve() not in session.parents:
            raise ValueError("Results must belong to this repository's runs directory.")
        state = load(session / "workflow.json")
        body = '<p class="meta">Run ' + html.escape(session.name) + ' · ' + html.escape(state["status"]) + '</p>'
        if error or state["status"] == "failed":
            body += '<h2>Stopped</h2><p>This attempt did not finish. No older run is substituted.</p><pre>' + html.escape(error or state.get("error", "See the logs.")) + '</pre>'
        elif state["status"] == "prepared_not_simulated":
            body += '<h2>Inputs prepared — no water simulation yet</h2>'
            body += gallery(session / "baseline/input_preview", output, "Input geometry only")
        elif state["status"] in {"completed", "partial"}:
            selected = inside(session, state["selected_directory"])
            if load(selected / "status.json").get("status") != "completed_basic_checks":
                raise ValueError("Selected run is not complete; refusing to present wave results.")
            for case in ("still", "slide"):
                if load(selected / case / "validation.json").get("status") != "passed_basic_checks":
                    raise ValueError("Selected run lacks passed case checks.")
            validation = load(selected / "slide/validation.json")
            heading = "Partial search — inspect failed candidates" if state["status"] == "partial" else "Calculation complete"
            body += f'<h2>{heading}</h2><p>Displayed case: <strong>{html.escape(state["selected_directory"])}</strong>.</p>'
            body += runup_description(validation)
            body += '<p class="note">Numerical checks passed for the displayed case. Historical validation remains separate.</p>'
            time_check = selected / "slide/time_step_check.json"
            if time_check.is_file():
                audit = load(time_check)
                body += f'<p><a href="{url(time_check, output)}">Actual time-step audit</a></p>'
                if audit.get("logged_speed_resets", 0):
                    body += '<p class="note">Water-speed limiting occurred during this calculation. Its influence has not been quantified; this is not a validated historical run-up prediction.</p>'

            if state.get("records"):
                body += score_table(state["records"])
            body += gallery(selected / "input_preview", output, "Source placement and reconstructed inputs")
            body += gallery(selected / "plots", output, "All saved wave plots, snapshots, and data")
            for name in ("inputs/config.json", "inputs/source_placement.json", "slide/validation.json", "slide/field_history.csv"):
                body += f'<p><a href="{url(selected / name, output)}">{html.escape(name)}</a></p>'
        else:
            body += '<h2>Work in progress</h2><p>The current attempt is not ready to interpret.</p>'
        body += f'<p><a href="{url(session / "workflow.json", output)}">Workflow record</a></p>'
    text = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Lituya Bay | Model results</title><style>
body{font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;max-width:1000px;margin:0 auto;padding:32px 22px;color:#23333d;background:#fafaf8}header{border-bottom:2px solid #344852;margin-bottom:32px;padding-bottom:20px}h1{font-size:34px;letter-spacing:-.04em;margin:8px 0}h2{margin-top:36px;font-size:23px;letter-spacing:-.025em}.meta,figcaption{font-size:13px;color:#607078}a{color:#24596f}code,pre{font-family:ui-monospace,SFMono-Regular,monospace}pre{white-space:pre-wrap;padding:18px;background:#f0ece5;overflow-wrap:anywhere}figure{margin:24px 0;background:white;border:1px solid #deded6;padding:14px}img{max-width:100%;height:auto;display:block;margin:auto}figcaption{margin-top:10px}.note{border-left:3px solid #aa8754;padding:12px 18px;background:#f4efe6}.table{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:10px;border-bottom:1px solid #d7d9d5;text-align:left}th{white-space:nowrap}footer{margin-top:48px;border-top:1px solid #d7d9d5;padding-top:16px;font-size:13px}</style></head><body><header><p class="meta">RECONSTRUCTED BASIN / PRESCRIBED SOURCE</p><h1>Lituya Bay</h1><p>Published geometry, a declared landslide path, and the resulting water response.</p></header>'''
    text += body + '<footer>GeoClaw adaptation of Franco et al. geometry. HySEA results are comparison evidence, not an embedded solver. This page is generated from the current attempt only.</footer></body></html>'
    path = output / "index.html"
    path.write_text(text, encoding="utf-8")
    return path


def refresh(root: Path | None = None) -> Path:
    root = Path(root or ROOT).resolve()
    pointer = root / "results/latest_attempt.json"
    if not pointer.is_file():
        return render(root=root)
    session = inside(root, load(pointer)["run_directory"])
    return render(session, root=root)
