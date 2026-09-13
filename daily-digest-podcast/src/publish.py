"""
生成したmp3を docs/episodes/ に配置し、docs/episodes.json (メタデータ台帳) と
docs/podcast.xml (Podcast用RSSフィード) を更新する。

docs/ を GitHub Pages で公開する前提 (Settings > Pages > Source: main branch / docs)。
公開後の podcast.xml のURLを Apple Podcasts / Overcast 等の
「URLで番組を追加」機能に登録すると購読できる。

環境変数:
  PODCAST_BASE_URL  例: https://<user>.github.io/<repo>  (末尾スラッシュ無し)
  PODCAST_TITLE     番組タイトル (省略時デフォルト値を使用)
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

from pydub import AudioSegment

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("publish")

MAX_EPISODES_IN_FEED = 30  # フィードに残す最大エピソード数（増えすぎ防止）
DEFAULT_TITLE = "毎日AI・プログラミング・セキュリティダイジェスト"
DEFAULT_DESCRIPTION = "AI・プログラミング・コンピュータ・セキュリティの最新ニュースを毎日自動で要約してお届けします。"
DEFAULT_AUTHOR = "Personal Digest Bot"
# VOICEVOXクレジット表記（使用した話者に合わせて書き換えてください）
VOICE_CREDIT = "この番組の音声には VOICEVOX を使用しています。"


def _episode_id(target_date: str) -> str:
    return target_date.replace("-", "")


def publish_episode(
    mp3_path: str | Path,
    docs_dir: str | Path,
    target_date: str,
    episode_title: str | None = None,
    episode_description: str | None = None,
) -> None:
    docs_dir = Path(docs_dir)
    episodes_dir = docs_dir / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)

    ep_id = _episode_id(target_date)
    dest_filename = f"{ep_id}.mp3"
    dest_path = episodes_dir / dest_filename
    shutil.copyfile(mp3_path, dest_path)

    audio = AudioSegment.from_file(dest_path, format="mp3")
    duration_sec = int(len(audio) / 1000)
    file_size = dest_path.stat().st_size

    episodes_json_path = docs_dir / "episodes.json"
    episodes: list[dict] = []
    if episodes_json_path.exists():
        with open(episodes_json_path, encoding="utf-8") as f:
            episodes = json.load(f)

    episodes = [e for e in episodes if e["id"] != ep_id]  # 同日再実行時は上書き
    episodes.append(
        {
            "id": ep_id,
            "date": target_date,
            "title": episode_title or f"{target_date} のダイジェスト",
            "description": episode_description or DEFAULT_DESCRIPTION,
            "filename": dest_filename,
            "duration_sec": duration_sec,
            "file_size": file_size,
            "pub_date": datetime.now(tz=timezone.utc).isoformat(),
        }
    )
    episodes.sort(key=lambda e: e["date"], reverse=True)

    # 古いエピソードは音声ファイルごと削除して容量を抑える
    keep, drop = episodes[:MAX_EPISODES_IN_FEED], episodes[MAX_EPISODES_IN_FEED:]
    for e in drop:
        old_file = episodes_dir / e["filename"]
        if old_file.exists():
            old_file.unlink()
    episodes = keep

    with open(episodes_json_path, "w", encoding="utf-8") as f:
        json.dump(episodes, f, ensure_ascii=False, indent=2)

    _write_feed(docs_dir, episodes)
    log.info("公開完了: %s (%d秒, %d bytes)", dest_path, duration_sec, file_size)


def _write_feed(docs_dir: Path, episodes: list[dict]) -> None:
    base_url = os.environ.get("PODCAST_BASE_URL", "").rstrip("/")
    if not base_url:
        raise SystemExit("環境変数 PODCAST_BASE_URL を設定してください (例: https://user.github.io/repo)")

    title = os.environ.get("PODCAST_TITLE", DEFAULT_TITLE)

    items_xml = []
    for e in episodes:
        audio_url = f"{base_url}/episodes/{e['filename']}"
        pub_date = format_datetime(datetime.fromisoformat(e["pub_date"]))
        duration = e["duration_sec"]
        hh, mm, ss = duration // 3600, (duration % 3600) // 60, duration % 60
        duration_str = f"{hh:02d}:{mm:02d}:{ss:02d}"

        items_xml.append(
            f"""
    <item>
      <title>{escape(e['title'])}</title>
      <description>{escape(e['description'])}</description>
      <pubDate>{pub_date}</pubDate>
      <guid isPermaLink="false">{escape(e['id'])}</guid>
      <enclosure url="{escape(audio_url)}" length="{e['file_size']}" type="audio/mpeg"/>
      <itunes:duration>{duration_str}</itunes:duration>
      <itunes:explicit>false</itunes:explicit>
    </item>"""
        )

    feed_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>{escape(title)}</title>
    <link>{escape(base_url)}</link>
    <language>ja-jp</language>
    <description>{escape(DEFAULT_DESCRIPTION)} {escape(VOICE_CREDIT)}</description>
    <itunes:author>{escape(DEFAULT_AUTHOR)}</itunes:author>
    <itunes:explicit>false</itunes:explicit>
    <itunes:category text="Technology"/>
    {"".join(items_xml)}
  </channel>
</rss>
"""
    (docs_dir / "podcast.xml").write_text(feed_xml, encoding="utf-8")


def main() -> None:
    mp3_path = sys.argv[1] if len(sys.argv) > 1 else "data/episode.mp3"
    docs_dir = sys.argv[2] if len(sys.argv) > 2 else "docs"
    target_date = sys.argv[3] if len(sys.argv) > 3 else datetime.now().date().isoformat()

    publish_episode(mp3_path, docs_dir, target_date)


if __name__ == "__main__":
    main()
