import json
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from backend.app import gemini_service


class GeminiProposalApplyTests(unittest.TestCase):
    def test_cut_analysis_preserves_existing_subtitle_proposals(self):
        response = {
            "summary": "冒頭の待機を削除",
            "transcript_segments": [],
            "subtitle_edits": [],
            "chapters": [],
            "cut_proposals": [{
                "action": "remove", "start_sec": 0.0, "end_sec": 1.5,
                "source_subtitle_ids": [], "reason": "長い待機", "confidence": 0.9,
            }],
        }
        existing = {
            "summary": "字幕を修正",
            "subtitle_summary": "字幕を修正",
            "subtitle_edits": [{
                "id": "subtitle_edits_0001", "action": "correct",
                "source_subtitle_ids": ["sub_1"], "replacements": [{"text": "正しい字幕", "speaker": ""}],
            }],
            "chapters": [],
            "cut_proposals": [],
        }
        plan = {"subtitles": [{
            "id": "sub_1", "text": "字幕", "range_relative_start_sec": 2.0,
            "range_relative_end_sec": 3.0,
        }]}
        captured = {}

        class FakeFiles:
            def upload(self, *, file):
                return SimpleNamespace(uri="fake://audio", mime_type="audio/wav", name="files/fake")

            def delete(self, *, name):
                return None

        class FakeInteractions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(output_text=json.dumps(response, ensure_ascii=False))

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            (base / "audio").mkdir()
            (base / "ai").mkdir()
            (base / "audio" / "source_range.wav").write_bytes(b"RIFF-test")
            (base / "ai" / "gemini_proposal.json").write_text(json.dumps(existing), encoding="utf-8")
            fake_client = SimpleNamespace(files=FakeFiles(), interactions=FakeInteractions())
            with (
                patch.object(gemini_service, "require_project", return_value=base),
                patch.object(gemini_service, "load_project_edit_plan", return_value=plan),
                patch.object(gemini_service, "_api_key", return_value="test-key"),
                patch.object(gemini_service, "_read_config", return_value={"model": "gemini-3.5-flash"}),
                patch.object(gemini_service, "_knowledge_base_instruction", return_value="DBなし"),
                patch("google.genai.Client", return_value=fake_client),
                patch.object(gemini_service, "audit_event"),
            ):
                result = gemini_service.analyze_project_with_gemini("sample", task="cut")

        proposal = result["proposal"]
        self.assertEqual(proposal["subtitle_edits"], existing["subtitle_edits"])
        self.assertEqual(proposal["cut_proposals"][0]["action"], "remove")
        self.assertEqual(proposal["last_task"], "cut")
        self.assertIn("カット提案だけ", captured["input"][0]["text"])

    def test_direct_transcription_writes_shared_transcript_contract(self):
        response = {
            "summary": "挨拶",
            "segments": [{"start_sec": 1.2, "end_sec": 2.8, "text": "こんにちは", "speaker": "SPEAKER_01"}],
        }

        class FakeFiles:
            def upload(self, *, file):
                return SimpleNamespace(uri="fake://audio", mime_type="audio/wav", name="files/fake")

            def delete(self, *, name):
                return None

        class FakeInteractions:
            def create(self, **kwargs):
                return SimpleNamespace(output_text=json.dumps(response, ensure_ascii=False))

        fake_client = SimpleNamespace(files=FakeFiles(), interactions=FakeInteractions())
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            (base / "audio").mkdir()
            (base / "audio" / "source_range.wav").write_bytes(b"RIFF-test")
            with (
                patch.object(gemini_service, "require_project", return_value=base),
                patch.object(gemini_service, "_api_key", return_value="test-key"),
                patch.object(gemini_service, "_read_config", return_value={"model": "gemini-3.5-flash"}),
                patch("google.genai.Client", return_value=fake_client),
                patch.object(gemini_service, "audit_event"),
            ):
                result = gemini_service.transcribe_project_with_gemini("sample")
            saved = json.loads((base / "transcript" / "transcript.json").read_text(encoding="utf-8"))
            srt = (base / "subtitles" / "original.srt").read_text(encoding="utf-8")

        self.assertEqual(result["engine"], "gemini")
        self.assertEqual(saved["subtitles"][0]["range_relative_start_sec"], 1.2)
        self.assertEqual(saved["subtitles"][0]["speaker_label_prefix"], False)
        self.assertIn("こんにちは", srt)
        self.assertNotIn("SPEAKER_01:", srt)

    def test_direct_transcription_discards_speaker_when_disabled(self):
        response = {
            "summary": "挨拶",
            "segments": [{"start_sec": 1.0, "end_sec": 2.0, "text": "SPEAKER_01: こんにちは", "speaker": "SPEAKER_01"}],
        }

        class FakeFiles:
            def upload(self, *, file):
                return SimpleNamespace(uri="fake://audio", mime_type="audio/wav", name="files/fake")

            def delete(self, *, name):
                return None

        captured_request = {}

        class FakeInteractions:
            def create(self, **kwargs):
                captured_request.update(kwargs)
                return SimpleNamespace(output_text=json.dumps(response, ensure_ascii=False))

        fake_client = SimpleNamespace(files=FakeFiles(), interactions=FakeInteractions())
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            (base / "audio").mkdir()
            (base / "audio" / "source_range.wav").write_bytes(b"RIFF-test")
            with (
                patch.object(gemini_service, "require_project", return_value=base),
                patch.object(gemini_service, "_api_key", return_value="test-key"),
                patch.object(
                    gemini_service,
                    "_read_config",
                    return_value={
                        "model": "gemini-3.5-flash",
                        "speaker_labels_enabled": False,
                        "srt_timing_priority": True,
                    },
                ),
                patch("google.genai.Client", return_value=fake_client),
                patch.object(gemini_service, "audit_event"),
            ):
                result = gemini_service.transcribe_project_with_gemini("sample")

        segment = result["subtitles"][0]
        schema = captured_request["response_format"]["schema"]["properties"]["segments"]["items"]
        prompt = captured_request["input"][0]["text"]
        self.assertEqual(segment["speaker_label"], "")
        self.assertEqual(segment["text"], "こんにちは")
        self.assertNotIn("speaker", schema["properties"])
        self.assertIn("SRTの1字幕キュー", prompt)
        self.assertIn("話者ラベルは一切返さず", prompt)
        self.assertIn("禁止事項", prompt)

    def test_direct_transcription_can_return_bilingual_subtitles(self):
        response = {
            "summary": "greeting",
            "segments": [{
                "start_sec": 1.0,
                "end_sec": 2.5,
                "source_text": "How are you?",
                "translated_text": "元気ですか？",
            }],
        }
        captured_request = {}

        class FakeFiles:
            def upload(self, *, file):
                return SimpleNamespace(uri="fake://audio", mime_type="audio/wav", name="files/fake")

            def delete(self, *, name):
                return None

        class FakeInteractions:
            def create(self, **kwargs):
                captured_request.update(kwargs)
                return SimpleNamespace(output_text=json.dumps(response, ensure_ascii=False))

        fake_client = SimpleNamespace(files=FakeFiles(), interactions=FakeInteractions())
        settings = {
            "enabled": True,
            "source_language": "en",
            "target_language": "ja",
            "display_mode": "source_above",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            (base / "audio").mkdir()
            (base / "audio" / "source_range.wav").write_bytes(b"RIFF-test")
            with (
                patch.object(gemini_service, "require_project", return_value=base),
                patch.object(gemini_service, "_api_key", return_value="test-key"),
                patch.object(
                    gemini_service,
                    "_read_config",
                    return_value={"model": "gemini-3.5-flash", "speaker_labels_enabled": False},
                ),
                patch("google.genai.Client", return_value=fake_client),
                patch.object(gemini_service, "audit_event"),
            ):
                result = gemini_service.transcribe_project_with_gemini(
                    "sample",
                    language="en",
                    bilingual_subtitle_settings=settings,
                )
            srt = (base / "subtitles" / "original.srt").read_text(encoding="utf-8")

        subtitle = result["subtitles"][0]
        schema = captured_request["response_format"]["schema"]["properties"]["segments"]["items"]
        prompt = captured_request["input"][0]["text"]
        self.assertEqual(subtitle["text"], "How are you?")
        self.assertEqual(subtitle["source_text"], "How are you?")
        self.assertEqual(subtitle["translated_text"], "元気ですか？")
        self.assertTrue(subtitle["bilingual_enabled"])
        self.assertIn("source_text", schema["required"])
        self.assertIn("translated_text", schema["required"])
        self.assertIn("How are you?\n元気ですか？", srt)
        self.assertIn("原文と翻訳のsegment数", prompt)

    def test_merge_uses_existing_timeline_and_returns_selected_cut(self):
        plan = {
            "subtitles": [
                {"id": "sub_1", "text": "こん", "range_relative_start_sec": 1.0, "range_relative_end_sec": 2.0, "output_start_sec": 0.0, "output_end_sec": 1.0},
                {"id": "sub_2", "text": "にちは", "range_relative_start_sec": 2.0, "range_relative_end_sec": 3.0, "output_start_sec": 1.0, "output_end_sec": 2.0},
            ]
        }
        proposal = {
            "subtitle_edits": [{
                "id": "subtitle_edits_0001", "action": "merge", "source_subtitle_ids": ["sub_1", "sub_2"],
                "replacements": [{"text": "こんにちは", "speaker": ""}],
            }],
            "chapters": [{"id": "chapters_0001", "title": "挨拶", "summary": "開始", "source_subtitle_ids": ["sub_1"]}],
            "cut_proposals": [{"id": "cut_proposals_0001", "action": "remove", "start_sec": 5.0, "end_sec": 7.0}],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            (base / "ai").mkdir()
            (base / "ai" / "gemini_proposal.json").write_text(json.dumps(proposal), encoding="utf-8")
            with (
                patch.object(gemini_service, "require_project", return_value=base),
                patch.object(gemini_service, "load_project_edit_plan", return_value=plan),
                patch.object(gemini_service, "audit_event"),
            ):
                result = gemini_service.apply_gemini_proposal(
                    "sample", ["subtitle_edits_0001"], ["chapters_0001"], ["cut_proposals_0001"]
                )

        merged = result["edit_plan"]["subtitles"]
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["text"], "こんにちは")
        self.assertEqual(merged[0]["range_relative_start_sec"], 1.0)
        self.assertEqual(merged[0]["range_relative_end_sec"], 3.0)
        self.assertEqual(result["edit_plan"]["chapters"][0]["start_sec"], 0.0)
        self.assertEqual(result["cut_segments"][0]["start_sec"], 5.0)


if __name__ == "__main__":
    unittest.main()
