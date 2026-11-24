"""ジャンル分類の単体テスト。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from genre import GenreMap  # noqa: E402


class GenreMapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.genres = GenreMap(
            {
                "技術": ["ai", "クラウド"],
                "その他": [],
            }
        )

    def test_ascii_keyword_does_not_match_inside_a_word(self) -> None:
        self.assertEqual(self.genres.classify("The campaign raises funds"), ["その他"])

    def test_ascii_keyword_matches_a_whole_word_and_japanese_matches_inside(self) -> None:
        self.assertEqual(self.genres.classify("New AI tools"), ["技術"])
        self.assertEqual(self.genres.classify("社内クラウド移行"), ["技術"])

    def test_without_fallback_an_unknown_article_has_no_genre(self) -> None:
        self.assertEqual(GenreMap({"技術": ["ai"]}).classify("天気"), [])

    def test_window_keeps_undated_articles_and_drops_old_ones(self) -> None:
        from datetime import datetime, timedelta, timezone
        from genre import ArticleWindow, LabelGate

        now = datetime(2026, 11, 25, tzinfo=timezone.utc)
        window = ArticleWindow(now, 26)
        self.assertTrue(window.includes(None))
        self.assertFalse(window.includes(now - timedelta(hours=27)))
        self.assertFalse(LabelGate({"技術"}).allows(["技術"]))
        self.assertTrue(LabelGate(set()).allows(["技術"]))


if __name__ == "__main__":
    unittest.main()
