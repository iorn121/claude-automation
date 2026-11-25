"""Echo の Flash Briefing は最新1本だけを、指定の時刻表記で出す。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from publish import alexa_timestamp, flash_briefing_item  # noqa: E402


def test_alexa_timestamp_uses_the_required_utc_shape() -> None:
    assert alexa_timestamp("2026-11-25T00:17:00+09:00") == "2026-11-24T15:17:00.0Z"


def test_flash_briefing_item_points_at_the_latest_episode_only() -> None:
    item = flash_briefing_item(
        {
            "id": "20261125",
            "title": "今日のダイジェスト",
            "filename": "20261125.mp3",
            "pub_date": "2026-11-24T15:17:00+00:00",
        },
        "https://example.github.io/repo/",
    )
    assert item["updateDate"] == "2026-11-24T15:17:00.0Z"
    assert item["streamUrl"] == "https://example.github.io/repo/episodes/20261125.mp3"
    assert item["mainText"] == ""
    assert item["redirectionUrl"] == "https://example.github.io/repo/"
