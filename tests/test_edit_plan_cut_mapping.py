import unittest

from backend.app.edit_plan import build_edit_plan
from backend.app.services import build_scene_catalog_from_subtitles


class EditPlanCutMappingTests(unittest.TestCase):
    def test_manual_cut_remaps_subtitles_to_joined_timeline(self):
        transcript = {
            "subtitles": [
                {"id": "before", "start_sec": 2.0, "end_sec": 4.0, "text": "before"},
                {"id": "inside", "start_sec": 6.0, "end_sec": 8.0, "text": "inside"},
                {"id": "after", "start_sec": 12.0, "end_sec": 14.0, "text": "after"},
                {"id": "crossing", "start_sec": 4.0, "end_sec": 12.0, "text": "crossing"},
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

        self.assertEqual(plan["segments"][0]["output_start_sec"], 0.0)
        self.assertEqual(plan["segments"][0]["output_end_sec"], 5.0)
        self.assertEqual(plan["segments"][1]["output_start_sec"], 5.0)
        self.assertEqual(plan["segments"][1]["output_end_sec"], 15.0)

        scenes = build_scene_catalog_from_subtitles(plan["subtitles"])
        scene_by_text = {scene["text"]: scene for scene in scenes}
        self.assertNotIn("inside", scene_by_text)
        self.assertEqual(scene_by_text["after"]["start_sec"], 7.0)
        self.assertEqual(scene_by_text["after"]["end_sec"], 9.0)


if __name__ == "__main__":
    unittest.main()
