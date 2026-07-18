from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.app.services import configured_export_directory, publish_export_result


def test_publish_external_subtitle_uses_project_folder_and_shared_stem():
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        workspace = root / "workspace"
        destination = root / "exports"
        workspace.mkdir()
        video = workspace / "final.mp4"
        subtitle = workspace / "final.srt"
        video.write_bytes(b"video")
        subtitle.write_text("subtitle", encoding="utf-8")
        result = {
            "video_path": str(video),
            "subtitle_path": str(subtitle),
            "subtitle_mode": "external",
        }
        with (
            patch("backend.app.services.project_info", return_value={"project_name": "テスト作品"}),
            patch("backend.app.services.audit_project_event"),
        ):
            published = publish_export_result(
                "sample",
                result,
                str(destination),
                "完成版",
                create_project_subdirectory=True,
            )

        output_dir = destination / "テスト作品"
        assert Path(published["video_path"]) == output_dir / "完成版.mp4"
        assert Path(published["subtitle_path"]) == output_dir / "完成版.srt"
        assert Path(published["video_path"]).read_bytes() == b"video"


def test_publish_adds_sequence_without_overwriting_existing_file():
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        video = root / "final.mkv"
        video.write_bytes(b"new")
        destination = root / "exports"
        destination.mkdir()
        (destination / "project.mkv").write_bytes(b"old")
        with (
            patch("backend.app.services.project_info", return_value={"project_name": "project"}),
            patch("backend.app.services.audit_project_event"),
        ):
            published = publish_export_result(
                "sample",
                {"video_path": str(video), "subtitle_mode": "embed"},
                str(destination),
            )

        assert Path(published["video_path"]).name == "project_2.mkv"
        assert (destination / "project.mkv").read_bytes() == b"old"


def test_configured_export_directory_falls_back_to_project_output():
    with TemporaryDirectory() as temp_dir:
        project = Path(temp_dir) / "project"
        with patch("backend.app.services.require_project", return_value=project):
            result = configured_export_directory("sample", {})

        assert result == project / "output"


def test_configured_export_directory_uses_sanitized_project_subfolder():
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir) / "exports"
        with (
            patch("backend.app.services.require_project", return_value=Path(temp_dir) / "project"),
            patch("backend.app.services.project_info", return_value={"project_name": "作品: 01"}),
        ):
            result = configured_export_directory(
                "sample",
                {
                    "default_output_directory": str(root),
                    "output_create_project_subdirectory": True,
                },
            )

        assert result == (root / "作品_ 01").resolve()
