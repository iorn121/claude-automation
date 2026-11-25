"""朝のブリーフィングを1回分作る。

    python src/run_all.py --dry-run     # 通信なし。台本とフィードの形だけ確認
    python src/run_all.py --skip-audio  # 音声合成なし（テキストフィードのみ）

GitHub Actions では Secrets / Variables を環境変数として渡す。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from compose import compose_script
from content import CalendarEvent, NewsItem, TaskItem, build_fallback_script
from publish_feeds import write_feeds

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("run_all")

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"
CONFIG_PATH = ROOT / "config" / "feeds.yaml"
LOCAL_TOKEN = "local-preview-only"


def _load_env() -> None:
    load_dotenv(ROOT / ".env", override=True)
    load_dotenv(REPO_ROOT / ".env", override=False)


def _dry_fixtures(today: datetime) -> tuple[list[CalendarEvent], list[TaskItem], list[NewsItem]]:
    events = [
        CalendarEvent(title="朝会", when="9時30分から10時", all_day=False, location=""),
        CalendarEvent(title="集中作業", when="終日", all_day=True, location=""),
    ]
    tasks = [
        TaskItem(title="報告書を出す", due=today.date(), bucket="today"),
        TaskItem(title="購入リストを更新する", due=None, bucket="undated"),
    ]
    news = [NewsItem(source="サンプル", title="音声アシスタントの朝の使い方", summary="")]
    return events, tasks, news


def _collect(now: datetime, tz: ZoneInfo, dry_run: bool):
    if dry_run:
        log.info("dry-run: サンプルの予定で台本を作ります")
        return _dry_fixtures(now)
    from fetch_google import fetch_events, fetch_tasks, load_credentials
    from fetch_news import fetch_news

    creds = load_credentials()
    start = datetime.combine(now.date(), time.min, tzinfo=tz)
    events = fetch_events(creds, start, tz)
    tasks = fetch_tasks(creds, now)
    try:
        news = fetch_news(CONFIG_PATH, now)
    except Exception as exc:
        log.warning("ニュース収集に失敗したため、ニュースなしで続行します (%s)", type(exc).__name__)
        news = []
    return events, tasks, news


def main(argv: list[str] | None = None) -> None:
    _load_env()
    parser = argparse.ArgumentParser(description="朝の Echo ブリーフィングを生成する")
    parser.add_argument("--dry-run", action="store_true", help="外部 API を呼ばずサンプルで生成する")
    parser.add_argument("--skip-audio", action="store_true", help="VOICEVOX による音声合成をしない")
    args = parser.parse_args(argv)

    tz = ZoneInfo(os.environ.get("BRIEFING_TIMEZONE", "Asia/Tokyo"))
    now = datetime.now(tz)
    skip_audio = args.skip_audio or args.dry_run or os.environ.get("BRIEFING_SKIP_AUDIO", "").lower() == "true"
    require_token = os.environ.get("BRIEFING_REQUIRE_TOKEN", "").lower() == "true"

    token = os.environ.get("BRIEFING_PATH_TOKEN", "").strip()
    public_base = os.environ.get("PODCAST_BASE_URL", "").strip()
    if require_token:
        if not token:
            raise SystemExit("BRIEFING_PATH_TOKEN を設定してください")
        if not public_base.startswith("https://"):
            raise SystemExit("PODCAST_BASE_URL は https:// から始まる公開 URL にしてください")
    token = token or LOCAL_TOKEN
    public_base = public_base or "http://localhost"

    events, tasks, news = _collect(now, tz, args.dry_run)
    if args.dry_run:
        script, source = build_fallback_script(now.date(), events, tasks, news), "dry-run"
    else:
        script, source = compose_script(
            now.date(),
            events,
            tasks,
            news,
            os.environ.get("GEMINI_API_KEY", "").strip() or None,
        )

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "script.txt").write_text(script, encoding="utf-8")
    summary = {
        "date": now.date().isoformat(),
        "events": len(events),
        "tasks": len(tasks),
        "news": len(news),
        "script_source": source,
        "script_chars": len(script),
        "audio": not skip_audio,
    }
    (DATA_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log.info("材料: %s", json.dumps(summary, ensure_ascii=False))

    mp3_path = None
    if not skip_audio:
        from synthesize import synthesize_script

        mp3_path = DATA_DIR / "briefing.mp3"
        synthesize_script(script, mp3_path)

    write_feeds(
        DOCS_DIR,
        script=script,
        mp3_path=mp3_path,
        public_base=public_base,
        token=token,
        moment=now,
        run_id=os.environ.get("GITHUB_RUN_ID"),
    )
    log.info("生成完了")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log.error("%s", exc)
        sys.exit(1)
