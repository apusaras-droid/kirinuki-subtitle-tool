import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from backend.app.main import ProjectSettingsRequest, update_project_settings
from backend.app.services import extract_audio, prepare_audio_track_preview, probe_video


class AudioTrackSelectionTests(unittest.TestCase):
    def test_probe_returns_all_audio_tracks_and_default_index(self):
        probe_result = {
            "format": {"duration": "12.5", "size": "1000"},
            "streams": [
                {"index": 0, "codec_type": "video", "width": 1280, "height": 720, "avg_frame_rate": "30000/1001"},
                {
                    "index": 1,
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "sample_rate": "48000",
                    "channels": 2,
                    "channel_layout": "stereo",
                    "tags": {"language": "jpn", "title": "Japanese"},
                    "disposition": {"default": 0},
                },
                {
                    "index": 2,
                    "codec_type": "audio",
                    "codec_name": "ac3",
                    "sample_rate": "48000",
                    "channels": 6,
                    "channel_layout": "5.1(side)",
                    "tags": {"language": "eng", "title": "English"},
                    "disposition": {"default": 1, "comment": 0},
                },
            ],
        }
        with TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "input.mkv"
            video.write_bytes(b"video")
            completed = SimpleNamespace(stdout=json.dumps(probe_result))
            with (
                patch("backend.app.services.ensure_tool"),
                patch("backend.app.services.audit_event"),
                patch("backend.app.services.run_command", return_value=completed),
            ):
                result = probe_video(str(video))

        self.assertEqual(result["default_audio_stream_index"], 2)
        self.assertEqual(len(result["audio_tracks"]), 2)
        self.assertEqual(result["audio_tracks"][0]["language"], "jpn")
        self.assertEqual(result["audio_tracks"][1]["title"], "English")
        self.assertTrue(result["audio_tracks"][1]["is_default"])
        self.assertEqual(result["audio_sample_rate"], 48000)

    def test_extract_maps_selected_absolute_stream_index(self):
        captured = []

        def fake_run(args, *_args, **_kwargs):
            captured.append(args)
            return subprocess.CompletedProcess(args, 0, "", "")

        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            (base / "audio").mkdir()
            (base / "temp" / "logs").mkdir(parents=True)
            (base / "analysis" / "voice_isolation").mkdir(parents=True)
            with (
                patch("backend.app.services.ensure_tool"),
                patch("backend.app.services.require_project", return_value=base),
                patch(
                    "backend.app.services.probe_video",
                    return_value={
                        "audio_tracks": [{"stream_index": 1}, {"stream_index": 2}],
                        "default_audio_stream_index": 1,
                    },
                ),
                patch("backend.app.services.run_command", side_effect=fake_run),
                patch("backend.app.services.audit_project_event"),
            ):
                result = extract_audio("project", "input.mkv", 0.0, 5.0, "cpu", 2)

        command = captured[0]
        map_position = command.index("-map")
        self.assertEqual(command[map_position + 1], "0:2")
        self.assertEqual(result["audio_stream_index"], 2)

    def test_project_settings_save_audio_stream_index(self):
        request = ProjectSettingsRequest(project_id="sample_project", audio_stream_index=3)
        with (
            patch("backend.app.main.project_info", return_value={"ui_state": {}}),
            patch("backend.app.main.update_project_info") as update,
        ):
            update.side_effect = lambda _project_id, values: values
            result = update_project_settings(request)
        self.assertEqual(result["project"]["ui_state"]["audio_stream_index"], 3)

    def test_preview_audio_maps_selected_track(self):
        captured = []

        def fake_run(args, *_args, **_kwargs):
            captured.append(args)
            return subprocess.CompletedProcess(args, 0, "", "")

        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            source = base / "source" / "input.mkv"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"video")
            (base / "temp" / "logs").mkdir(parents=True)
            with (
                patch("backend.app.services.ensure_tool"),
                patch("backend.app.services.require_project", return_value=base),
                patch("backend.app.services.project_source_video", return_value=source),
                patch(
                    "backend.app.services.probe_video",
                    return_value={"audio_tracks": [{"stream_index": 2, "timeline_offset_sec": 0.125}]},
                ),
                patch("backend.app.services.run_command", side_effect=fake_run),
                patch("backend.app.services.audit_project_event"),
            ):
                result = prepare_audio_track_preview("project", 2)

        command = captured[0]
        map_position = command.index("-map")
        self.assertEqual(command[map_position + 1], "0:2")
        self.assertEqual(result["timeline_offset_sec"], 0.125)
        self.assertEqual(result["audio_url"], "/api/projects/project/media/preview/audio_track_2.m4a")


if __name__ == "__main__":
    unittest.main()
