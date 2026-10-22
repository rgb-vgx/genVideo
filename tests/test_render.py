from __future__ import annotations

import unittest
from pathlib import Path

from genvideo.render import F, detect_font_family, font_family, set_font_family
from genvideo.schema import load_episode

from .helpers import EXAMPLE, ROOT

NOTO_CJK = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")


class FontTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_font_family("default")

    def test_font_family_detection(self) -> None:
        english = load_episode(EXAMPLE)
        korean = load_episode(ROOT / "examples" / "lesson_ko.json")
        japanese = load_episode(ROOT / "examples" / "lesson_ja.json")

        self.assertEqual(detect_font_family(english, "en"), "default")
        self.assertEqual(detect_font_family(korean, "ko"), "kr")
        self.assertEqual(detect_font_family(korean, "vi"), "kr")
        self.assertEqual(detect_font_family(japanese, "ja"), "jp")
        self.assertEqual(detect_font_family(japanese, "vi"), "jp")

    @unittest.skipUnless(NOTO_CJK.exists(), "Noto Sans CJK is not installed")
    def test_korean_and_japanese_fonts_load(self) -> None:
        set_font_family("kr")
        self.assertEqual(font_family(), "kr")
        self.assertGreater(F(20).getlength("안녕하세요"), 0)
        set_font_family("jp")
        self.assertEqual(font_family(), "jp")
        self.assertGreater(F(20).getlength("こんにちは"), 0)

    @unittest.skipUnless(NOTO_CJK.exists(), "Noto Sans CJK is not installed")
    def test_cjk_font_covers_vietnamese(self) -> None:
        set_font_family("kr")
        self.assertGreater(F(20, False).getlength("Tiếng Hàn cơ bản"), 0)


if __name__ == "__main__":
    unittest.main()
