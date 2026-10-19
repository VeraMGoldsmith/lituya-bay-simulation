"""Record the built solver, source revision, and executed smoke-test evidence."""
from __future__ import annotations

import argparse
import importlib.metadata as metadata
import os
from pathlib import Path
import platform
import subprocess
import sys

from simulation.common import ROOT, load, now, save, sha


def create(smoke_path: Path, destination: Path) -> dict:
    smoke = load(smoke_path)
    if smoke.get("status") != "passed":
        raise ValueError("Cannot record an unexecuted or failed solver smoke test.")
    claw = os.environ["CLAW"]
    def git(*arguments):
        return subprocess.check_output(["git", "-C", claw, *arguments], text=True).strip()
    record = {
        "built_utc": now(), "clawpack_tag": git("describe", "--tags", "--exact-match"),
        "clawpack_commit": git("rev-parse", "HEAD"), "submodules": git("submodule", "status", "--recursive"),
        "makefile_sha256": sha(ROOT / "geoclaw/Makefile"), "solver_sha256": sha(ROOT / "geoclaw/xgeoclaw"),
        "synthetic_solver_smoke_test": smoke, "python": sys.version,
        "platform": platform.platform(), "machine": platform.machine(),
        "compiler": subprocess.check_output(["gfortran", "--version"], text=True).splitlines()[0],
        "packages": sorted(f'{d.metadata["Name"]}=={d.version}' for d in metadata.distributions()),
        "limitation": "A synthetic executable test is not a Lituya Bay run or historical validation.",
    }
    save(destination, record)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    create(args.smoke, args.output)


if __name__ == "__main__":
    main()
