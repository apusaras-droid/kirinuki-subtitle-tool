from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.app.services import build_decoration_ass, build_plain_ass, collision_layout_for_item


def test_build_decoration_ass_uses_project_default_and_subtitle_override():
    with TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        source_srt = base / "edited.srt"
        source_srt.write_text("1\n00:00:01,000 --> 00:00:03,000\nテスト\n", encoding="utf-8")
        event = {
            "id": "sub_0001",
            "start_sec": 1,
            "end_sec": 3,
            "text": "テスト",
            "ass_style": {
                "enabled": True,
                "font_name": "Noto Serif JP",
                "font_size": 52,
                "primary_color": "#FFF7DE",
                "outline_color": "#112233",
                "outline_width": 4,
                "shadow_depth": 2,
                "bold": False,
                "italic": True,
                "alignment": 8,
                "margin_l": 70,
                "margin_r": 80,
                "margin_v": 40,
                "spacing": 1.5,
            },
        }
        project = {
            "ui_state": {
                "ass_subtitle_defaults": {
                    "font_name": "Noto Sans JP",
                    "font_size": 44,
                    "primary_color": "#FFFFFF",
                    "outline_color": "#000000",
                    "outline_width": 3,
                    "shadow_depth": 1,
                    "bold": True,
                    "italic": False,
                    "alignment": 2,
                    "margin_l": 60,
                    "margin_r": 60,
                    "margin_v": 48,
                    "spacing": 0,
                }
            }
        }
        with (
            patch("backend.app.services.require_project", return_value=base),
            patch("backend.app.services.project_info", return_value=project),
        ):
            output = build_decoration_ass(
                "sample",
                {"source_srt": str(source_srt), "events": [event]},
                base / "output.ass",
            )

        ass_text = output.read_text(encoding="utf-8")
        style = next(line for line in ass_text.splitlines() if line.startswith("Style:"))
        dialogue = next(line for line in ass_text.splitlines() if line.startswith("Dialogue:"))
        assert "Noto Sans JP,44" in style
        assert r"\an8\pos(640.0,40.0)" in dialogue
        assert r"\fnNoto Serif JP\fs52" in dialogue
        assert r"\3c&H00332211&\bord4\shad2\b0\i1\fsp1.5" in dialogue


def test_build_plain_ass_uses_ass_style_without_decoration_fields():
    with TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        project = {
            "ui_state": {
                "ass_subtitle_defaults": {
                    "font_name": "Noto Sans JP",
                    "font_size": 44,
                    "primary_color": "#FFFFFF",
                    "outline_color": "#000000",
                    "outline_width": 3,
                    "shadow_depth": 1,
                    "bold": True,
                    "italic": False,
                    "alignment": 2,
                    "margin_l": 60,
                    "margin_r": 60,
                    "margin_v": 48,
                    "spacing": 0,
                }
            }
        }
        subtitle = {
            "output_start_sec": 1.0,
            "output_end_sec": 2.5,
            "text": "通常字幕★",
            "frame_preset_id": "frame_bubble_jagged",
            "effect_group_id": "effect_heart",
            "font_color": "#FF0000",
            "ass_style": {
                "enabled": True,
                "font_name": "Noto Serif JP",
                "font_size": 52,
                "primary_color": "#FFF7DE",
                "outline_color": "#112233",
                "outline_width": 4,
                "shadow_depth": 2,
                "alignment": 8,
                "margin_l": 70,
                "margin_r": 80,
                "margin_v": 40,
            },
        }
        with (
            patch("backend.app.services.require_project", return_value=base),
            patch("backend.app.services.project_info", return_value=project),
        ):
            output = build_plain_ass("sample", [subtitle], base / "plain.ass")

        text = output.read_text(encoding="utf-8")
        assert "WrapStyle: 0" in text
        dialogue = next(line for line in text.splitlines() if line.startswith("Dialogue:"))
        assert r"\fnNoto Serif JP\fs52" in dialogue
        assert r"\1c&H00DEF7FF&\3c&H00332211&\bord4" in dialogue
        assert "frame_bubble_jagged" not in text
        assert "effect_heart" not in text


def test_build_decoration_ass_enables_smart_caption_wrapping():
    with TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        source_srt = base / "edited.srt"
        source_srt.write_text(
            "1\n00:00:01,000 --> 00:00:03,000\n長い字幕の折り返し確認\n",
            encoding="utf-8",
        )
        with (
            patch("backend.app.services.require_project", return_value=base),
            patch("backend.app.services.project_info", return_value={"ui_state": {}}),
        ):
            output = build_decoration_ass(
                "sample",
                {"source_srt": str(source_srt), "events": []},
                base / "decorated.ass",
            )

        assert "WrapStyle: 0" in output.read_text(encoding="utf-8")


def test_build_plain_ass_stacks_overlapping_middle_captions_downward():
    with TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        subtitles = [
            {"id": "long", "output_start_sec": 0.0, "output_end_sec": 10.0, "text": "長い下段"},
            {"id": "short_b", "output_start_sec": 1.0, "output_end_sec": 2.0, "text": "短い上段B"},
            {"id": "short_c", "output_start_sec": 3.0, "output_end_sec": 4.0, "text": "短い上段C"},
            {"id": "short_d", "output_start_sec": 3.5, "output_end_sec": 4.5, "text": "さらに上段D"},
            {"id": "solo", "output_start_sec": 11.0, "output_end_sec": 12.0, "text": "通常"},
        ]
        with (
            patch("backend.app.services.require_project", return_value=base),
            patch(
                "backend.app.services.project_info",
                return_value={"ui_state": {"ass_subtitle_defaults": {"alignment": 5}}},
            ),
        ):
            output = build_plain_ass("sample", subtitles, base / "plain.ass")

        dialogues = [line for line in output.read_text(encoding="utf-8").splitlines() if line.startswith("Dialogue:")]
        assert r"\an5" in dialogues[0]
        assert r"\an5" in dialogues[1]
        assert r"\an5" in dialogues[2]
        assert r"\pos(640.0,360.0)" in dialogues[0]
        assert r"\pos(640.0,483.2)" in dialogues[1]
        assert r"\pos(640.0,483.2)" in dialogues[2]
        assert r"\an5" in dialogues[3]
        assert r"\pos(640.0,606.4)" in dialogues[3]
        assert r"\an5" in dialogues[4]


def test_build_plain_ass_stacks_overlapping_top_captions_downward():
    with TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        subtitles = [
            {"output_start_sec": 0.0, "output_end_sec": 3.0, "text": "上中央"},
            {"output_start_sec": 1.0, "output_end_sec": 2.0, "text": "下へ積む"},
        ]
        with (
            patch("backend.app.services.require_project", return_value=base),
            patch(
                "backend.app.services.project_info",
                return_value={"ui_state": {"ass_subtitle_defaults": {"alignment": 8}}},
            ),
        ):
            output = build_plain_ass("sample", subtitles, base / "top.ass")

        dialogues = [line for line in output.read_text(encoding="utf-8").splitlines() if line.startswith("Dialogue:")]
        assert r"\an8\pos(640.0,48.0)" in dialogues[0]
        assert r"\an8\pos(640.0,171.2)" in dialogues[1]


def test_build_plain_ass_stacks_overlapping_bottom_captions_upward():
    with TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        subtitles = [
            {"output_start_sec": 0.0, "output_end_sec": 3.0, "text": "下中央"},
            {"output_start_sec": 1.0, "output_end_sec": 2.0, "text": "上へ積む"},
        ]
        with (
            patch("backend.app.services.require_project", return_value=base),
            patch(
                "backend.app.services.project_info",
                return_value={"ui_state": {"ass_subtitle_defaults": {"alignment": 2}}},
            ),
        ):
            output = build_plain_ass("sample", subtitles, base / "bottom.ass")

        dialogues = [line for line in output.read_text(encoding="utf-8").splitlines() if line.startswith("Dialogue:")]
        assert r"\an2\pos(640.0,672.0)" in dialogues[0]
        assert r"\an2\pos(640.0,548.8)" in dialogues[1]


def test_decoration_layout_stack_direction_follows_vertical_anchor():
    item = {"subtitle_collision_lane": 1, "font_size": 44}
    _, top = collision_layout_for_item(item, {"anchor": "top_center", "offset_y_px": 20})
    _, middle = collision_layout_for_item(item, {"anchor": "middle_center", "offset_y_px": 10})
    _, bottom = collision_layout_for_item(item, {"anchor": "bottom_center", "offset_y_px": 18})

    assert top["offset_y_px"] == 152.0
    assert middle["offset_y_px"] == 142.0
    assert bottom["offset_y_px"] == -114.0
