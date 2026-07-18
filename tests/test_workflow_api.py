import unittest
from unittest.mock import patch

from fastapi import HTTPException

from backend.app.main import ProjectSettingsRequest, ProjectWorkflowRequest, update_project_settings, update_project_workflow


class ProjectWorkflowApiTests(unittest.TestCase):
    def test_normalizes_workflow_before_persisting(self):
        request = ProjectWorkflowRequest(
            project_id="sample_project",
            workflow={
                "revision": 4,
                "currentStepId": "STEP_SUBTITLE_EDIT",
                "stepStatus": {
                    "STEP_PROJECT": "completed",
                    "STEP_SUBTITLE_EDIT": "current",
                    "UNKNOWN": "completed",
                },
                "execution": {
                    "status": "running",
                    "snapshot": {"outputMode": "video_srt"},
                },
            },
        )
        with patch("backend.app.main.update_project_info") as update:
            update.side_effect = lambda project_id, values: values
            result = update_project_workflow(request)

        workflow = result["workflow"]
        self.assertEqual(workflow["revision"], 4)
        self.assertEqual(workflow["schemaVersion"], "1.2.0")
        self.assertEqual(workflow["currentStepId"], "STEP_SUBTITLE_EDIT")
        self.assertNotIn("UNKNOWN", workflow["stepStatus"])
        self.assertEqual(workflow["execution"]["snapshot"]["outputMode"], "video_srt")

    def test_rejects_unknown_current_step(self):
        request = ProjectWorkflowRequest(
            project_id="sample_project",
            workflow={"currentStepId": "STEP_UNKNOWN"},
        )
        with self.assertRaises(HTTPException) as context:
            update_project_workflow(request)
        self.assertEqual(context.exception.status_code, 400)

    def test_accepts_cut_step(self):
        request = ProjectWorkflowRequest(
            project_id="sample_project",
            workflow={
                "currentStepId": "STEP_CUT",
                "stepStatus": {"STEP_CUT": "current"},
            },
        )
        with patch("backend.app.main.update_project_info") as update:
            update.side_effect = lambda project_id, values: values
            result = update_project_workflow(request)
        self.assertEqual(result["workflow"]["currentStepId"], "STEP_CUT")

    def test_accepts_ai_subtitle_step(self):
        request = ProjectWorkflowRequest(
            project_id="sample_project",
            workflow={
                "currentStepId": "STEP_AI_SUBTITLE",
                "stepStatus": {"STEP_AI_SUBTITLE": "current"},
            },
        )
        with patch("backend.app.main.update_project_info") as update:
            update.side_effect = lambda project_id, values: values
            result = update_project_workflow(request)
        self.assertEqual(result["workflow"]["currentStepId"], "STEP_AI_SUBTITLE")

    def test_saves_transcription_mode_in_ui_state(self):
        request = ProjectSettingsRequest(project_id="sample_project", transcription_mode="gemini")
        with (
            patch("backend.app.main.project_info", return_value={"ui_state": {}}),
            patch("backend.app.main.update_project_info") as update,
        ):
            update.side_effect = lambda project_id, values: values
            result = update_project_settings(request)
        self.assertEqual(result["project"]["ui_state"]["transcription_mode"], "gemini")

    def test_saves_subtitle_click_playback_mode_in_ui_state(self):
        request = ProjectSettingsRequest(project_id="sample_project", subtitle_click_playback_mode="loop")
        with (
            patch("backend.app.main.project_info", return_value={"ui_state": {}}),
            patch("backend.app.main.update_project_info") as update,
        ):
            update.side_effect = lambda project_id, values: values
            result = update_project_settings(request)
        self.assertEqual(result["project"]["ui_state"]["subtitle_click_playback_mode"], "loop")

    def test_rejects_unknown_subtitle_click_playback_mode(self):
        request = ProjectSettingsRequest(project_id="sample_project", subtitle_click_playback_mode="repeat_forever")
        with patch("backend.app.main.project_info", return_value={"ui_state": {}}):
            with self.assertRaises(HTTPException) as context:
                update_project_settings(request)
        self.assertEqual(context.exception.status_code, 400)

    def test_normalizes_ass_subtitle_defaults(self):
        request = ProjectSettingsRequest(
            project_id="sample_project",
            ass_subtitle_defaults={
                "font_name": "Noto Serif JP",
                "font_size": 999,
                "primary_color": "not-a-color",
                "outline_width": -4,
                "alignment": 12,
            },
        )
        with (
            patch("backend.app.main.project_info", return_value={"ui_state": {}}),
            patch("backend.app.main.update_project_info") as update,
        ):
            update.side_effect = lambda project_id, values: values
            result = update_project_settings(request)
        style = result["project"]["ui_state"]["ass_subtitle_defaults"]
        self.assertEqual(style["font_name"], "Noto Serif JP")
        self.assertEqual(style["font_size"], 160)
        self.assertEqual(style["primary_color"], "#FFFFFF")
        self.assertEqual(style["outline_width"], 0)
        self.assertEqual(style["alignment"], 9)


if __name__ == "__main__":
    unittest.main()
