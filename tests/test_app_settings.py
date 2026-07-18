import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from backend.app import app_settings


class AppSettingsTests(unittest.TestCase):
    def test_defaults_to_resume_last(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app.json"
            with patch.object(app_settings, "APP_SETTINGS_PATH", path):
                result = app_settings.load_app_settings()

        self.assertEqual(result["startup_mode"], "resume_last")
        self.assertIsNone(result["last_project_id"])
        self.assertEqual(result["default_output_directory"], "")
        self.assertTrue(result["output_create_project_subdirectory"])

    def test_saves_startup_mode_and_validated_last_project(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings" / "app.json"
            project_path = Path(temp_dir) / "projects" / "sample"
            project_path.mkdir(parents=True)
            with (
                patch.object(app_settings, "APP_SETTINGS_PATH", path),
                patch.object(app_settings, "require_project", return_value=project_path),
                patch.object(app_settings, "audit_event"),
            ):
                result = app_settings.save_app_settings(
                    startup_mode="new_project",
                    last_project_id="sample",
                    update_last_project=True,
                )
                stored = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(result["startup_mode"], "new_project")
        self.assertEqual(stored["last_project_id"], "sample")

    def test_rejects_invalid_startup_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app.json"
            with patch.object(app_settings, "APP_SETTINGS_PATH", path):
                with self.assertRaises(HTTPException) as raised:
                    app_settings.save_app_settings(startup_mode="unknown")

        self.assertEqual(raised.exception.status_code, 400)

    def test_saves_default_output_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings" / "app.json"
            output_path = Path(temp_dir) / "exports"
            with (
                patch.object(app_settings, "APP_SETTINGS_PATH", path),
                patch.object(app_settings, "audit_event"),
            ):
                result = app_settings.save_app_settings(
                    default_output_directory=str(output_path),
                    output_create_project_subdirectory=False,
                )

        self.assertEqual(result["default_output_directory"], str(output_path))
        self.assertFalse(result["output_create_project_subdirectory"])


if __name__ == "__main__":
    unittest.main()
