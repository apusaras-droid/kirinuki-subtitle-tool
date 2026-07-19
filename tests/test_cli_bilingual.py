import unittest

from backend.app.cli import build_parser


class BilingualCliTests(unittest.TestCase):
    def test_translate_subtitles_arguments(self):
        args = build_parser().parse_args(
            [
                "translate-subtitles",
                "--project-id",
                "sample",
                "--source-language",
                "en",
                "--target-language",
                "ja",
                "--display-mode",
                "translation_above",
            ]
        )
        self.assertEqual(args.command, "translate-subtitles")
        self.assertEqual(args.project_id, "sample")
        self.assertEqual(args.display_mode, "translation_above")


if __name__ == "__main__":
    unittest.main()
