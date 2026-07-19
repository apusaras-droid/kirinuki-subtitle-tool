import json
import sys
import types
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.app.gemini_service import translate_project_subtitles


class FakeInteractions:
    def create(self, **kwargs):
        payload = json.loads(kwargs["input"].split("入力:\n", 1)[1])
        translations = [
            {"id": item["id"], "translated_text": f"訳:{item['text']}"}
            for item in payload
        ]
        return types.SimpleNamespace(output_text=json.dumps({"translations": translations}, ensure_ascii=False))


class FakeClient:
    def __init__(self, **kwargs):
        self.interactions = FakeInteractions()


def test_translate_project_subtitles_preserves_source_and_timing():
    with TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        (base / "transcript").mkdir()
        (base / "subtitles").mkdir()
        original = {
            "subtitles": [
                {"id": "sub_1", "start_sec": 1.25, "end_sec": 2.75, "text": "Hello."},
            ]
        }
        (base / "transcript" / "transcript.json").write_text(json.dumps(original), encoding="utf-8")
        google_module = types.ModuleType("google")
        google_module.genai = types.SimpleNamespace(Client=FakeClient)
        with (
            patch.dict(sys.modules, {"google": google_module}),
            patch("backend.app.gemini_service.require_project", return_value=base),
            patch("backend.app.gemini_service._api_key", return_value="test-key"),
            patch("backend.app.gemini_service.audit_event"),
        ):
            result = translate_project_subtitles("sample", model="gemini-test")

        subtitle = result["subtitles"][0]
        assert subtitle["text"] == "Hello."
        assert subtitle["source_text"] == "Hello."
        assert subtitle["translated_text"] == "訳:Hello."
        assert subtitle["start_sec"] == 1.25
        assert subtitle["end_sec"] == 2.75
        assert subtitle["bilingual_enabled"] is True
