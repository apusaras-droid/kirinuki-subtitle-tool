from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
GLOBAL_AUDIT_LOG = ROOT / "logs" / "app_audit.jsonl"


def _write_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False) + "\n")


def audit_event(
    event: str,
    *,
    project_id: str | None = None,
    status: str = "ok",
    detail: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "status": status,
    }
    if project_id is not None:
        payload["project_id"] = project_id
    if detail is not None:
        payload["detail"] = detail
    if context:
        payload["context"] = context
    _write_jsonl(GLOBAL_AUDIT_LOG, payload)
    return payload


def project_audit_log(project_id: str) -> Path:
    return ROOT / "projects" / project_id / "temp" / "logs" / "audit.jsonl"


def project_detail_log(project_id: str, stream: str = "processing") -> Path:
    safe_stream = re.sub(r"[^A-Za-z0-9_.-]+", "_", stream)
    return ROOT / "projects" / project_id / "temp" / "logs" / f"{safe_stream}.jsonl"


def audit_project_event(
    project_id: str,
    event: str,
    *,
    status: str = "ok",
    detail: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = audit_event(event, project_id=project_id, status=status, detail=detail, context=context)
    _write_jsonl(project_audit_log(project_id), payload)
    return payload


def audit_project_detail_event(
    project_id: str,
    event: str,
    *,
    stream: str = "processing",
    status: str = "ok",
    detail: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = audit_event(event, project_id=project_id, status=status, detail=detail, context=context)
    _write_jsonl(project_detail_log(project_id, stream), payload)
    return payload
