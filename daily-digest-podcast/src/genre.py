"""記事をジャンルへ分類する。フィード取得とは別に、言葉の一致だけを知る。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

FALLBACK_GENRE = "その他"

class ArticleWindow:
    """公開時刻が振り返り時間より前の記事は捨てる。時刻が無い記事は残す。"""

    def __init__(self, now: datetime, lookback_hours: int):
        self.cutoff = now.astimezone(timezone.utc) - timedelta(hours=lookback_hours)

    def includes(self, published: datetime | None) -> bool:
        return published is None or published >= self.cutoff


class LabelGate:
    """OFF のジャンルが一つでも付いた記事は載せない。OFF が無ければ全部載せる。"""

    def __init__(self, disabled: set[str]):
        self.disabled = disabled

    def allows(self, labels: list[str]) -> bool:
        if not self.disabled:
            return True
        return not any(label in self.disabled for label in labels)


class GenreMap:
    def __init__(self, mapping: dict[str, list[str]]):
        self._mapping = mapping

    def classify(self, title: str, tags: list[str] | None = None) -> list[str]:
        haystack = " ".join([*(tags or []), title]).lower()
        matched = [
            genre
            for genre, keywords in self._mapping.items()
            if any(_keyword_matches(haystack, keyword.lower()) for keyword in keywords)
        ]
        if matched:
            return matched
        if FALLBACK_GENRE in self._mapping:
            return [FALLBACK_GENRE]
        return []


def _keyword_matches(haystack: str, keyword: str) -> bool:
    """英数字だけのキーワードは単語境界で見る。日本語は部分一致。"""
    if re.fullmatch(r"[a-z0-9 \-]+", keyword):
        pattern = r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])"
        return re.search(pattern, haystack) is not None
    return keyword in haystack
