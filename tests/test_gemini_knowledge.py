import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.app import gemini_service


class SearchInteraction:
    output_text = "公式情報を調査したレポート"

    def model_dump(self, mode=None):
        return {
            "steps": [{
                "type": "model_output",
                "content": [{
                    "type": "text",
                    "annotations": [{
                        "type": "url_citation",
                        "url": "https://example.com/official",
                        "title": "公式サイト",
                    }],
                }],
            }],
        }


class GeminiKnowledgeTests(unittest.TestCase):
    def test_user_can_save_and_reload_knowledge_base(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            with (
                patch.object(gemini_service, "require_project", return_value=base),
                patch.object(gemini_service, "audit_event"),
            ):
                saved = gemini_service.save_project_knowledge_base("sample", {
                    "work_title": "作品名",
                    "entries": [{
                        "type": "character",
                        "canonical_name": "正しい名前",
                        "aliases": ["読み", "誤認識"],
                        "description": "主人公",
                        "enabled": True,
                    }],
                })
                loaded = gemini_service.load_project_knowledge_base("sample")

        self.assertEqual(saved["entries"][0]["canonical_name"], "正しい名前")
        self.assertTrue(saved["entries"][0]["user_edited"])
        self.assertEqual(loaded["entries"][0]["aliases"], ["読み", "誤認識"])

    def test_web_research_uses_google_search_and_saves_citations(self):
        generated = {
            "work_title": "作品名",
            "summary": "字幕校正用DB",
            "entries": [{
                "type": "character",
                "canonical_name": "主人公",
                "aliases": ["しゅじんこう"],
                "description": "主要人物",
                "source_urls": ["https://example.com/official"],
                "confidence": 0.95,
            }],
        }
        calls = []

        class FakeInteractions:
            def create(self, **kwargs):
                calls.append(kwargs)
                if len(calls) == 1:
                    return SearchInteraction()
                return SimpleNamespace(output_text=json.dumps(generated, ensure_ascii=False))

        fake_client = SimpleNamespace(interactions=FakeInteractions())
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            with (
                patch.object(gemini_service, "require_project", return_value=base),
                patch.object(gemini_service, "_api_key", return_value="test-key"),
                patch.object(gemini_service, "_read_config", return_value={"model": "gemini-3.5-flash"}),
                patch("google.genai.Client", return_value=fake_client),
                patch.object(gemini_service, "audit_event"),
            ):
                result = gemini_service.research_project_knowledge("sample", "作品名")

        self.assertEqual(calls[0]["tools"], [{"type": "google_search"}])
        self.assertEqual(result["sources"][0]["url"], "https://example.com/official")
        self.assertEqual(result["entries"][0]["canonical_name"], "主人公")
        self.assertEqual(result["entries"][0]["origin"], "gemini_web")

    def test_human_edited_entry_is_preserved_on_research(self):
        generated = {
            "work_title": "作品名",
            "summary": "更新",
            "entries": [{
                "type": "term",
                "canonical_name": "専門用語",
                "aliases": ["AI候補"],
                "description": "AI説明",
                "source_urls": [],
                "confidence": 0.8,
            }],
        }

        class FakeInteractions:
            count = 0

            def create(self, **kwargs):
                self.count += 1
                return SearchInteraction() if self.count == 1 else SimpleNamespace(output_text=json.dumps(generated, ensure_ascii=False))

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            (base / "ai").mkdir()
            (base / "ai" / gemini_service.KNOWLEDGE_BASE_FILENAME).write_text(json.dumps({
                "entries": [{
                    "id": "kb_manual",
                    "type": "term",
                    "canonical_name": "専門用語",
                    "aliases": ["手動候補"],
                    "description": "人間が修正した説明",
                    "enabled": True,
                    "origin": "manual",
                    "user_edited": True,
                }],
                "sources": [],
            }, ensure_ascii=False), encoding="utf-8")
            fake_client = SimpleNamespace(interactions=FakeInteractions())
            with (
                patch.object(gemini_service, "require_project", return_value=base),
                patch.object(gemini_service, "_api_key", return_value="test-key"),
                patch.object(gemini_service, "_read_config", return_value={"model": "gemini-3.5-flash"}),
                patch("google.genai.Client", return_value=fake_client),
                patch.object(gemini_service, "audit_event"),
            ):
                result = gemini_service.research_project_knowledge("sample", "作品名")

        self.assertEqual(result["entries"][0]["description"], "人間が修正した説明")
        self.assertEqual(result["entries"][0]["aliases"], ["手動候補"])

    def test_enabled_database_entries_are_added_to_correction_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            (base / "ai").mkdir()
            (base / "ai" / gemini_service.KNOWLEDGE_BASE_FILENAME).write_text(json.dumps({
                "entries": [
                    {"type": "character", "canonical_name": "正式名", "aliases": ["誤認識"], "enabled": True},
                    {"type": "term", "canonical_name": "無効語", "enabled": False},
                ]
            }, ensure_ascii=False), encoding="utf-8")
            with patch.object(gemini_service, "require_project", return_value=base):
                prompt = gemini_service._knowledge_base_instruction("sample")

        self.assertIn("正式名", prompt)
        self.assertIn("誤認識", prompt)
        self.assertNotIn("無効語", prompt)

    def test_shared_database_can_be_linked_and_reused_by_another_project(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            shared = root / "shared"
            projects = {project_id: root / project_id for project_id in ("project_a", "project_b")}
            for base in projects.values():
                (base / "ai").mkdir(parents=True)

            def require(project_id):
                return projects[project_id]

            with (
                patch.object(gemini_service, "require_project", side_effect=require),
                patch.object(gemini_service, "SHARED_KNOWLEDGE_DIR", shared),
                patch.object(gemini_service, "audit_event"),
            ):
                gemini_service.save_project_knowledge_base("project_a", {
                    "work_title": "共通作品",
                    "entries": [{
                        "type": "character",
                        "canonical_name": "主人公",
                        "aliases": ["しゅじんこう"],
                        "description": "Aで作成",
                    }],
                })
                registered = gemini_service.register_project_knowledge_as_shared("project_a", "作品DB")
                database_id = registered["linked_database_id"]
                linked = gemini_service.link_project_knowledge_base("project_b", database_id)
                linked["entries"][0]["description"] = "Bで更新"
                gemini_service.save_project_knowledge_base("project_b", linked)
                visible_from_a = gemini_service.load_project_knowledge_base("project_a")
                unlinked = gemini_service.link_project_knowledge_base("project_b", None)
                databases = gemini_service.list_shared_knowledge_bases()

        self.assertEqual(linked["storage_scope"], "shared")
        self.assertEqual(visible_from_a["entries"][0]["description"], "Bで更新")
        self.assertEqual(unlinked["storage_scope"], "project")
        self.assertEqual(unlinked["entries"], [])
        self.assertEqual(databases[0]["database_name"], "作品DB")
        self.assertEqual(databases[0]["entry_count"], 1)


if __name__ == "__main__":
    unittest.main()
