from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.app.services import build_plain_ass
from backend.app.srt import write_srt
from backend.app.subtitle_text import normalize_bilingual_settings, subtitle_display_text


def bilingual_subtitle(**overrides):
    item = {
        "id": "sub_0001",
        "output_start_sec": 1.0,
        "output_end_sec": 3.0,
        "text": "A shooting star.",
        "source_text": "A shooting star.",
        "translated_text": "流れ星だ。",
        "subtitle_display_mode": "source_above",
        "bilingual_enabled": True,
    }
    item.update(overrides)
    return item


def test_subtitle_display_text_supports_order_and_disable():
    assert subtitle_display_text(bilingual_subtitle()) == "A shooting star.\n流れ星だ。"
    assert subtitle_display_text(bilingual_subtitle(subtitle_display_mode="translation_above")) == "流れ星だ。\nA shooting star."
    assert subtitle_display_text(bilingual_subtitle(bilingual_enabled=False)) == "A shooting star."


def test_write_srt_preserves_two_lines():
    with TemporaryDirectory() as temp_dir:
        output = Path(temp_dir) / "bilingual.srt"
        write_srt([bilingual_subtitle()], output)
        text = output.read_text(encoding="utf-8-sig")
    assert "A shooting star.\n流れ星だ。" in text


def test_build_plain_ass_applies_independent_source_and_translation_styles():
    with TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        settings = normalize_bilingual_settings(
            {
                "enabled": True,
                "source_style": {"font_name": "Noto Sans JP", "font_size": 32, "color": "#FFF4C2"},
                "target_style": {"font_name": "Zen Kaku Gothic New", "font_size": 46, "color": "#FFFFFF"},
            }
        )
        project = {"ui_state": {"bilingual_subtitle_settings": settings}}
        with (
            patch("backend.app.services.require_project", return_value=base),
            patch("backend.app.services.project_info", return_value=project),
        ):
            output = build_plain_ass("sample", [bilingual_subtitle()], base / "bilingual.ass")
        dialogue = next(line for line in output.read_text(encoding="utf-8").splitlines() if line.startswith("Dialogue:"))
    assert r"{\fnNoto Sans JP\fs32\1c&H00C2F4FF&}A shooting star." in dialogue
    assert r"\N{\fnZen Kaku Gothic New\fs46\1c&H00FFFFFF&}流れ星だ。" in dialogue
