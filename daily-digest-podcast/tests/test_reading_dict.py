"""読み上げマスタ（reading_dict）のユニットテスト。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from reading_dict import apply_readings, load_reading_dict  # noqa: E402


class LoadReadingDictTests(unittest.TestCase):
    def test_default_dict_includes_qiita(self) -> None:
        entries = load_reading_dict()
        surfaces = {s for s, _ in entries}
        self.assertIn("Qiita", surfaces)
        qiita = next(r for s, r in entries if s == "Qiita")
        self.assertEqual(qiita, "キータ")

    def test_longer_surfaces_come_first(self) -> None:
        entries = load_reading_dict()
        surfaces = [s for s, _ in entries]
        if "GitHub Actions" in surfaces and "GitHub" in surfaces:
            self.assertLess(
                surfaces.index("GitHub Actions"),
                surfaces.index("GitHub"),
            )


class ApplyReadingsTests(unittest.TestCase):
    def test_qiita_becomes_kiita(self) -> None:
        text = "今日のQiita人気記事を紹介します。"
        out = apply_readings(text, entries=[("Qiita", "キータ")])
        self.assertEqual(out, "今日のキータ人気記事を紹介します。")
        self.assertNotIn("Qiita", out)

    def test_qiita_case_insensitive(self) -> None:
        text = "qiita と QIITA と Qiita"
        out = apply_readings(text, entries=[("Qiita", "キータ")])
        self.assertEqual(out, "キータ と キータ と キータ")

    def test_does_not_replace_inside_ascii_word(self) -> None:
        text = "NotQiitaX は対象外"
        out = apply_readings(text, entries=[("Qiita", "キータ")])
        self.assertEqual(out, text)

    def test_longer_phrase_wins(self) -> None:
        text = "GitHub Actions と GitHub"
        out = apply_readings(
            text,
            entries=[
                ("GitHub Actions", "ギットハブアクションズ"),
                ("GitHub", "ギットハブ"),
            ],
        )
        self.assertEqual(out, "ギットハブアクションズ と ギットハブ")

    def test_load_from_temp_yaml(self) -> None:
        yaml_body = (
            "readings:\n"
            "  - surface: FooBar\n"
            "    reading: フーバー\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reading_dict.yaml"
            path.write_text(yaml_body, encoding="utf-8")
            out = apply_readings("see FooBar today", dict_path=path)
            self.assertEqual(out, "see フーバー today")

    def test_default_dict_fixes_qiita_in_realistic_script(self) -> None:
        script = (
            "こんにちは。今日はQiitaから注目の投稿と、"
            "GitHubで話題のPull Requestについて話します。"
        )
        out = apply_readings(script)
        self.assertIn("キータ", out)
        self.assertNotIn("Qiita", out)
        self.assertIn("ギットハブ", out)


if __name__ == "__main__":
    unittest.main()
