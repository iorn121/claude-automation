"""外部 API を使わない単体テスト。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from clock import parse_hhmm, seconds_until  # noqa: E402
from content import (  # noqa: E402
    CalendarEvent,
    NewsItem,
    alexa_timestamp,
    build_fallback_script,
    build_flash_briefing,
    calendar_event_from_api,
    classify_tasks,
    clean_model_script,
    finalize_script,
    for_tts,
    select_news,
    task_due_date,
    truncate_for_speech,
    validate_path_token,
)
from publish_feeds import write_feeds  # noqa: E402

TZ = ZoneInfo("Asia/Tokyo")
TOKEN = "a" * 32


class ClockTests(unittest.TestCase):
    def test_waits_when_announce_time_is_soon(self) -> None:
        now = datetime(2026, 9, 23, 6, 40, tzinfo=TZ)
        self.assertEqual(seconds_until(now, "07:00"), 20 * 60)

    def test_does_not_wait_after_the_time_or_when_it_is_far(self) -> None:
        later = datetime(2026, 9, 23, 7, 5, tzinfo=TZ)
        early = datetime(2026, 9, 23, 5, 0, tzinfo=TZ)
        self.assertEqual(seconds_until(later, "07:00"), 0)
        self.assertEqual(seconds_until(early, "07:00"), 0)

    def test_rejects_bad_clock(self) -> None:
        with self.assertRaises(ValueError):
            parse_hhmm("25:00")


class ContentTests(unittest.TestCase):
    def test_calendar_formats_tokyo_time_and_skips_declined(self) -> None:
        event = {
            "summary": "企画会議",
            "location": "会議室A",
            "start": {"dateTime": "2026-09-22T22:00:00Z"},
            "end": {"dateTime": "2026-09-22T23:00:00Z"},
        }
        parsed = calendar_event_from_api(event, TZ)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.when, "7時から8時")
        self.assertEqual(parsed.title, "企画会議")

        declined = {
            "summary": "欠席する会議",
            "start": {"date": "2026-09-23"},
            "attendees": [{"self": True, "responseStatus": "declined"}],
        }
        self.assertIsNone(calendar_event_from_api(declined, TZ))

    def test_tasks_keep_near_due_dates_using_the_date_prefix(self) -> None:
        today = date(2026, 9, 23)
        raw = [
            {"title": "昨日の宿題", "due": "2026-09-22T00:00:00.000Z", "status": "needsAction"},
            {"title": "今日出す", "due": "2026-09-23T00:00:00.000Z", "status": "needsAction"},
            {"title": "来月", "due": "2026-10-23T00:00:00.000Z", "status": "needsAction"},
            {"title": "完了済み", "due": "2026-09-23T00:00:00.000Z", "status": "completed"},
            {"title": "期限なし", "status": "needsAction"},
        ]
        chosen = classify_tasks(raw, today)
        self.assertEqual([item.title for item in chosen], ["昨日の宿題", "今日出す", "期限なし"])
        self.assertEqual([item.bucket for item in chosen], ["overdue", "today", "undated"])
        self.assertEqual(task_due_date("2026-09-23T00:00:00.000Z"), today)

    def test_news_round_robin(self) -> None:
        base = datetime(2026, 9, 23, tzinfo=timezone.utc)
        items = [
            NewsItem("A", "a1", "", base),
            NewsItem("A", "a2", "", base - timedelta(hours=1)),
            NewsItem("B", "b1", "", base - timedelta(minutes=30)),
            NewsItem("C", "c1", "", base - timedelta(minutes=20)),
        ]
        selected = select_news(items, limit=3)
        self.assertEqual([item.title for item in selected], ["a1", "c1", "b1"])

    def test_fallback_script_is_speakable(self) -> None:
        script = build_fallback_script(
            date(2026, 9, 23),
            [CalendarEvent("朝会", "9時から9時30分", False, "")],
            [],
            [NewsItem("NHKニュース", "見出しです", "")],
        )
        self.assertIn("おはようございます", script)
        self.assertIn("朝会", script)
        self.assertIn("ニュース", script)
        self.assertIn("VOICEVOX", script)
        self.assertNotIn("#", script)
        self.assertNotIn("<", for_tts(script))

    def test_model_script_strips_markdown_and_keeps_credit(self) -> None:
        cleaned = finalize_script("# おはようございます。\n- 予定は朝会です")
        self.assertNotIn("#", cleaned)
        self.assertNotIn("-", cleaned)
        self.assertTrue(cleaned.strip().endswith("使用しています。"))
        self.assertIn("おはようございます", clean_model_script("# おはようございます。"))

    def test_truncate_keeps_a_sentence_boundary(self) -> None:
        text = "あ" * 20 + "。" + "い" * 80
        short = truncate_for_speech(text, limit=30)
        self.assertTrue(short.endswith("。"))
        self.assertLessEqual(len(short), 30)

    def test_flash_briefing_audio_does_not_embed_the_script(self) -> None:
        moment = datetime(2026, 9, 23, 6, 50, tzinfo=TZ)
        text_items, audio_items = build_flash_briefing(
            script="おはようございます。今日の予定は朝会です。",
            audio_url=f"https://example.github.io/repo/briefing/{TOKEN}/episode.mp3",
            redirection_url="https://example.github.io/repo/",
            moment=moment,
            title="9月23日水曜日の朝のブリーフィング",
        )
        self.assertNotIn(TOKEN, text_items[0]["redirectionUrl"])
        self.assertIn("朝会", text_items[0]["mainText"])
        self.assertRegex(text_items[0]["updateDate"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.0Z$")
        self.assertEqual(alexa_timestamp(moment), "2026-09-22T21:50:00.0Z")
        assert audio_items is not None
        self.assertEqual(audio_items[0]["mainText"], "")
        self.assertIn(TOKEN, audio_items[0]["streamUrl"])

    def test_token_rules(self) -> None:
        self.assertEqual(validate_path_token(TOKEN), TOKEN)
        with self.assertRaises(ValueError):
            validate_path_token("short")
        with self.assertRaises(ValueError):
            validate_path_token("../etc/passwd")


class PublishTests(unittest.TestCase):
    def test_writes_text_and_audio_feeds(self) -> None:
        moment = datetime(2026, 9, 23, 6, 50, tzinfo=TZ)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mp3 = root / "in.mp3"
            mp3.write_bytes(b"not-really-audio")
            docs = root / "docs"
            docs.mkdir()
            (docs / "old.mp3").write_bytes(b"old")
            result = write_feeds(
                docs,
                script="おはようございます。今日の予定はありません。",
                mp3_path=mp3,
                public_base="https://example.github.io/repo",
                token=TOKEN,
                moment=moment,
                run_id="123",
            )
            text = json.loads((docs / "flashbriefing.json").read_text(encoding="utf-8"))
            audio = json.loads((docs / "flashbriefing-audio.json").read_text(encoding="utf-8"))
            rss = (docs / "briefing.xml").read_text(encoding="utf-8")
            self.assertEqual(text[0]["redirectionUrl"], "https://example.github.io/repo/")
            self.assertNotIn(TOKEN, text[0]["redirectionUrl"])
            self.assertIn(TOKEN, audio[0]["streamUrl"])
            self.assertIn("20260922T215000Z-123.mp3", audio[0]["streamUrl"])
            self.assertIn("audio/mpeg", rss)
            self.assertFalse((docs / "old.mp3").exists())
            self.assertTrue(result["audio_url"].endswith(".mp3"))


if __name__ == "__main__":
    unittest.main()
