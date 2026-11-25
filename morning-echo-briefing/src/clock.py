"""アナウンス時刻までの待ち時間。

定時ジョブは生成に数分かかる。鳴ってほしい時刻の少し前に起動し、
準備が終わってからその時刻まで待つ。手動実行で時刻が遠いときは待たない。
"""

from __future__ import annotations

from datetime import datetime


def parse_hhmm(value: str) -> tuple[int, int]:
    hour_text, minute_text = value.strip().split(":")
    hour, minute = int(hour_text), int(minute_text)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"時刻の形式が不正です: {value}")
    return hour, minute


def seconds_until(now: datetime, hhmm: str, max_wait_sec: int = 40 * 60) -> int:
    """now がアナウンス時刻の少し前なら待つ秒数。過ぎている、または遠すぎるなら 0。"""
    if now.tzinfo is None:
        raise ValueError("タイムゾーン付きの現在時刻が必要です")
    hour, minute = parse_hhmm(hhmm)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    delta = int((target - now).total_seconds())
    if delta <= 0 or delta > max_wait_sec:
        return 0
    return delta
