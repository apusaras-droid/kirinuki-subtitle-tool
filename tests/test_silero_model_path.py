import tempfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.app.services import _ensure_ascii_model_path


class SileroModelPathTests(unittest.TestCase):
    def test_copies_non_ascii_model_to_ascii_temp_path(self):
        with TemporaryDirectory() as source_root, TemporaryDirectory() as cache_root:
            source_dir = Path(source_root) / "日本語"
            source_dir.mkdir()
            source = source_dir / "silero_vad.jit"
            source.write_bytes(b"model-data")
            with patch.object(tempfile, "gettempdir", return_value=cache_root):
                resolved = _ensure_ascii_model_path(source)
            str(resolved).encode("ascii")
            self.assertEqual(resolved.read_bytes(), b"model-data")
            self.assertNotEqual(resolved, source)


if __name__ == "__main__":
    unittest.main()
