import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.app import gemini_service


class GeminiConfigTests(unittest.TestCase):
    def test_secret_is_saved_but_never_returned(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "gemini.json"
            with (
                patch.object(gemini_service, "PRIVATE_DIR", config_path.parent),
                patch.object(gemini_service, "GEMINI_CONFIG_PATH", config_path),
                patch.dict("os.environ", {}, clear=False),
                patch.object(gemini_service, "audit_event"),
            ):
                result = gemini_service.save_gemini_config("secret-value-1234", "gemini-3.5-flash")
                stored = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(stored["api_key"], "secret-value-1234")
        self.assertTrue(result["configured"])
        self.assertEqual(result["masked_key"], "...1234")
        self.assertNotIn("api_key", result)
        self.assertNotIn("secret-value", json.dumps(result))

    def test_clear_removes_saved_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "gemini.json"
            config_path.write_text('{"api_key":"secret","model":"gemini-3.5-flash"}', encoding="utf-8")
            with (
                patch.object(gemini_service, "PRIVATE_DIR", config_path.parent),
                patch.object(gemini_service, "GEMINI_CONFIG_PATH", config_path),
                patch.dict("os.environ", {}, clear=False),
                patch.object(gemini_service, "audit_event"),
            ):
                result = gemini_service.save_gemini_config(None, None, clear_key=True)
                stored = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertNotIn("api_key", stored)
        self.assertFalse(result["configured"])

    def test_transcription_preferences_are_saved_and_returned(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "gemini.json"
            with (
                patch.object(gemini_service, "PRIVATE_DIR", config_path.parent),
                patch.object(gemini_service, "GEMINI_CONFIG_PATH", config_path),
                patch.dict("os.environ", {}, clear=False),
                patch.object(gemini_service, "audit_event"),
            ):
                result = gemini_service.save_gemini_config(
                    "secret",
                    "gemini-3.5-flash",
                    speaker_labels_enabled=False,
                    srt_timing_priority=True,
                )
                stored = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertFalse(stored["speaker_labels_enabled"])
        self.assertTrue(stored["srt_timing_priority"])
        self.assertFalse(result["speaker_labels_enabled"])
        self.assertTrue(result["srt_timing_priority"])

    def test_transcript_schema_can_omit_speaker(self):
        segment_schema = gemini_service._transcript_schema(include_speaker=False)["properties"]["segments"]["items"]

        self.assertNotIn("speaker", segment_schema["properties"])
        self.assertNotIn("speaker", segment_schema["required"])

    def test_proposal_schema_contains_all_correction_sections(self):
        schema = gemini_service._proposal_schema()

        self.assertIsInstance(schema, dict)
        self.assertEqual(
            set(schema["required"]),
            {"summary", "transcript_segments", "subtitle_edits", "chapters", "cut_proposals"},
        )

    def test_generated_speaker_prefixes_are_removed(self):
        self.assertEqual(gemini_service._strip_generated_speaker_prefix("SPEAKER_01: こんにちは"), "こんにちは")
        self.assertEqual(gemini_service._strip_generated_speaker_prefix("[話者1] こんにちは"), "こんにちは")
        self.assertEqual(gemini_service._strip_generated_speaker_prefix("（男性）こんにちは"), "こんにちは")
        self.assertEqual(gemini_service._strip_generated_speaker_prefix("男性が話している。"), "男性が話している。")

    def test_model_status_marks_models_returned_by_api_as_available(self):
        fake_client = SimpleNamespace(models=SimpleNamespace(list=lambda: [
            SimpleNamespace(name="models/gemini-3.1-flash-lite"),
            SimpleNamespace(name="models/gemini-3.5-flash"),
        ]))
        with (
            patch.object(gemini_service, "_api_key", return_value="test-key"),
            patch("google.genai.Client", return_value=fake_client),
        ):
            result = gemini_service.gemini_model_status()

        by_id = {item["id"]: item for item in result["models"]}
        self.assertTrue(result["checked"])
        self.assertEqual(by_id["gemini-3.1-flash-lite"]["availability"], "available")
        self.assertEqual(by_id["gemini-3.5-flash"]["availability"], "available")
        self.assertEqual(by_id["gemini-3.1-pro-preview"]["availability"], "unavailable")

    def test_model_probe_distinguishes_ready_and_rate_limited(self):
        class FakeInteractions:
            def create(self, *, model, input):
                if model == "gemini-3.5-flash":
                    raise RuntimeError("429 RESOURCE_EXHAUSTED quota")
                return SimpleNamespace(output_text="OK")

        fake_client = SimpleNamespace(
            models=SimpleNamespace(list=lambda: [SimpleNamespace(name=f"models/{item['id']}") for item in gemini_service.GEMINI_MODEL_REGISTRY]),
            interactions=FakeInteractions(),
        )
        with (
            patch.object(gemini_service, "_api_key", return_value="test-key"),
            patch("google.genai.Client", return_value=fake_client),
        ):
            result = gemini_service.gemini_model_status(probe=True)

        by_id = {item["id"]: item for item in result["models"]}
        self.assertTrue(result["probed"])
        self.assertEqual(by_id["gemini-3.1-flash-lite"]["probe_status"], "ready")
        self.assertEqual(by_id["gemini-3.5-flash"]["probe_status"], "rate_limited")


if __name__ == "__main__":
    unittest.main()
