"""フィード収集が設定順を保ったまま並列に進むことを確認する。"""
from __future__ import annotations

import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import fetch_feeds  # noqa: E402


class FetchOrderTests(unittest.TestCase):
    def test_parallel_fetch_keeps_feed_order(self) -> None:
        parsed: list[str] = []
        state = {"active": 0, "max": 0}
        lock = threading.Lock()

        def parse(url: str):
            with lock:
                state["active"] += 1
                state["max"] = max(state["max"], state["active"])
            try:
                time.sleep(0.05)
                parsed.append(url)

                class Feed:
                    bozo = False
                    entries = [
                        {
                            "title": url,
                            "link": url,
                            "summary": "本文" * 200,
                        }
                    ]

                return Feed()
            finally:
                with lock:
                    state["active"] -= 1

        original_parse = fetch_feeds.feedparser.parse
        original_clean = fetch_feeds._clean_html
        fetch_feeds.feedparser.parse = parse
        fetch_feeds._clean_html = lambda raw: raw
        try:
            with tempfile.TemporaryDirectory() as tmp:
                config = Path(tmp) / "feeds.yaml"
                config.write_text(
                    textwrap.dedent(
                        """
                        lookback_hours: 48
                        max_articles_per_feed: 2
                        feeds:
                          - name: slow
                            url: https://example.test/slow
                            enabled: true
                          - name: fast
                            url: https://example.test/fast
                            enabled: true
                          - name: off
                            url: https://example.test/off
                            enabled: false
                        """
                    ),
                    encoding="utf-8",
                )
                articles = fetch_feeds.fetch_all(
                    config,
                    labels_path=None,
                    mapping_path=Path(tmp) / "missing.yaml",
                )
        finally:
            fetch_feeds.feedparser.parse = original_parse
            fetch_feeds._clean_html = original_clean

        self.assertEqual([article["source"] for article in articles], ["slow", "fast"])
        self.assertNotIn("https://example.test/off", parsed)
        self.assertGreaterEqual(state["max"], 2)


if __name__ == "__main__":
    unittest.main()
