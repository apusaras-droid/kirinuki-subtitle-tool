from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .audit import audit_event
from .services import APP_DATA_DIR, atomic_write_json, load_project_edit_plan, require_project
from .srt import write_srt


PRIVATE_DIR = APP_DATA_DIR / "private"
GEMINI_CONFIG_PATH = PRIVATE_DIR / "gemini.json"
DEFAULT_MODEL = "gemini-3.5-flash"
DEFAULT_SPEAKER_LABELS_ENABLED = True
DEFAULT_SRT_TIMING_PRIORITY = True
KNOWLEDGE_BASE_FILENAME = "knowledge_base.json"
KNOWLEDGE_LINK_FILENAME = "knowledge_base_link.json"
SHARED_KNOWLEDGE_DIR = APP_DATA_DIR / "shared" / "knowledge_bases"
GEMINI_MODEL_REGISTRY = (
    {
        "id": "gemini-3.1-flash-lite",
        "label": "Gemini 3.1 Flash-Lite",
        "profile": "軽量・推奨",
        "description": "高速な安定版。字幕校正、作品DB整理、Web調査向け。",
    },
    {
        "id": "gemini-2.5-flash-lite",
        "label": "Gemini 2.5 Flash-Lite",
        "profile": "最軽量・互換",
        "description": "軽量な安定版。単純な置換や構造化処理向け。",
    },
    {
        "id": "gemini-2.5-flash",
        "label": "Gemini 2.5 Flash",
        "profile": "標準・互換",
        "description": "品質と速度のバランスを重視する安定版。",
    },
    {
        "id": "gemini-3.5-flash",
        "label": "Gemini 3.5 Flash",
        "profile": "高品質",
        "description": "音声文字起こしと複雑な校正を優先する安定版。",
    },
    {
        "id": "gemini-3.1-pro-preview",
        "label": "Gemini 3.1 Pro Preview",
        "profile": "高精度・制限注意",
        "description": "複雑な判断向け。Previewのため制限と変更に注意。",
    },
)


def _read_config() -> dict[str, Any]:
    if not GEMINI_CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(GEMINI_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Gemini秘密設定を読み込めません") from exc
    return data if isinstance(data, dict) else {}


def gemini_config_status() -> dict[str, Any]:
    config = _read_config()
    key = str(config.get("api_key") or os.environ.get("GEMINI_API_KEY") or "").strip()
    return {
        "configured": bool(key),
        "source": "environment" if os.environ.get("GEMINI_API_KEY") else ("private_file" if key else "none"),
        "masked_key": f"...{key[-4:]}" if len(key) >= 4 else ("設定済み" if key else ""),
        "model": str(config.get("model") or DEFAULT_MODEL),
        "speaker_labels_enabled": bool(config.get("speaker_labels_enabled", DEFAULT_SPEAKER_LABELS_ENABLED)),
        "srt_timing_priority": bool(config.get("srt_timing_priority", DEFAULT_SRT_TIMING_PRIORITY)),
    }


def gemini_model_status(probe: bool = False) -> dict[str, Any]:
    key = _api_key()
    try:
        from google import genai
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="google-genaiが未導入です。setup.batまたはpip install -r requirements.txtを実行してください") from exc
    available: set[str] = set()
    error = ""
    client = genai.Client(api_key=key)
    try:
        for model in client.models.list():
            name = str(getattr(model, "name", "") or "").strip()
            if name.startswith("models/"):
                name = name[7:]
            if name:
                available.add(name)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        audit_event("gemini.models.list_failed", context={"error_type": type(exc).__name__})
    models = []
    for spec in GEMINI_MODEL_REGISTRY:
        item = dict(spec)
        availability = "available" if spec["id"] in available else ("unavailable" if not error else "unknown")
        probe_status = "not_checked"
        probe_error = ""
        if probe and availability == "available":
            try:
                response = client.interactions.create(model=spec["id"], input="Reply with OK only.")
                probe_status = "ready" if str(getattr(response, "output_text", "") or "").strip() else "error"
            except Exception as exc:
                probe_error = str(exc)
                lowered = probe_error.lower()
                if "429" in lowered or "quota" in lowered or "too_many_requests" in lowered or "resource_exhausted" in lowered:
                    probe_status = "rate_limited"
                elif "404" in lowered or "not found" in lowered or "unsupported" in lowered:
                    probe_status = "unavailable"
                else:
                    probe_status = "error"
        item.update({
            "audio_input": True,
            "structured_output": True,
            "search_grounding": True,
            "availability": availability,
            "probe_status": probe_status,
            "probe_error": probe_error[:300],
        })
        models.append(item)
    return {
        "checked": not bool(error),
        "probed": probe,
        "models": models,
        "error": error[:500],
        "note": "制限はモデル別とプロジェクト共有の両方があります。readyは最小リクエスト成功、rate_limitedは現在制限中です。",
    }


def save_gemini_config(
    api_key: str | None,
    model: str | None,
    clear_key: bool = False,
    speaker_labels_enabled: bool | None = None,
    srt_timing_priority: bool | None = None,
) -> dict[str, Any]:
    current = _read_config()
    if clear_key:
        current.pop("api_key", None)
    elif api_key is not None and api_key.strip():
        current["api_key"] = api_key.strip()
    if model is not None and model.strip():
        current["model"] = model.strip()
    if speaker_labels_enabled is not None:
        current["speaker_labels_enabled"] = bool(speaker_labels_enabled)
    if srt_timing_priority is not None:
        current["srt_timing_priority"] = bool(srt_timing_priority)
    current["updated_at"] = datetime.now(timezone.utc).isoformat()
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(GEMINI_CONFIG_PATH, current)
    audit_event(
        "gemini.config.updated",
        context={
            "configured": bool(current.get("api_key")),
            "model": current.get("model"),
            "speaker_labels_enabled": bool(current.get("speaker_labels_enabled", DEFAULT_SPEAKER_LABELS_ENABLED)),
            "srt_timing_priority": bool(current.get("srt_timing_priority", DEFAULT_SRT_TIMING_PRIORITY)),
        },
    )
    return gemini_config_status()


def _api_key() -> str:
    key = str(os.environ.get("GEMINI_API_KEY") or _read_config().get("api_key") or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="詳細設定でGemini APIキーを設定してください")
    return key


def _proposal_schema() -> dict[str, Any]:
    source_ids = {"type": "array", "items": {"type": "string"}}
    replacement = {
        "type": "object",
        "properties": {"text": {"type": "string"}, "speaker": {"type": "string"}},
        "required": ["text", "speaker"],
    }
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "transcript_segments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "start_sec": {"type": "number"}, "end_sec": {"type": "number"},
                        "text": {"type": "string"}, "speaker": {"type": "string"},
                    },
                    "required": ["start_sec", "end_sec", "text", "speaker"],
                },
            },
            "subtitle_edits": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source_subtitle_ids": source_ids,
                        "action": {"type": "string", "enum": ["keep", "correct", "merge", "split"]},
                        "replacements": {"type": "array", "items": replacement},
                        "reason": {"type": "string"}, "confidence": {"type": "number"},
                    },
                    "required": ["source_subtitle_ids", "action", "replacements", "reason", "confidence"],
                },
            },
            "chapters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"title": {"type": "string"}, "source_subtitle_ids": source_ids, "summary": {"type": "string"}},
                    "required": ["title", "source_subtitle_ids", "summary"],
                },
            },
            "cut_proposals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["remove", "keep", "highlight"]},
                        "start_sec": {"type": "number"}, "end_sec": {"type": "number"},
                        "source_subtitle_ids": source_ids, "reason": {"type": "string"}, "confidence": {"type": "number"},
                    },
                    "required": ["action", "start_sec", "end_sec", "source_subtitle_ids", "reason", "confidence"],
                },
            },
        },
        "required": ["summary", "transcript_segments", "subtitle_edits", "chapters", "cut_proposals"],
    }


def _transcript_schema(include_speaker: bool = True) -> dict[str, Any]:
    segment_properties = {
        "start_sec": {"type": "number"},
        "end_sec": {"type": "number"},
        "text": {"type": "string"},
    }
    segment_required = ["start_sec", "end_sec", "text"]
    if include_speaker:
        segment_properties["speaker"] = {"type": "string"}
        segment_required.append("speaker")
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "segments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": segment_properties,
                    "required": segment_required,
                },
            },
        },
        "required": ["summary", "segments"],
    }


_GENERATED_SPEAKER_PREFIX = re.compile(
    r"^\s*(?:"
    r"[\[（(]\s*(?:speaker\s*[_-]?\s*[\w.-]+|話者\s*[\w０-９Ａ-Ｚａ-ｚ.-]+|男性|女性|男声|女声|ナレーター|ナレーション)\s*[\]）)]\s*[:：]?"
    r"|(?:speaker\s*[_-]?\s*[\w.-]+|話者\s*[\w０-９Ａ-Ｚａ-ｚ.-]+|男性|女性|男声|女声|ナレーター|ナレーション)\s*[:：]"
    r")\s*",
    re.IGNORECASE,
)


def _strip_generated_speaker_prefix(text: str) -> str:
    return _GENERATED_SPEAKER_PREFIX.sub("", text, count=1).strip()


def _knowledge_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "work_title": {"type": "string"},
            "summary": {"type": "string"},
            "entries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["character", "term"]},
                        "canonical_name": {"type": "string"},
                        "aliases": {"type": "array", "items": {"type": "string"}},
                        "description": {"type": "string"},
                        "source_urls": {"type": "array", "items": {"type": "string"}},
                        "confidence": {"type": "number"},
                    },
                    "required": ["type", "canonical_name", "aliases", "description", "source_urls", "confidence"],
                },
            },
        },
        "required": ["work_title", "summary", "entries"],
    }


def _interaction_json(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except TypeError:
            return value.model_dump()
    if isinstance(value, dict):
        return {str(key): _interaction_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_interaction_json(item) for item in value]
    return value


def _extract_url_citations(interaction: Any) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    seen: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("type") == "url_citation":
                url = str(value.get("url") or "").strip()
                if url.startswith(("https://", "http://")) and url not in seen:
                    seen.add(url)
                    found.append({"url": url, "title": str(value.get("title") or url).strip()[:300]})
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(_interaction_json(interaction))
    return found


def _safe_knowledge_database_id(database_id: str) -> str:
    value = str(database_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", value):
        raise HTTPException(status_code=400, detail="作品DB IDが不正です")
    return value


def _knowledge_link_path(project_id: str) -> Path:
    return require_project(project_id) / "ai" / KNOWLEDGE_LINK_FILENAME


def _read_knowledge_link(project_id: str) -> str | None:
    path = _knowledge_link_path(project_id)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="作品DBの紐付け情報を読み込めません") from exc
    database_id = str(value.get("database_id") or "").strip() if isinstance(value, dict) else ""
    return _safe_knowledge_database_id(database_id) if database_id else None


def _shared_knowledge_path(database_id: str) -> Path:
    return SHARED_KNOWLEDGE_DIR / f"{_safe_knowledge_database_id(database_id)}.json"


def _knowledge_path(project_id: str) -> Path:
    linked_database_id = _read_knowledge_link(project_id)
    if linked_database_id:
        shared_path = _shared_knowledge_path(linked_database_id)
        if not shared_path.exists():
            raise HTTPException(status_code=404, detail="紐付けられた共通作品DBが見つかりません")
        return shared_path
    return require_project(project_id) / "ai" / KNOWLEDGE_BASE_FILENAME


def load_project_knowledge_base(project_id: str) -> dict[str, Any]:
    linked_database_id = _read_knowledge_link(project_id)
    path = _knowledge_path(project_id)
    if not path.exists():
        return {
            "schema_version": "1.0",
            "project_id": project_id,
            "work_title": "",
            "summary": "",
            "entries": [],
            "sources": [],
            "storage_scope": "project",
            "linked_database_id": None,
        }
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="キャラクター・用語DBを読み込めません") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=500, detail="キャラクター・用語DBの形式が不正です")
    value.setdefault("entries", [])
    value.setdefault("sources", [])
    value["storage_scope"] = "shared" if linked_database_id else "project"
    value["linked_database_id"] = linked_database_id
    return value


def list_shared_knowledge_bases() -> list[dict[str, Any]]:
    if not SHARED_KNOWLEDGE_DIR.exists():
        return []
    result = []
    for path in sorted(SHARED_KNOWLEDGE_DIR.glob("*.json"), key=lambda item: item.name.casefold()):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict):
            continue
        result.append({
            "database_id": path.stem,
            "database_name": str(value.get("database_name") or value.get("work_title") or path.stem),
            "work_title": str(value.get("work_title") or ""),
            "entry_count": len(value.get("entries") or []),
            "updated_at": value.get("updated_at"),
        })
    return result


def register_project_knowledge_as_shared(project_id: str, database_name: str) -> dict[str, Any]:
    name = str(database_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="共通作品DBの名前を入力してください")
    current = load_project_knowledge_base(project_id)
    current_database_id = str(current.get("linked_database_id") or "").strip()
    database_id = current_database_id or f"kb_{uuid.uuid4().hex[:16]}"
    result = dict(current)
    result.pop("storage_scope", None)
    result.pop("linked_database_id", None)
    result["database_id"] = database_id
    result["database_name"] = name[:300]
    result["updated_at"] = datetime.now(timezone.utc).isoformat()
    result["updated_by"] = "user"
    SHARED_KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(_shared_knowledge_path(database_id), result, backup=True)
    link_project_knowledge_base(project_id, database_id)
    audit_event("gemini.knowledge.registered_shared", project_id=project_id, context={"database_id": database_id, "entries": len(result.get("entries") or [])})
    return load_project_knowledge_base(project_id)


def link_project_knowledge_base(project_id: str, database_id: str | None) -> dict[str, Any]:
    link_path = _knowledge_link_path(project_id)
    value = str(database_id or "").strip()
    if not value:
        if link_path.exists():
            try:
                link_path.unlink()
            except OSError as exc:
                raise HTTPException(status_code=500, detail="作品DBの紐付けを解除できません") from exc
        audit_event("gemini.knowledge.unlinked", project_id=project_id)
        return load_project_knowledge_base(project_id)
    safe_id = _safe_knowledge_database_id(value)
    if not _shared_knowledge_path(safe_id).exists():
        raise HTTPException(status_code=404, detail="選択した共通作品DBが見つかりません")
    atomic_write_json(link_path, {
        "database_id": safe_id,
        "linked_at": datetime.now(timezone.utc).isoformat(),
    }, backup=True)
    audit_event("gemini.knowledge.linked", project_id=project_id, context={"database_id": safe_id})
    return load_project_knowledge_base(project_id)


def _string_list(value: Any, limit: int = 30) -> list[str]:
    values = value if isinstance(value, list) else str(value or "").split(",")
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item or "").strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text[:300])
        if len(result) >= limit:
            break
    return result


def _normalize_knowledge_entry(item: dict[str, Any], *, user_edited: bool | None = None) -> dict[str, Any] | None:
    canonical_name = str(item.get("canonical_name") or "").strip()[:300]
    if not canonical_name:
        return None
    entry_type = str(item.get("type") or "term").strip()
    if entry_type not in {"character", "term"}:
        entry_type = "term"
    source_urls = [url for url in _string_list(item.get("source_urls"), 20) if url.startswith(("https://", "http://"))]
    try:
        confidence = float(item.get("confidence", 1.0) or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    normalized = {
        "id": str(item.get("id") or f"kb_{uuid.uuid4().hex[:12]}")[:80],
        "type": entry_type,
        "canonical_name": canonical_name,
        "aliases": _string_list(item.get("aliases"), 30),
        "description": str(item.get("description") or "").strip()[:2000],
        "source_urls": source_urls,
        "confidence": round(max(0.0, min(1.0, confidence)), 3),
        "enabled": item.get("enabled", True) is not False,
        "origin": str(item.get("origin") or "manual")[:40],
        "user_edited": bool(item.get("user_edited", False) if user_edited is None else user_edited),
    }
    return normalized


def save_project_knowledge_base(project_id: str, knowledge_base: dict[str, Any]) -> dict[str, Any]:
    base = require_project(project_id)
    entries = []
    for item in list(knowledge_base.get("entries") or [])[:500]:
        if isinstance(item, dict):
            origin = str(item.get("origin") or "manual")
            user_edited = bool(item.get("user_edited", origin == "manual"))
            normalized = _normalize_knowledge_entry(item, user_edited=user_edited)
            if normalized:
                entries.append(normalized)
    sources = []
    for item in list(knowledge_base.get("sources") or [])[:100]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if url.startswith(("https://", "http://")):
            sources.append({"url": url[:2000], "title": str(item.get("title") or url).strip()[:300]})
    result = {
        "schema_version": "1.0",
        "project_id": project_id,
        "work_title": str(knowledge_base.get("work_title") or "").strip()[:300],
        "summary": str(knowledge_base.get("summary") or "").strip()[:4000],
        "entries": entries,
        "sources": sources,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": "user",
    }
    linked_database_id = _read_knowledge_link(project_id)
    if linked_database_id:
        current = load_project_knowledge_base(project_id)
        result["database_id"] = linked_database_id
        result["database_name"] = str(current.get("database_name") or current.get("work_title") or linked_database_id)
    atomic_write_json(_knowledge_path(project_id), result, backup=True)
    audit_event("gemini.knowledge.saved", project_id=project_id, context={"entries": len(entries), "sources": len(sources), "database_id": linked_database_id})
    return load_project_knowledge_base(project_id)


def research_project_knowledge(
    project_id: str,
    work_title: str,
    model: str | None = None,
    instructions: str = "",
) -> dict[str, Any]:
    base = require_project(project_id)
    title = str(work_title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="検索する作品名を入力してください")
    selected_model = str(model or _read_config().get("model") or DEFAULT_MODEL).strip()
    try:
        from google import genai
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="google-genaiが未導入です。setup.batまたはpip install -r requirements.txtを実行してください") from exc

    search_prompt = f"""Google検索を使い、作品「{title}」の字幕校正に必要な情報を調査してください。
登場キャラクターの正式名・読み・別名と、作品固有の用語・地名・組織名・技名を収集してください。
同名作品を混同せず、公式サイト、出版社、放送局、信頼できる作品データベースを優先してください。
推測は事実として書かず、字幕の表記修正に必要な範囲へ絞ってください。
追加条件: {instructions.strip() or '特になし'}"""
    client = genai.Client(api_key=_api_key())
    try:
        search_result = client.interactions.create(
            model=selected_model,
            input=search_prompt,
            tools=[{"type": "google_search"}],
        )
        citations = _extract_url_citations(search_result)
        report = str(getattr(search_result, "output_text", "") or "").strip()
        if not report:
            raise ValueError("検索結果が空です")
        structure_prompt = """次のWeb調査レポートを、字幕校正用のキャラクター・用語DBへ変換してください。
typeは人物ならcharacter、それ以外の固有語はtermにしてください。
canonical_nameは字幕で使う正式表記、aliasesは誤認識候補・読み・別表記です。
一般語や根拠のない項目は登録しないでください。source_urlsには提示された出典URLだけを使用してください。

出典URL:
""" + json.dumps(citations, ensure_ascii=False) + "\n\n調査レポート:\n" + report
        structured = client.interactions.create(
            model=selected_model,
            input=structure_prompt,
            response_format={"type": "text", "mime_type": "application/json", "schema": _knowledge_schema()},
        )
        generated = json.loads(structured.output_text)
    except Exception as exc:
        audit_event("gemini.knowledge.research_failed", project_id=project_id, context={"model": selected_model, "error_type": type(exc).__name__})
        error_text = str(exc).lower()
        if "429" in error_text or "quota" in error_text or "too_many_requests" in error_text:
            raise HTTPException(
                status_code=429,
                detail="Gemini APIの利用上限に達しています。無料枠の回復後に再実行するか、Google AI Studioで利用状況を確認してください。",
            ) from exc
        raise HTTPException(status_code=502, detail=f"キャラクター・用語のWeb調査に失敗しました: {exc}") from exc

    allowed_urls = {item["url"] for item in citations}
    generated_entries = []
    for item in list(generated.get("entries") or [])[:300]:
        if not isinstance(item, dict):
            continue
        item = dict(item)
        item["origin"] = "gemini_web"
        item["enabled"] = True
        item["user_edited"] = False
        item["source_urls"] = [url for url in _string_list(item.get("source_urls"), 20) if url in allowed_urls]
        normalized = _normalize_knowledge_entry(item)
        if normalized:
            generated_entries.append(normalized)

    existing = load_project_knowledge_base(project_id)
    existing_by_key = {
        (str(item.get("type")), str(item.get("canonical_name", "")).casefold()): item
        for item in existing.get("entries") or [] if isinstance(item, dict)
    }
    merged = []
    generated_keys: set[tuple[str, str]] = set()
    for item in generated_entries:
        key = (item["type"], item["canonical_name"].casefold())
        generated_keys.add(key)
        current = existing_by_key.get(key)
        if current and current.get("user_edited"):
            preserved = _normalize_knowledge_entry(current)
            if preserved:
                preserved["source_urls"] = _string_list([*preserved["source_urls"], *item["source_urls"]], 20)
                merged.append(preserved)
        else:
            if current:
                item["id"] = str(current.get("id") or item["id"])
                item["enabled"] = current.get("enabled", True) is not False
            merged.append(item)
    for key, item in existing_by_key.items():
        if key not in generated_keys:
            normalized = _normalize_knowledge_entry(item)
            if normalized:
                merged.append(normalized)

    result = {
        "schema_version": "1.0",
        "project_id": project_id,
        "work_title": str(generated.get("work_title") or title).strip()[:300],
        "summary": str(generated.get("summary") or report).strip()[:4000],
        "entries": merged,
        "sources": citations,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": "gemini_web",
        "model": selected_model,
    }
    linked_database_id = _read_knowledge_link(project_id)
    if linked_database_id:
        current = load_project_knowledge_base(project_id)
        result["database_id"] = linked_database_id
        result["database_name"] = str(current.get("database_name") or current.get("work_title") or linked_database_id)
    atomic_write_json(_knowledge_path(project_id), result, backup=True)
    audit_event("gemini.knowledge.researched", project_id=project_id, context={"model": selected_model, "entries": len(merged), "sources": len(citations)})
    return load_project_knowledge_base(project_id)


def _knowledge_base_instruction(project_id: str) -> str:
    knowledge = load_project_knowledge_base(project_id)
    entries = []
    for item in knowledge.get("entries") or []:
        if not isinstance(item, dict) or item.get("enabled", True) is False:
            continue
        entries.append({
            "type": item.get("type"),
            "canonical_name": item.get("canonical_name"),
            "aliases": item.get("aliases") or [],
            "description": item.get("description") or "",
        })
        if len(entries) >= 300:
            break
    if not entries:
        return "登録済みキャラクター・用語DB: なし"
    return """登録済みキャラクター・用語DB（人間が編集した正式表記を優先）:
aliasesや音声の読みが一致する場合はcanonical_nameへ修正してください。DBにない固有名詞を推測で追加しないでください。
""" + json.dumps(entries, ensure_ascii=False)


def transcribe_project_with_gemini(project_id: str, model: str | None = None, language: str = "ja") -> dict[str, Any]:
    base = require_project(project_id)
    audio_path = base / "audio" / "source_range.wav"
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="解析用音声がありません。先に音声抽出を実行してください")
    config = _read_config()
    selected_model = str(model or config.get("model") or DEFAULT_MODEL).strip()
    speaker_labels_enabled = bool(config.get("speaker_labels_enabled", DEFAULT_SPEAKER_LABELS_ENABLED))
    srt_timing_priority = bool(config.get("srt_timing_priority", DEFAULT_SRT_TIMING_PRIORITY))
    try:
        from google import genai
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="google-genaiが未導入です。setup.batまたはpip install -r requirements.txtを実行してください") from exc

    speaker_instruction = (
        "発話ごとに匿名の話者ラベルも返してください。同一人物には音声全体で同じラベルを使ってください。"
        if speaker_labels_enabled
        else """話者の推定や話者ラベルは一切返さず、字幕本文だけに集中してください。
禁止事項: textの先頭や本文中に、SPEAKER_01、話者1、男性、女性、登場人物名などの話者名を付けないでください。
禁止事項: 「話者名: 台詞」「[話者名] 台詞」「（男性）台詞」のような形式にしないでください。
textには実際に発話された台詞だけを入れてください。"""
    )
    timing_instruction = ""
    if srt_timing_priority:
        timing_instruction = """
返却する各segmentを、そのままSRTの1字幕キューとして使える単位にしてください。
start_secは実際に声が聞こえ始める位置、end_secはその発話が聞こえ終わる位置に合わせてください。
離れた発話を1つに結合せず、話者交代、明確な間、文意の区切りでsegmentを分けてください。
segmentは時刻順に並べ、互いに重複させず、start_sec < end_secを守ってください。
短い相づちも独立して聞こえる場合は省略せず、長すぎる本文は読みやすい文節で分けてください。"""
    prompt = f"""音声を{language or 'ja'}の字幕として正確に文字起こししてください。
{speaker_instruction}{timing_instruction}
BGM、歌、効果音だけの区間を台詞として捏造しないでください。聞き取れない語を推測で繰り返さないでください。
字幕本文は読みやすい句読点を付け、同じ発話を細かく分割しすぎないでください。"""
    client = genai.Client(api_key=_api_key())
    uploaded = None
    try:
        uploaded = client.files.upload(file=str(audio_path))
        interaction = client.interactions.create(
            model=selected_model,
            input=[
                {"type": "text", "text": prompt},
                {"type": "audio", "uri": uploaded.uri, "mime_type": uploaded.mime_type},
            ],
            response_format={"type": "text", "mime_type": "application/json", "schema": _transcript_schema(speaker_labels_enabled)},
        )
        result = json.loads(interaction.output_text)
    except Exception as exc:
        audit_event("gemini.transcription.failed", project_id=project_id, context={"model": selected_model, "error_type": type(exc).__name__})
        raise HTTPException(status_code=502, detail=f"Gemini文字起こしに失敗しました: {exc}") from exc
    finally:
        if uploaded is not None and getattr(uploaded, "name", None):
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                audit_event("gemini.upload.cleanup_failed", project_id=project_id, context={"model": selected_model})

    subtitles = []
    previous_end = 0.0
    for index, segment in enumerate(result.get("segments") or [], start=1):
        text = str(segment.get("text") or "").strip()
        if not speaker_labels_enabled:
            text = _strip_generated_speaker_prefix(text)
        if not text:
            continue
        start = max(0.0, float(segment.get("start_sec") or 0))
        end = max(start + 0.05, float(segment.get("end_sec") or start + 0.05))
        start = max(start, previous_end if start < previous_end - 0.2 else start)
        end = max(end, start + 0.05)
        previous_end = end
        subtitles.append({
            "id": f"sub_{len(subtitles) + 1:04d}",
            "enabled": True,
            "whisper_start_sec": round(start, 3),
            "whisper_end_sec": round(end, 3),
            "range_relative_start_sec": round(start, 3),
            "range_relative_end_sec": round(end, 3),
            "output_start_sec": round(start, 3),
            "output_end_sec": round(end, 3),
            "text": text,
            "speaker_label": str(segment.get("speaker") or "") if speaker_labels_enabled else "",
            "speaker_label_prefix": False,
            "transcription_engine": "gemini",
        })
    if not subtitles:
        raise HTTPException(status_code=502, detail="Geminiから有効な字幕が返りませんでした")
    transcript = {
        "engine": "gemini",
        "model": selected_model,
        "language": language,
        "summary": str(result.get("summary") or ""),
        "speaker_labels_enabled": speaker_labels_enabled,
        "srt_timing_priority": srt_timing_priority,
        "subtitles": subtitles,
        "raw_subtitles": subtitles,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    transcript_path = base / "transcript" / "transcript.json"
    srt_path = base / "subtitles" / "original.srt"
    atomic_write_json(transcript_path, transcript, backup=True)
    write_srt(subtitles, srt_path)
    proposal = {
        "schema_version": "1.0",
        "project_id": project_id,
        "model": selected_model,
        "created_at": transcript["created_at"],
        "summary": transcript["summary"],
        "transcript_segments": [
            {"start_sec": item["range_relative_start_sec"], "end_sec": item["range_relative_end_sec"], "text": item["text"], "speaker": item["speaker_label"]}
            for item in subtitles
        ],
        "subtitle_edits": [],
        "chapters": [],
        "cut_proposals": [],
    }
    atomic_write_json(base / "ai" / "gemini_proposal.json", proposal, backup=True)
    audit_event(
        "gemini.transcription.completed",
        project_id=project_id,
        context={
            "model": selected_model,
            "subtitle_count": len(subtitles),
            "speaker_labels_enabled": speaker_labels_enabled,
            "srt_timing_priority": srt_timing_priority,
        },
    )
    return {
        **transcript,
        "transcript_path": str(transcript_path),
        "srt_path": str(srt_path),
        "proposal": proposal,
    }


def _source_subtitles(plan: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for index, sub in enumerate(plan.get("subtitles") or []):
        if sub.get("enabled", True) is False:
            continue
        result.append({
            "id": str(sub.get("id") or f"sub_{index + 1:04d}"),
            "start_sec": float(sub.get("range_relative_start_sec", sub.get("start_sec", 0)) or 0),
            "end_sec": float(sub.get("range_relative_end_sec", sub.get("end_sec", 0)) or 0),
            "text": str(sub.get("text") or ""),
            "speaker": str(sub.get("speaker_label") or sub.get("speaker_id") or ""),
        })
    return result


def analyze_project_with_gemini(
    project_id: str,
    model: str | None = None,
    instructions: str = "",
    task: str = "subtitle",
) -> dict[str, Any]:
    base = require_project(project_id)
    audio_path = base / "audio" / "source_range.wav"
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="解析用音声がありません。先に文字起こしを実行してください")
    plan = load_project_edit_plan(project_id)
    subtitles = _source_subtitles(plan)
    if not subtitles:
        raise HTTPException(status_code=400, detail="比較対象の字幕がありません")
    selected_task = str(task or "subtitle").strip().lower()
    if selected_task not in {"subtitle", "cut"}:
        raise HTTPException(status_code=400, detail="Gemini解析種別はsubtitleまたはcutを指定してください")
    selected_model = str(model or _read_config().get("model") or DEFAULT_MODEL).strip()
    try:
        from google import genai
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="google-genaiが未導入です。setup.batまたはpip install -r requirements.txtを実行してください") from exc

    if selected_task == "subtitle":
        task_instruction = """字幕校正だけを行ってください。
固有名詞、誤認識、脱字、句読点を修正し、同じ発話として自然な短文は結合し、長すぎる字幕は分割してください。
必要なら話題の切り替わりにチャプターを提案してください。
cut_proposalsは必ず空配列にし、カット判断は行わないでください。"""
    else:
        task_instruction = """動画のカット提案だけを行ってください。
本編と無関係な長い無言、明確な言い直し、重複発言をremove候補にしてください。
台詞、短い間、演出上必要な余韻、判断できない区間は削除せずkeepにしてください。
見どころはhighlightで示してください。字幕本文は変更せず、subtitle_editsとchaptersは必ず空配列にしてください。"""

    prompt = """あなたは日本語動画の編集者です。添付音声と既存字幕を照合してください。
字幕IDは必ず保持して参照し、存在しないIDを作らないでください。
時刻は指定範囲の先頭を0秒とした元タイムラインです。無音だけを理由に字幕のある発話を削除しないでください。
""" + task_instruction + "\n" + _knowledge_base_instruction(project_id) + """
ユーザー追加指示:
""" + (instructions.strip() or "特になし") + "\n\n既存字幕JSON:\n" + json.dumps(subtitles, ensure_ascii=False)

    client = genai.Client(api_key=_api_key())
    uploaded = None
    try:
        uploaded = client.files.upload(file=str(audio_path))
        interaction = client.interactions.create(
            model=selected_model,
            input=[
                {"type": "text", "text": prompt},
                {"type": "audio", "uri": uploaded.uri, "mime_type": uploaded.mime_type},
            ],
            response_format={"type": "text", "mime_type": "application/json", "schema": _proposal_schema()},
        )
        proposal = json.loads(interaction.output_text)
    except HTTPException:
        raise
    except Exception as exc:
        audit_event("gemini.analysis.failed", project_id=project_id, context={"model": selected_model, "error_type": type(exc).__name__})
        raise HTTPException(status_code=502, detail=f"Gemini解析に失敗しました: {exc}") from exc
    finally:
        if uploaded is not None and getattr(uploaded, "name", None):
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                audit_event("gemini.upload.cleanup_failed", project_id=project_id, context={"model": selected_model})

    valid_ids = {item["id"] for item in subtitles}
    proposal["schema_version"] = "1.1"
    proposal["project_id"] = project_id
    proposal["model"] = selected_model
    proposal["created_at"] = datetime.now(timezone.utc).isoformat()
    proposal["last_task"] = selected_task
    for category in ("subtitle_edits", "chapters", "cut_proposals"):
        cleaned = []
        for index, item in enumerate(proposal.get(category) or []):
            if not isinstance(item, dict):
                continue
            item["id"] = f"{category}_{index + 1:04d}"
            item["source_subtitle_ids"] = [str(value) for value in item.get("source_subtitle_ids") or [] if str(value) in valid_ids]
            cleaned.append(item)
        proposal[category] = cleaned
    path = base / "ai" / "gemini_proposal.json"
    existing = load_gemini_proposal(project_id) or {}
    if selected_task == "subtitle":
        proposal["cut_proposals"] = list(existing.get("cut_proposals") or [])
        proposal["cut_summary"] = str(existing.get("cut_summary") or "")
        proposal["subtitle_summary"] = str(proposal.get("summary") or "")
    else:
        proposal["subtitle_edits"] = list(existing.get("subtitle_edits") or [])
        proposal["chapters"] = list(existing.get("chapters") or [])
        proposal["subtitle_summary"] = str(existing.get("subtitle_summary") or existing.get("summary") or "")
        proposal["cut_summary"] = str(proposal.get("summary") or "")
    if not proposal.get("transcript_segments"):
        proposal["transcript_segments"] = list(existing.get("transcript_segments") or [])
    proposal["summary"] = proposal.get("subtitle_summary") or proposal.get("cut_summary") or ""
    atomic_write_json(path, proposal, backup=True)
    audit_event("gemini.analysis.completed", project_id=project_id, context={
        "model": selected_model,
        "task": selected_task,
        "subtitle_edits": len(proposal.get("subtitle_edits") or []),
        "chapters": len(proposal.get("chapters") or []),
        "cut_proposals": len(proposal.get("cut_proposals") or []),
    })
    return {"proposal": proposal, "proposal_path": "ai/gemini_proposal.json"}


def load_gemini_proposal(project_id: str) -> dict[str, Any] | None:
    path = require_project(project_id) / "ai" / "gemini_proposal.json"
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Gemini提案JSONを読み込めません") from exc
    return value if isinstance(value, dict) else None


def _timeline_value(sub: dict[str, Any], key: str, fallback: float) -> float:
    try:
        return float(sub.get(key, fallback))
    except (TypeError, ValueError):
        return fallback


def apply_gemini_proposal(
    project_id: str,
    subtitle_edit_ids: list[str],
    chapter_ids: list[str],
    cut_ids: list[str],
) -> dict[str, Any]:
    base = require_project(project_id)
    proposal = load_gemini_proposal(project_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Gemini提案がありません")
    plan = load_project_edit_plan(project_id)
    subtitles = list(plan.get("subtitles") or [])
    by_id = {str(item.get("id")): item for item in subtitles}
    selected_edits = {str(value) for value in subtitle_edit_ids}
    consumed: set[str] = set()
    replacements_by_first: dict[str, list[dict[str, Any]]] = {}
    for edit in proposal.get("subtitle_edits") or []:
        if str(edit.get("id")) not in selected_edits or edit.get("action") == "keep":
            continue
        source_ids = [value for value in edit.get("source_subtitle_ids") or [] if value in by_id and value not in consumed]
        replacement_specs = [item for item in edit.get("replacements") or [] if str(item.get("text") or "").strip()]
        if not source_ids or not replacement_specs:
            continue
        source = [by_id[value] for value in source_ids]
        first = source_ids[0]
        consumed.update(source_ids)
        template = dict(source[0])
        timelines = [
            ("range_relative_start_sec", "range_relative_end_sec", "start_sec", "end_sec"),
            ("output_start_sec", "output_end_sec", "output_start_sec", "output_end_sec"),
            ("source_start_sec", "source_end_sec", "source_start_sec", "source_end_sec"),
        ]
        weights = [max(1, len(str(item.get("text") or ""))) for item in replacement_specs]
        total_weight = sum(weights)
        generated = []
        for index, spec in enumerate(replacement_specs):
            item = dict(template)
            item["id"] = first if index == 0 else f"{first}_ai_{index + 1}_{uuid.uuid4().hex[:6]}"
            item["text"] = str(spec.get("text") or "").strip()
            if spec.get("speaker"):
                item["speaker_label"] = str(spec.get("speaker"))
            before = sum(weights[:index]) / total_weight
            after = sum(weights[: index + 1]) / total_weight
            for start_key, end_key, fallback_start, fallback_end in timelines:
                start = min(_timeline_value(value, start_key, _timeline_value(value, fallback_start, 0)) for value in source)
                end = max(_timeline_value(value, end_key, _timeline_value(value, fallback_end, start)) for value in source)
                item[start_key] = round(start + (end - start) * before, 3)
                item[end_key] = round(start + (end - start) * after, 3)
            item["ai_edit_id"] = edit.get("id")
            generated.append(item)
        replacements_by_first[first] = generated
    updated_subtitles: list[dict[str, Any]] = []
    for sub in subtitles:
        sub_id = str(sub.get("id"))
        if sub_id in replacements_by_first:
            updated_subtitles.extend(replacements_by_first[sub_id])
        elif sub_id not in consumed:
            updated_subtitles.append(sub)
    plan["subtitles"] = updated_subtitles

    selected_chapters = {str(value) for value in chapter_ids}
    chapters = []
    updated_by_id = {str(item.get("id")): item for item in updated_subtitles}
    for chapter in proposal.get("chapters") or []:
        if str(chapter.get("id")) not in selected_chapters:
            continue
        source = next((updated_by_id[value] for value in chapter.get("source_subtitle_ids") or [] if value in updated_by_id), None)
        if not source:
            continue
        chapters.append({
            "id": str(chapter.get("id")), "title": str(chapter.get("title") or "チャプター"),
            "start_sec": _timeline_value(source, "output_start_sec", _timeline_value(source, "start_sec", 0)),
            "summary": str(chapter.get("summary") or ""),
        })
    if chapters:
        plan["chapters"] = chapters
    plan["gemini_proposal_applied_at"] = datetime.now(timezone.utc).isoformat()
    atomic_write_json(base / "edit_plan.json", plan, backup=True)

    selected_cuts = {str(value) for value in cut_ids}
    cut_segments = []
    for item in proposal.get("cut_proposals") or []:
        if str(item.get("id")) not in selected_cuts or item.get("action") != "remove":
            continue
        start = max(0.0, float(item.get("start_sec") or 0))
        end = max(start, float(item.get("end_sec") or start))
        if end - start >= 0.05:
            cut_segments.append({"start_sec": round(start, 3), "end_sec": round(end, 3), "source": "gemini", "proposal_id": item.get("id")})
    audit_event("gemini.proposal.applied", project_id=project_id, context={
        "subtitle_edits": len(selected_edits), "chapters": len(chapters), "cut_segments": len(cut_segments),
    })
    return {"edit_plan": plan, "cut_segments": cut_segments}
