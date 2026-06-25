from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION_FILES = [
    "backend/app/main.py",
    "backend/app/services.py",
    "backend/app/edit_plan.py",
    "backend/app/srt.py",
    "backend/app/cli.py",
    "frontend/app.js",
    "frontend/index.html",
    "frontend/styles.css",
]


def compute_build_id() -> str:
    hasher = hashlib.sha256()
    for relative in VERSION_FILES:
        path = ROOT / relative
        if not path.exists():
            continue
        hasher.update(relative.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


def version_info() -> dict[str, str]:
    return {
        "app_version": "1.0.0",
        "build_id": compute_build_id(),
    }
