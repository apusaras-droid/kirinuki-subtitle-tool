import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.main import TranscriptSkipRequest, api_skip_transcript


class TranscriptSkipTests(unittest.TestCase):
    def test_skip_creates_empty_transcript_and_clears_existing_plan_subtitles(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            (base / "edit_plan.json").write_text(
                json.dumps({"segments": [], "subtitles": [{"text": "old"}], "speaker_roster": [{"id": "old"}]}),
                encoding="utf-8",
            )

            def resolve_path(_project_id, folder, filename):
                return base / folder / filename

            with (
                patch("backend.app.main.require_project", return_value=base),
                patch("backend.app.main.resolve_project_path", side_effect=resolve_path),
                patch("backend.app.main.load_project_edit_plan", return_value={"segments": [], "subtitles": [{"text": "old"}]}),
                patch("backend.app.main.update_project_info"),
                patch("backend.app.main.audit_event"),
            ):
                result = api_skip_transcript(TranscriptSkipRequest(project_id="sample"))

            transcript = json.loads((base / "transcript" / "transcript.json").read_text(encoding="utf-8"))
            plan = json.loads((base / "edit_plan.json").read_text(encoding="utf-8"))
            self.assertEqual(transcript["subtitle_mode"], "none")
            self.assertEqual(transcript["subtitles"], [])
            self.assertEqual(plan["subtitles"], [])
            self.assertEqual(result["transcript"]["status"], "skipped")
            self.assertEqual((base / "subtitles" / "original.srt").read_text(encoding="utf-8"), "")


if __name__ == "__main__":
    unittest.main()
