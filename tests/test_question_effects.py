from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from PIL import Image

from backend.app import services


def _render_frames(effect: dict) -> tuple[list[bytes], list[str]]:
    with TemporaryDirectory() as temp_dir:
        output = Path(temp_dir) / "question.mov"
        with mock.patch.object(services, "run_command") as run_command, mock.patch.object(services.shutil, "rmtree"):
            services.render_question_overlay_video(
                "missing-test-project",
                effect,
                output,
                0.6,
                canvas_size=(240, 135),
                fps=10,
            )
            frame_paths = sorted(output.with_suffix("").glob("frame_*.png"))
            frames = []
            for frame_path in frame_paths:
                with Image.open(frame_path) as image:
                    frames.append(image.convert("RGBA").tobytes())
            command = run_command.call_args.args[0]
    return frames, command


def test_question_float_up_generates_moving_transparent_frames():
    frames, command = _render_frames(
        {
            "id": "question_float_up",
            "position_x": 0.5,
            "position_y": 0.82,
            "radius": 0.08,
            "symbol_count": 8,
            "spread": 0.4,
            "sway_strength": 0.06,
        }
    )

    assert len(frames) == 6
    assert len(set(frames)) > 1
    assert "qtrle" in command
    assert "argb" in command


def test_question_tilt_generates_animated_frames_at_selected_position():
    frames, _ = _render_frames(
        {
            "id": "question_tilt",
            "position_x": 0.7,
            "position_y": 0.3,
            "radius": 0.25,
            "speed": 1.1,
            "tilt_angle": 24,
        }
    )

    assert len(frames) == 6
    assert len(set(frames)) > 1


def test_question_effect_respects_scene_scope():
    plan = {
        "segments": [{"output_start_sec": 0.0, "output_end_sec": 12.0}],
        "scenes": [{"id": "scene_1", "start_sec": 3.0, "end_sec": 5.5}],
    }
    decoration = {
        "screen_effect_stacks": [
            {
                "id": "question_stack",
                "timing_mode": "full",
                "effects": [{"id": "question_tilt", "position_x": 0.7}],
            }
        ],
        "screen_effect_targets": {
            "global_stack_ids": [],
            "scene_stack_ids": {"scene_1": ["question_stack"]},
        },
    }

    intervals = services.screen_effect_intervals(plan, decoration, "question_tilt")

    assert intervals == [
        {
            "start_sec": 3.0,
            "end_sec": 5.5,
            "effect": {"id": "question_tilt", "position_x": 0.7},
        }
    ]


def test_large_question_is_marked_as_foreground_overlay():
    plan = {
        "segments": [{"output_start_sec": 0.0, "output_end_sec": 4.0}],
        "scenes": [{"id": "scene_1", "start_sec": 0.0, "end_sec": 4.0}],
    }
    decoration = {
        "screen_effect_stacks": [
            {
                "id": "question_stack",
                "effects": [{"id": "question_tilt", "position_x": 0.5, "position_y": 0.45}],
            }
        ],
        "screen_effect_targets": {
            "global_stack_ids": [],
            "scene_stack_ids": {"scene_1": ["question_stack"]},
        },
    }

    with TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)

        def fake_render(_project_id, _effect, output_path, _duration, **_kwargs):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.touch()
            return output_path

        with mock.patch.object(services, "require_project", return_value=base), mock.patch.object(
            services, "render_question_overlay_video", side_effect=fake_render
        ):
            overlays = services.generate_screen_effect_overlays("test", plan, decoration, canvas_size=(320, 180))

    assert len(overlays) == 1
    assert overlays[0]["type"] == "question_tilt"
    assert overlays[0]["layer"] == "foreground"
