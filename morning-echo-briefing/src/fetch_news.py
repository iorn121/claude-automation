"""設定した RSS から、朝の短いニュース材料を集める。

本文の全文取得はしない。見出しとフィード内の短い要約だけを使う。
"""

from __future__ import annotations

import logging
from calendar import timegm
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests
import yaml

from content import NewsItem, sanitize_spoken, select_news

log = logging.getLogger("fetch_news")

USER_AGENT = "morning-echo-briefing/1.0"


def _published(entry: dict) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        stamp = entry.get(key)
        if stamp:
            return datetime.fromtimestamp(timegm(stamp), tz=timezone.utc)
    return None


def load_config(path: Path) -> tuple[list[dict], int, int]:
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    feeds = [feed for feed in data.get("feeds") or [] if feed.get("enabled", True) and feed.get("url")]
    lookback_hours = int(data.get("lookback_hours", 30))
    limit = int(data.get("max_items", 5))
    return feeds, lookback_hours, limit


def fetch_news(config_path: Path, now: datetime) -> list[NewsItem]:
    feeds, lookback_hours, limit = load_config(config_path)
    cutoff = now.astimezone(timezone.utc) - timedelta(hours=lookback_hours)
    collected: list[NewsItem] = []

    for feed in feeds:
        name = str(feed.get("name") or feed["url"])
        try:
            response = requests.get(
                feed["url"],
                timeout=20,
                headers={"User-Agent": USER_AGENT},
            )
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
        except requests.RequestException as exc:
            log.warning("フィードを取得できませんでした (%s): %s", name, type(exc).__name__)
            continue

        kept = 0
        for entry in parsed.entries:
            published = _published(entry)
            if published is not None and published < cutoff:
                continue
            title = sanitize_spoken(entry.get("title") or "", limit=80)
            if not title:
                continue
            summary = sanitize_spoken(entry.get("summary") or entry.get("description") or "", limit=240)
            collected.append(NewsItem(source=name, title=title, summary=summary, published=published))
            kept += 1
            if kept >= 4:
                break
        log.info("ニュース %s: %d 件", name, kept)

    selected = select_news(collected, limit=limit)
    log.info("ニュース採用 %d 件", len(selected))
    return selected
