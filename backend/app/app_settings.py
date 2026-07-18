from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .audit import audit_event
from .services import APP_DATA_DIR, atomic_write_json, require_project


APP_SETTINGS_PATH = APP_DATA_DIR / "settings" / "app.json"
DEFAULT_STARTUP_MODE = "resume_last"
STARTUP_MODES = {"resume_last", "new_project"}


def load_app_settings() -> dict[str, Any]:
    data: dict[str, Any] = {}
    if APP_SETTINGS_PATH.exists():
        try:
            value = json.loads(APP_SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                data = value
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail="アプリ起動設定を読み込めません") from exc
    startup_mode = str(data.get("startup_mode") or DEFAULT_STARTUP_MODE)
    if startup_mode not in STARTUP_MODES:
        startup_mode = DEFAULT_STARTUP_MODE
    return {
        "startup_mode": startup_mode,
        "last_project_id": str(data.get("last_project_id") or "") or None,
        "default_output_directory": str(data.get("default_output_directory") or ""),
        "output_create_project_subdirectory": data.get("output_create_project_subdirectory", True) is not False,
        "updated_at": data.get("updated_at"),
    }


def save_app_settings(
    *,
    startup_mode: str | None = None,
    last_project_id: str | None = None,
    update_last_project: bool = False,
    default_output_directory: str | None = None,
    output_create_project_subdirectory: bool | None = None,
) -> dict[str, Any]:
    current = load_app_settings()
    if startup_mode is not None:
        mode = str(startup_mode).strip()
        if mode not in STARTUP_MODES:
            raise HTTPException(status_code=400, detail="起動時の動作設定が不正です")
        current["startup_mode"] = mode
    if update_last_project:
        project_id = str(last_project_id or "").strip()
        if project_id:
            require_project(project_id)
            current["last_project_id"] = project_id
        else:
            current["last_project_id"] = None
    if default_output_directory is not None:
        directory = str(default_output_directory).strip()
        if directory and not Path(directory).expanduser().is_absolute():
            raise HTTPException(status_code=400, detail="既定の出力先は絶対パスで指定してください")
        current["default_output_directory"] = directory
    if output_create_project_subdirectory is not None:
        current["output_create_project_subdirectory"] = bool(output_create_project_subdirectory)
    current["updated_at"] = datetime.now(timezone.utc).isoformat()
    APP_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(APP_SETTINGS_PATH, current, backup=True)
    audit_event(
        "app.settings.updated",
        context={
            "startup_mode": current["startup_mode"],
            "has_last_project": bool(current.get("last_project_id")),
            "has_default_output_directory": bool(current.get("default_output_directory")),
        },
    )
    return current
