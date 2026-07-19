import unittest

from backend.app.edit_plan import build_edit_plan
from backend.app.services import build_scene_catalog_from_subtitles


class EditPlanCutMappingTests(unittest.TestCase):
    def test_subtitle_free_mode_keeps_full_range_for_manual_cutting(self):
        plan = build_edit_plan(
            "input.mp4",
            {"start_sec": 10.0, "end_sec": 40.0},
            [{"start_sec": 0.0, "end_sec": 30.0}],
            {"subtitle_mode": "none", "subtitles": []},
            {
                "detection_mode": "silencedetect",
                "manual_cut_segments": [{"start_sec": 15.0, "end_sec": 20.0}],
                "pre_margin_sec": 0.0,
                "post_margin_sec": 0.0,
                "merge_silence_gap_sec": 0.0,
                "min_keep_segment_duration": 0.1,
            },
        )

        self.assertEqual(plan["subtitles"], [])
        self.assertEqual(len(plan["segments"]), 2)
        self.assertEqual(plan["segments"][0]["source_start_sec"], 10.0)
        self.assertEqual(plan["segments"][0]["source_end_sec"], 15.0)
        self.assertEqual(plan["segments"][1]["source_start_sec"], 20.0)
        self.assertEqual(plan["segments"][1]["source_end_sec"], 40.0)

    def test_manual_cut_remaps_subtitles_to_joined_timeline(self):
        transcript = {
            "subtitles": [
                {"id": "before", "start_sec": 2.0, "end_sec": 4.0, "text": "before"},
                {"id": "inside", "start_sec": 6.0, "end_sec": 8.0, "text": "inside"},
                {"id": "after", "start_sec": 12.0, "end_sec": 14.0, "text": "after"},
                {"id": "crossing", "start_sec": 4.0, "end_sec": 12.0, "text": "crossing"},
                {"id": "head_cut", "start_sec": 8.0, "end_sec": 12.0, "text": "head cut"},
                {"id": "tail_cut", "start_sec": 4.0, "end_sec": 7.0, "text": "tail cut"},
            ]
        }
        plan = build_edit_plan(
            "input.mp4",
            {"start_sec": 0.0, "end_sec": 20.0},
            [],
            transcript,
            {
                "detection_mode": "silencedetect",
                "manual_cut_segments": [{"src_start": 5.0, "src_end": 10.0}],
                "pre_margin_sec": 0.0,
                "post_margin_sec": 0.0,
                "merge_silence_gap_sec": 0.0,
                "min_keep_segment_duration": 0.1,
            },
        )

        subtitles = {item["id"]: item for item in plan["subtitles"]}
        self.assertEqual(subtitles["before"]["output_start_sec"], 2.0)
        self.assertEqual(subtitles["before"]["output_end_sec"], 4.0)
        self.assertFalse(subtitles["inside"]["enabled"])
        self.assertEqual(subtitles["after"]["output_start_sec"], 7.0)
        self.assertEqual(subtitles["after"]["output_end_sec"], 9.0)
        self.assertEqual(subtitles["crossing"]["output_start_sec"], 4.0)
        self.assertEqual(subtitles["crossing"]["output_end_sec"], 7.0)
        self.assertEqual(len(subtitles["crossing"]["split_pieces"]), 2)
        self.assertIsNot(subtitles["head_cut"].get("enabled"), False)
        self.assertEqual(subtitles["head_cut"]["output_start_sec"], 5.0)
        self.assertEqual(subtitles["head_cut"]["output_end_sec"], 7.0)
        self.assertTrue(subtitles["head_cut"]["cut_clipped_start"])
        self.assertIsNot(subtitles["tail_cut"].get("enabled"), False)
        self.assertEqual(subtitles["tail_cut"]["output_start_sec"], 4.0)
        self.assertEqual(subtitles["tail_cut"]["output_end_sec"], 5.0)
        self.assertTrue(subtitles["tail_cut"]["cut_clipped_end"])

        self.assertEqual(plan["segments"][0]["output_start_sec"], 0.0)
        self.assertEqual(plan["segments"][0]["output_end_sec"], 5.0)
        self.assertEqual(plan["segments"][1]["output_start_sec"], 5.0)
        self.assertEqual(plan["segments"][1]["output_end_sec"], 15.0)

        scenes = build_scene_catalog_from_subtitles(plan["subtitles"])
        scene_by_text = {scene["text"]: scene for scene in scenes}
        self.assertNotIn("inside", scene_by_text)
        self.assertEqual(scene_by_text["after"]["start_sec"], 7.0)
        self.assertEqual(scene_by_text["after"]["end_sec"], 9.0)

    def test_subtitle_disabled_by_a_cut_returns_when_the_cut_is_removed(self):
        transcript = {"subtitles": [{"id": "caption", "start_sec": 6.0, "end_sec": 8.0, "text": "caption"}]}
        cut_plan = build_edit_plan(
            "input.mp4",
            {"start_sec": 0.0, "end_sec": 20.0},
            [],
            transcript,
            {
                "detection_mode": "silencedetect",
                "manual_cut_segments": [{"src_start": 5.0, "src_end": 10.0}],
                "pre_margin_sec": 0.0,
                "post_margin_sec": 0.0,
                "merge_silence_gap_sec": 0.0,
                "min_keep_segment_duration": 0.1,
            },
        )
        self.assertFalse(cut_plan["subtitles"][0]["enabled"])
        self.assertTrue(cut_plan["subtitles"][0]["disabled_by_cut"])

        restored_plan = build_edit_plan(
            "input.mp4",
            {"start_sec": 0.0, "end_sec": 20.0},
            [],
            {"subtitles": cut_plan["subtitles"]},
            {
                "detection_mode": "silencedetect",
                "manual_cut_segments": [],
                "pre_margin_sec": 0.0,
                "post_margin_sec": 0.0,
                "merge_silence_gap_sec": 0.0,
                "min_keep_segment_duration": 0.1,
            },
        )
        restored = restored_plan["subtitles"][0]
        self.assertTrue(restored["enabled"])
        self.assertNotIn("disabled_by_cut", restored)
        self.assertEqual(restored["output_start_sec"], 6.0)
        self.assertEqual(restored["output_end_sec"], 8.0)

    def test_automatic_cut_keeps_the_full_caption_when_vad_keeps_its_head(self):
        plan = build_edit_plan(
            "input.mp4",
            {"start_sec": 0.0, "end_sec": 20.0},
            [{"start_sec": 5.0, "end_sec": 20.0}],
            {"subtitles": [{"id": "caption", "start_sec": 4.0, "end_sec": 8.0, "text": "caption"}]},
            {
                "detection_mode": "silencedetect",
                "manual_cut_segments": [],
                "pre_margin_sec": 0.0,
                "post_margin_sec": 0.0,
                "merge_silence_gap_sec": 0.0,
                "min_keep_segment_duration": 0.1,
            },
        )

        self.assertEqual(plan["segments"][0]["range_relative_start_sec"], 0.0)
        self.assertEqual(plan["segments"][0]["range_relative_end_sec"], 8.0)
        subtitle = plan["subtitles"][0]
        self.assertEqual(subtitle["output_start_sec"], 4.0)
        self.assertEqual(subtitle["output_end_sec"], 8.0)
        self.assertFalse(subtitle["cut_clipped_end"])


if __name__ == "__main__":
    unittest.main()
