"""Run the existing GeoClaw executable and retain checks for every attempt.

A stationary control can be reused only when its inputs and solver fingerprint
match. That removes duplicate integrations, not a numerical acceptance check.
"""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import time

from .common import ROOT, hash_json, load, now, save, sha
from .validate import validate
from .time_steps import audit as audit_time_steps
from geoclaw.setrun import write_data


def logged(command, cwd: Path, path: Path) -> None:
    with Path(path).open("w", encoding="utf-8") as out:
        out.write("COMMAND: " + " ".join(map(str, command)) + "\n")
        out.flush()
        process = subprocess.Popen(
            list(map(str, command)), cwd=cwd, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True,
        )
        try:
            for line in process.stdout:
                print(line, end="", flush=True)
                out.write(line)
                out.flush()
            status = process.wait()
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            except ProcessLookupError:
                pass
            raise
    if status:
        raise RuntimeError(f"Solver returned exit {status}; see {path}.")


def solver(config: dict):
    # Legacy variable names permit reuse of the user's already compiled image.
    # New builds and all repository directories use project-neutral names.
    exe = Path(os.environ.get("LITUYA_SOLVER", os.environ.get("VERA_PREBUILT_EXE", "/not-set")))
    manifest = Path(os.environ.get("LITUYA_BUILD_MANIFEST", os.environ.get("VERA_BUILD_MANIFEST", "/not-set")))
    claw = Path(os.environ.get("CLAW", "/not-set"))
    if not exe.is_file() or not manifest.is_file():
        raise RuntimeError("A compiled solver and its manifest are required. Start with bash run.sh.")
    record = load(manifest)
    allowed = load(ROOT / "environment/compatible_recipes.json")["allowed_makefile_sha256"]
    if (record.get("clawpack_tag") != config["clawpack_tag"]
            or record.get("makefile_sha256") not in allowed
            or record.get("solver_sha256") != sha(exe)):
        raise RuntimeError("Solver fingerprint does not match the reviewed recipe. Use bash run.sh --build.")
    if record.get("synthetic_solver_smoke_test", {}).get("status") != "passed":
        raise RuntimeError("No passed executable smoke test is recorded in this image.")
    if not (claw / "geoclaw/src/2d/shallow/Makefile.geoclaw").is_file():
        raise RuntimeError("Clawpack source tree is missing from the image.")
    tag = subprocess.check_output(["git", "-C", str(claw), "describe", "--tags", "--exact-match"], text=True).strip()
    if tag != config["clawpack_tag"]:
        raise RuntimeError("Clawpack tag differs from the configuration.")
    revisions = subprocess.check_output(["git", "-C", str(claw), "submodule", "status", "--recursive"], text=True)
    if any(line.startswith(("-", "+", "U")) for line in revisions.splitlines()):
        raise RuntimeError("Unexpected Clawpack submodule revisions.")
    return exe, record


def control_key(config: dict, setup: dict, image: dict) -> str:
    """Fingerprint every variable used by setrun() in the stationary case."""
    return hash_json({
        "terrain_sha256": setup["terrain_file_sha256"],
        "grid": [setup["nx"], setup["ny"], setup["domain_xyxy_m"]],
        "gauges": setup["gauges"], "water": config["water"],
        "run": config["run"], "checks": config["checks"],
        "geometry": config["geometry"],
        "step_limit": config["source"]["maximum_solver_step_during_motion_s"],
        "solver_sha256": image["solver_sha256"],
        "clawpack_tag": config["clawpack_tag"],
        "setrun_sha256": sha(ROOT / "geoclaw/setrun.py"),
    })


def seal_control(session: Path, config: dict, setup: dict, image: dict) -> None:
    folder = session / "still"
    files = {p.name: sha(p) for p in sorted(folder.iterdir()) if p.is_file()}
    save(session / "control_signature.json", {
        "key": control_key(config, setup, image), "files": files,
        "note": "Reuse requires matching stationary inputs and unchanged saved control files.",
    })


def checked_control(control: Path, config: dict, setup: dict, image: dict) -> dict:
    control = Path(control)
    signature = load(control / "control_signature.json")
    if signature["key"] != control_key(config, setup, image):
        raise ValueError("Stationary-control inputs differ; reuse is not permitted.")
    result = load(control / "still/validation.json")
    if result.get("status") != "passed_basic_checks":
        raise ValueError("Stationary control did not pass its numerical checks.")
    if not signature["files"]:
        raise ValueError("Stationary control has no sealed output files.")
    for name, expected in signature["files"].items():
        if Path(name).name != name or sha(control / "still" / name) != expected:
            raise ValueError("Stationary-control output changed after validation.")
    return result


def run_cases(config: dict, setup: dict, session: Path, control: Path | None = None) -> dict:
    session = Path(session)
    exe, image = solver(config)
    save(session / "image_manifest.json", image)
    state = {"status": "running", "started_utc": now(), "cases": {}, "historically_calibrated": False}
    save(session / "status.json", state)
    baseline = None
    try:
        if control is not None:
            baseline = checked_control(control, config, setup, image)
            save(session / "still/validation.json", baseline)
            save(session / "still/reused_control.json", {
                "source_directory": os.path.relpath(control, session),
                "control_key": control_key(config, setup, image),
                "solver_integration_performed_here": False,
            })
            state["cases"]["still"] = {"status": "reused_checked_control", "key": control_key(config, setup, image)}
        for case in (("slide",) if control is not None else ("still", "slide")):
            folder = session / case
            write_data(folder, session / "inputs", config, setup, case)
            print(f"\n{session.name} / {case}: {config['run']['duration_s']:g} simulated seconds", flush=True)
            started = time.monotonic()
            logged([exe], folder, folder / "solver.log")
            audit_time_steps(folder, config, case)
            result = validate(folder, case, config, setup, session / "inputs", baseline)
            result["solver_wall_seconds_measured"] = time.monotonic() - started
            save(folder / "validation.json", result)
            state["cases"][case] = result
            if case == "still":
                baseline = result
                seal_control(session, config, setup, image)
            save(session / "status.json", state)
        state.update(status="completed_basic_checks", completed_utc=now())
        save(session / "status.json", state)
    except BaseException as exc:
        state.update(status="failed", error=str(exc))
        save(session / "status.json", state)
        raise
    return state
