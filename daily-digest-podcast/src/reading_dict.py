"""
読み上げマスタ（config/reading_dict.yaml）の読み込みと台本への適用。

VOICEVOX は英字固有名詞の読みを誤りやすい（例: Qiita →「ちーた」）。
台本を合成する直前に、マスタの reading（カタカナ等）へ置換して精度を上げる。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable

import yaml

log = logging.getLogger("reading_dict")

DEFAULT_DICT_PATH = Path(__file__).resolve().parent.parent / "config" / "reading_dict.yaml"

# 英数字＋よく出る記号だけの surface は単語境界で置換する
_ASCII_WORD_RE = re.compile(r"^[A-Za-z0-9+#./_ -]+$")


def load_reading_dict(path: str | Path | None = None) -> list[tuple[str, str]]:
    """YAML から (surface, reading) のリストを返す。長い surface を先に並べる。"""
    dict_path = Path(path) if path else DEFAULT_DICT_PATH
    if not dict_path.exists():
        log.warning("読み上げマスタがありません: %s", dict_path)
        return []

    with open(dict_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    entries: list[tuple[str, str]] = []
    for item in data.get("readings") or []:
        if not isinstance(item, dict):
            continue
        surface = str(item.get("surface") or "").strip()
        reading = str(item.get("reading") or "").strip()
        if not surface or not reading:
            log.warning("不正な読み上げエントリをスキップ: %r", item)
            continue
        entries.append((surface, reading))

    # 長い表記を先に置換（"GitHub Actions" が "GitHub" より先、など）
    entries.sort(key=lambda pair: len(pair[0]), reverse=True)
    return entries


def _compile_pattern(surface: str) -> re.Pattern[str]:
    escaped = re.escape(surface)
    if _ASCII_WORD_RE.fullmatch(surface):
        # 前後が英数字でない位置でのみマッチ（大文字小文字無視）
        return re.compile(
            rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])",
            re.IGNORECASE,
        )
    return re.compile(escaped)


def apply_readings(
    text: str,
    entries: Iterable[tuple[str, str]] | None = None,
    dict_path: str | Path | None = None,
) -> str:
    """台本テキストに読み上げマスタを適用した文字列を返す。"""
    pairs = list(entries) if entries is not None else load_reading_dict(dict_path)
    if not pairs:
        return text

    # 呼び出し側が順不同でも、長い surface を優先する
    pairs.sort(key=lambda pair: len(pair[0]), reverse=True)

    result = text
    for surface, reading in pairs:
        pattern = _compile_pattern(surface)
        result = pattern.sub(reading, result)
    return result
