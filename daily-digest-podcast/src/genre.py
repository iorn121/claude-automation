"""記事をジャンルへ分類する。フィード取得とは別に、言葉の一致だけを知る。"""

from __future__ import annotations

import re

FALLBACK_GENRE = "その他"


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
