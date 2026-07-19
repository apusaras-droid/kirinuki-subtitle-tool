from __future__ import annotations

from typing import Any


DISPLAY_MODES = {"source_above", "translation_above", "source_only", "translation_only"}


def normalize_bilingual_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    value = raw if isinstance(raw, dict) else {}
    display_mode = str(value.get("display_mode") or "source_above").strip().lower()
    if display_mode not in DISPLAY_MODES:
        display_mode = "source_above"

    def style(key: str, defaults: dict[str, Any]) -> dict[str, Any]:
        source = value.get(key) if isinstance(value.get(key), dict) else {}
        try:
            size = int(round(float(source.get("font_size", defaults["font_size"]))))
        except (TypeError, ValueError):
            size = defaults["font_size"]
        color = str(source.get("color") or defaults["color"]).strip()
        if len(color) != 7 or not color.startswith("#"):
            color = defaults["color"]
        return {
            "font_name": str(source.get("font_name") or defaults["font_name"]).strip()[:160],
            "font_size": max(8, min(160, size)),
            "color": color.upper(),
        }

    return {
        "enabled": bool(value.get("enabled", False)),
        "source_language": str(value.get("source_language") or "en").strip().lower()[:20],
        "target_language": str(value.get("target_language") or "ja").strip().lower()[:20],
        "display_mode": display_mode,
        "source_style": style("source_style", {"font_name": "Noto Sans JP", "font_size": 34, "color": "#FFF4C2"}),
        "target_style": style("target_style", {"font_name": "Noto Sans JP", "font_size": 44, "color": "#FFFFFF"}),
    }


def subtitle_source_text(item: dict[str, Any]) -> str:
    return str(item.get("source_text") or item.get("text") or "").strip()


def subtitle_display_text(item: dict[str, Any]) -> str:
    source = subtitle_source_text(item)
    translated = str(item.get("translated_text") or "").strip()
    if item.get("bilingual_enabled") is False:
        return source
    mode = str(item.get("subtitle_display_mode") or "source_above").strip().lower()
    if mode not in DISPLAY_MODES:
        mode = "source_above"
    if not translated:
        return source
    if mode == "source_only":
        return source
    if mode == "translation_only":
        return translated
    lines = (translated, source) if mode == "translation_above" else (source, translated)
    return "\n".join(line for line in lines if line)
