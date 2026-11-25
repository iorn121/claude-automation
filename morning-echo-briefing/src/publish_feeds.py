"""Flash Briefing 用の JSON / RSS と mp3 を docs/ に書き出す。

ここは git push しない。公開ブランチへの配置はワークフローが行う。
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

from content import (
    alexa_timestamp,
    build_flash_briefing,
    episode_id,
    japanese_date,
    render_audio_rss,
    validate_path_token,
)

log = logging.getLogger("publish_feeds")


def write_feeds(
    docs_dir: Path,
    *,
    script: str,
    mp3_path: Path | None,
    public_base: str,
    token: str,
    moment: datetime,
    run_id: str | None = None,
) -> dict:
    token = validate_path_token(token)
    base = public_base.rstrip("/")
    if not base.startswith("http://") and not base.startswith("https://"):
        raise ValueError("PODCAST_BASE_URL は http:// または https:// から始めてください")

    docs_dir.mkdir(parents=True, exist_ok=True)
    for old in docs_dir.glob("*.mp3"):
        old.unlink()

    audio_name = None
    file_size = 0
    if mp3_path is not None:
        audio_name = f"{episode_id(moment, run_id)}.mp3"
        dest = docs_dir / audio_name
        shutil.copyfile(mp3_path, dest)
        file_size = dest.stat().st_size

    prefix = f"{base}/briefing/{token}"
    audio_url = f"{prefix}/{audio_name}" if audio_name else None
    # 「続きを読む」は番組トップに飛ばし、秘密パスを Alexa アプリに出さない。
    redirection_url = f"{base}/"
    # moment は BRIEFING_TIMEZONE の現地時刻で渡す。date() はそのタイムゾーンの日付。
    title = f"{japanese_date(moment.date())}の朝のブリーフィング"
    text_items, audio_items = build_flash_briefing(
        script=script,
        audio_url=audio_url,
        redirection_url=redirection_url,
        moment=moment,
        title=title,
    )

    (docs_dir / "flashbriefing.json").write_text(
        json.dumps(text_items, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if audio_items and audio_url and audio_name:
        (docs_dir / "flashbriefing-audio.json").write_text(
            json.dumps(audio_items, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        rss = render_audio_rss(
            title=title,
            audio_url=audio_url,
            file_size=file_size,
            redirection_url=redirection_url,
            moment=moment,
            guid=audio_items[0]["uid"],
        )
        (docs_dir / "briefing.xml").write_text(rss, encoding="utf-8")
    else:
        for name in ("flashbriefing-audio.json", "briefing.xml"):
            stale = docs_dir / name
            if stale.exists():
                stale.unlink()

    log.info("フィードを書き出しました（更新時刻 %s）", alexa_timestamp(moment))
    return {
        "audio_url": audio_url,
        "text_feed_path": str(docs_dir / "flashbriefing.json"),
        "audio_feed_path": str(docs_dir / "flashbriefing-audio.json") if audio_url else None,
    }
