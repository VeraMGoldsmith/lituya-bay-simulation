"""Unified project entry point. The shell launcher supplies its environment."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/lituya-matplotlib")

from simulation.common import ROOT, load, new_session, now, save
from simulation.prepare import prepare, validate_config
from simulation.runtime import run_cases, solver
from reporting import dashboard, plots
from calibration.search import run_search

CODE_DIRS = ("simulation", "calibration", "reporting", "geoclaw", "tools", "environment")


def archive_code(session: Path, root: Path) -> None:
    destination = session / "code"
    destination.mkdir()
    for name in CODE_DIRS:
        shutil.copytree(root / name, destination / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.o", "*.mod", "xgeoclaw"))
    for name in ("workflow.py", "config.json", "run.sh", "pyproject.toml"):
        shutil.copy2(root / name, destination / name)


def execute(config: dict, action: str, root: Path = ROOT) -> int:
    root = Path(root)
    validate_config(config)
    session = new_session(root)
    state = {"status": "preparing", "action": action, "started_utc": now(), "historically_validated": False}
    save(session / "workflow.json", state)
    save(root / "results/latest_attempt.json", {"run_directory": str(session.relative_to(root))})
    try:
        dashboard.render(session, root=root)
        archive_code(session, root)
        save(session / "requested_config.json", config)
        if action != "prepare":
            solver(config)
        baseline = session / "baseline"
        setup, checks = prepare(config, baseline / "inputs")
        save(baseline / "status.json", {"status": "prepared_not_simulated"})
        plots.input_previews(baseline / "inputs", baseline / "input_preview")
        if action == "prepare":
            state.update(status="prepared_not_simulated", completed_utc=now())
            save(session / "workflow.json", state)
            dashboard.render(session, root=root)
            return 0
        run_cases(config, setup, baseline)
        selected, records = baseline, []
        if action == "all":
            state["status"] = "calibrating_source"
            save(session / "workflow.json", state)
            dashboard.render(session, root=root)
            selected, records = run_search(config, baseline, setup, session / "calibration",
                                           load(root / "calibration/search.json"), load(root / "calibration/targets.json"))
        if selected != baseline:
            plots.input_previews(selected / "inputs", selected / "input_preview")
        plots.results(selected)
        partial = any(record["status"] != "completed" for record in records)
        state.update(status="partial" if partial else "completed", completed_utc=now(), records=records,
                     selected_directory=selected.relative_to(session).as_posix())
        save(session / "workflow.json", state)
        dashboard.render(session, root=root)
        if not partial:
            save(root / "results/latest_success.json", {"run_directory": str(session.relative_to(root))})
        print("\nResults: results/index.html")
        print("Numerical output, not a claim of historical validation.")
        if partial:
            print("Some source candidates failed or were rejected. Inspect the partial report.", file=sys.stderr)
        return 1 if partial else 0
    except BaseException as exc:
        error = traceback.format_exc()
        (session / "last_error.txt").write_text(error)
        state.update(status="failed", error=str(exc))
        save(session / "workflow.json", state)
        (root / "results/last_error.txt").write_text(error)
        dashboard.render(session, error=str(exc), root=root)
        print(f"Stopped: {exc}\nPreserved diagnostics: {session}", file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", default="all", choices=["all", "baseline", "prepare", "test", "report", "check"])
    parser.add_argument("--config", type=Path, default=ROOT / "config.json", help="Configuration file inside the repository")
    parser.add_argument("--grid", type=float, choices=[15., 30., 60.])
    parser.add_argument("--sw-relief-factor", type=float)
    parser.add_argument("--travel-m", type=float, help="Prescribed distance toward decreasing local Y")
    parser.add_argument("--duration-s", type=float, help="Prescribed landslide movement duration")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = arguments(argv)
    if args.action == "report":
        print(dashboard.refresh())
        return 0
    if args.action in {"all", "baseline", "prepare", "test"}:
        status = subprocess.call([sys.executable, "-m", "pytest"], cwd=ROOT)
        if status or args.action == "test":
            return status
    config = load(args.config)
    if args.grid is not None:
        config["run"]["target_cell_size_m"] = args.grid
    if args.sw_relief_factor is not None:
        config["geometry"]["sw_relief_factor"] = args.sw_relief_factor
    if args.travel_m is not None:
        config["source"]["travel_negative_y_m"] = args.travel_m
    if args.duration_s is not None:
        config["source"]["travel_duration_s"] = args.duration_s
    if args.action == "all" and config["geometry"]["sw_relief_factor"] != 1.:
        raise ValueError("Calibrate the source on baseline geometry first. Use baseline for a fixed-source geometry experiment.")
    if args.action == "check":
        exe, _ = solver(config)
        print("Verified solver:", exe)
        return 0
    return execute(config, args.action)


if __name__ == "__main__":
    raise SystemExit(main())
