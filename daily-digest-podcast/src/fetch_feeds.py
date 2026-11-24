"""
RSSフィードを巡回して、直近 lookback_hours 以内に公開された記事を集める。
本文が短い（フィードが要約のみ）場合は trafilatura で本文抽出を試みる。

各記事には「ラベル」として、あらかじめ定義された大雑把なジャンル
(config/label_mapping.yaml、MECEを意識した9種類、最後は受け皿の「その他」)が付く。
元のRSS/Atomエントリが持つ<category>タグ・タイトルをキーワード判定してジャンルに
分類し、どれにも一致しなければ「その他」に分類する(＝記事には必ず1つ以上のラベルが付く)。
フィード(config/feeds.yaml)側にジャンルの概念はなく、あくまで記事ごとに毎回判定する。
config/labels.yaml でジャンルごとにON/OFFを管理でき、OFFのジャンルに
分類された記事は収集結果から除外される（tools/feeds_editor.py のブラウザUIから編集可能）。

出力: list[dict] を返す。各要素は
  {
    "title": str,
    "url": str,
    "labels": list[str],    # 記事を分類した結果のジャンル(1件以上)
    "source": str,          # フィード名
    "published": str,       # ISO8601
    "text": str,            # 本文（取得できなければ要約のみ）
  }
"""
from __future__ import annotations

import json
import logging
import sys
from calendar import timegm
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import feedparser
import trafilatura
import yaml

from genre import ArticleWindow, GenreMap, LabelGate

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("fetch_feeds")

MIN_TEXT_LEN_TO_SKIP_EXTRACTION = 400  # フィードのdescriptionがこれ以上長ければ本文抽出をスキップ

LABELS_HEADER_COMMENT = """\
# 大雑把なジャンル(ラベル)ごとのON/OFF一覧。
# ジャンルの一覧・分類ルールは config/label_mapping.yaml で定義されている
# (ここに新しいジャンルを追加/削除したい場合は、まずそちらを編集してから
# tools/feeds_editor.py で保存し直すと、この一覧にも反映される)。
# false にしたジャンルに分類された記事は収集結果から除外されます。
"""

DEFAULT_LABEL_MAPPING_PATH = "config/label_mapping.yaml"


def _entry_published(entry: dict[str, Any]) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime.fromtimestamp(timegm(t), tz=timezone.utc)
    return None


def _raw_entry_tags(entry: dict[str, Any]) -> list[str]:
    """RSS/Atomエントリ自身が持つ<category>タグを、そのままの粒度で抽出する。"""
    tags = []
    for tag in entry.get("tags", []) or []:
        term = (tag.get("term") or "").strip()
        if term and term not in tags:
            tags.append(term)
    return tags


def load_label_mapping(mapping_path: str | Path) -> dict[str, list[str]]:
    """config/label_mapping.yaml を読み込む。
    戻り値のキーの並び順が「選べるジャンル一覧」そのもの。
    ファイルが無ければ空の辞書（＝分類なし、記事にはラベルが付かない）。
    """
    path = Path(mapping_path)
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    genres = data.get("genres", {}) or {}
    result: dict[str, list[str]] = {}
    for genre, cfg in genres.items():
        keywords = (cfg or {}).get("keywords", []) or []
        result[str(genre)] = [str(k).lower() for k in keywords]
    return result


def _classify_genres(
    raw_tags: list[str],
    title: str,
    mapping: dict[str, list[str]],
) -> list[str]:
    """生のタグ・タイトルを、あらかじめ定義されたジャンル(mappingのキー)に分類する。"""
    return GenreMap(mapping).classify(title, raw_tags)


def _clean_html(raw: str) -> str:
    # trafilatura はHTML文字列からもテキスト抽出できるので、descriptionがHTMLの場合はそれを使う
    text = trafilatura.extract(raw, include_comments=False, include_tables=False)
    return text or raw


def _fetch_full_text(url: str) -> str | None:
    try:
        downloaded = trafilatura.fetch_url(url, no_ssl=False)
        if not downloaded:
            return None
        return trafilatura.extract(
            downloaded, include_comments=False, include_tables=False, favor_recall=True
        )
    except Exception as e:  # noqa: BLE001 - フィード取得は失敗しても全体を止めない
        log.warning("本文取得に失敗: %s (%s)", url, e)
        return None


def load_labels(labels_path: str | Path) -> dict[str, bool]:
    """config/labels.yaml を読み込む。無ければ空の辞書を返す。"""
    path = Path(labels_path)
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {str(k): bool(v) for k, v in data.items()}


def save_labels(labels_path: str | Path, labels: dict[str, bool]) -> None:
    path = Path(labels_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 見やすいように有効→無効、名前順で並べる
    ordered = dict(sorted(labels.items(), key=lambda kv: (not kv[1], kv[0])))
    yaml_text = yaml.safe_dump(ordered, allow_unicode=True, sort_keys=False)
    path.write_text(LABELS_HEADER_COMMENT + "\n" + yaml_text, encoding="utf-8")


def seed_labels(
    labels_path: str | Path,
    mapping_path: str | Path = DEFAULT_LABEL_MAPPING_PATH,
) -> dict[str, bool]:
    """config/label_mapping.yaml に定義されたジャンル一覧を元に、
    config/labels.yaml を作る/更新する。ジャンルは固定なのでフィードのスキャンは不要。
    既存のON/OFF状態は保持し、新しく増えたジャンルはON(有効)として追加する。
    label_mapping.yaml から無くなったジャンルは一覧から取り除く。
    """
    mapping = load_label_mapping(mapping_path)
    existing = load_labels(labels_path)
    merged = {genre: existing.get(genre, True) for genre in mapping}
    save_labels(labels_path, merged)
    return merged


def _articles_from_feed(
    feed: dict[str, Any],
    *,
    mapping: dict[str, list[str]],
    window: ArticleWindow,
    gate: LabelGate,
    max_per_feed: int,
) -> list[dict[str, Any]]:
    name, url = feed["name"], feed["url"]
    log.info("収集中: %s (%s)", name, url)
    try:
        parsed = feedparser.parse(url)
    except Exception as e:  # noqa: BLE001
        log.warning("フィード取得失敗: %s (%s)", name, e)
        return []

    if parsed.bozo and not parsed.entries:
        log.warning("フィードのパースに問題あり、スキップ: %s", name)
        return []

    articles: list[dict[str, Any]] = []
    for entry in parsed.entries:
        if len(articles) >= max_per_feed:
            break

        published = _entry_published(entry)
        if not window.includes(published):
            continue  # 古い記事は対象外

        raw_tags = _raw_entry_tags(entry)
        title = entry.get("title", "(タイトルなし)")
        entry_labels = _classify_genres(raw_tags, title, mapping)
        if not gate.allows(entry_labels):
            continue  # OFFにされたジャンルに分類された記事は除外

        link = entry.get("link", "")
        summary_raw = entry.get("summary", "") or entry.get("description", "")
        summary = _clean_html(summary_raw) if summary_raw else ""

        text = summary
        if len(summary) < MIN_TEXT_LEN_TO_SKIP_EXTRACTION and link:
            full_text = _fetch_full_text(link)
            if full_text and len(full_text) > len(summary):
                text = full_text

        if not text:
            log.info("本文が取得できずスキップ: %s", title)
            continue

        articles.append(
            {
                "title": title,
                "url": link,
                "labels": entry_labels,
                "source": name,
                "published": (published or datetime.now(tz=timezone.utc)).isoformat(),
                "text": text.strip(),
            }
        )
    return articles


def fetch_all(
    config_path: str | Path,
    labels_path: str | Path | None = None,
    mapping_path: str | Path = DEFAULT_LABEL_MAPPING_PATH,
) -> list[dict[str, Any]]:
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    mapping = load_label_mapping(mapping_path)

    disabled_labels: set[str] = set()
    if labels_path is not None:
        labels = load_labels(labels_path)
        disabled_labels = {label for label, enabled in labels.items() if not enabled}

    lookback_hours = config.get("lookback_hours", 26)
    max_per_feed = config.get("max_articles_per_feed", 6)
    window = ArticleWindow(datetime.now(tz=timezone.utc), lookback_hours)
    gate = LabelGate(disabled_labels)
    enabled = [feed for feed in config["feeds"] if feed.get("enabled", True)]

    articles: list[dict[str, Any]] = []
    if enabled:
        workers = min(8, len(enabled))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            groups = pool.map(
                lambda feed: _articles_from_feed(
                    feed,
                    mapping=mapping,
                    window=window,
                    gate=gate,
                    max_per_feed=max_per_feed,
                ),
                enabled,
            )
            for group in groups:
                articles.extend(group)

    log.info("収集完了: %d件", len(articles))
    return articles


def main() -> None:
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config/feeds.yaml"
    out_path = sys.argv[2] if len(sys.argv) > 2 else None
    labels_path = sys.argv[3] if len(sys.argv) > 3 else "config/labels.yaml"

    articles = fetch_all(config_path, labels_path)

    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        log.info("保存先: %s", out_path)
    else:
        print(json.dumps(articles, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
