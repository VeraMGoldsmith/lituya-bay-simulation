"""Paths, atomic JSON records, and input fingerprints shared by the workflow."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid

ROOT = Path(os.environ.get("LITUYA_ROOT", Path(__file__).resolve().parents[1])).resolve()


def load(path: Path | str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path: Path | str, obj) -> None:
    """Replace a JSON record atomically; do not emit NaN as nonstandard JSON."""
    path = Path(path)
    data = json.dumps(obj, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sha(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def hash_json(obj) -> str:
    data = json.dumps(obj, sort_keys=True, allow_nan=False).encode()
    return hashlib.sha256(data).hexdigest()


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def new_session(root: Path | None = None) -> Path:
    root = Path(root or ROOT)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = root / "runs" / (stamp + "_" + uuid.uuid4().hex[:8])
    path.mkdir(parents=True, exist_ok=False)
    return path


def inside(root: Path, relative: str) -> Path:
    """Resolve a saved relative path without following it outside its run."""
    root = Path(root).resolve()
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("Expected a relative path inside the current run.")
    path = (root / rel).resolve()
    if path == root or root not in path.parents:
        raise ValueError("Saved path escapes its run directory.")
    return path
