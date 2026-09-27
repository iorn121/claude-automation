"""ニュース間の無音（間）が計画どおり入ることを検証する。"""
from __future__ import annotations

import io
import sys
import wave
from pathlib import Path

import pytest
from pydub import AudioSegment

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import synthesize as syn  # noqa: E402


def _silent_wav_bytes(duration_ms: int = 100, framerate: int = 24000) -> bytes:
    """指定長の無音 WAV をバイト列で返す（VOICEVOXなしで組立を検証するため）。"""
    n_frames = int(framerate * duration_ms / 1000)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(framerate)
        wf.writeframes(b"\x00\x00" * n_frames)
    return buf.getvalue()


def test_split_into_news_blocks_by_blank_line() -> None:
    script = "挨拶です。\n\nニュース1です。続きます。\n\nニュース2です。"
    blocks = syn.split_into_news_blocks(script)
    assert len(blocks) == 3
    assert "ニュース1" in blocks[1]
    assert "ニュース2" in blocks[2]


def test_plan_synthesis_inserts_long_silence_between_news() -> None:
    script = (
        "こんにちは、今日のダイジェストです。\n\n"
        "AI関連です。モデルが更新されました。精度が上がっています。\n\n"
        "セキュリティです。脆弱性が公開されました。"
    )
    plan = syn.plan_synthesis(script)

    assert len(plan) >= 3
    # ニュース境界の直後無音は SILENCE_BETWEEN_NEWS_MS 以上
    long_gaps = [s for _, _, s in plan if s >= syn.SILENCE_BETWEEN_NEWS_MS]
    assert len(long_gaps) >= 2
    assert all(s == syn.SILENCE_BETWEEN_NEWS_MS for s in long_gaps)
    # 末尾は無音0
    assert plan[-1][2] == 0
    # 同一ニュース内に複数チャンクがある場合は短い無音もある
    short_gaps = [s for _, _, s in plan if 0 < s < syn.SILENCE_BETWEEN_NEWS_MS]
    # 文が短いと1チャンクにまとまることもあるので、短無音は0以上でOK
    assert all(s == syn.SILENCE_BETWEEN_CHUNKS_MS for s in short_gaps)


def test_plan_synthesis_single_block_has_no_news_gap() -> None:
    script = "一文だけです。"
    plan = syn.plan_synthesis(script)
    assert len(plan) == 1
    assert plan[0][2] == 0


def test_assemble_from_plan_duration_includes_news_silence() -> None:
    """組立後の総時間が、チャンク長 + ニュース間無音を含むことを確認する。"""
    speech_ms = 100
    script = "話題Aです。\n\n話題Bです。\n\n話題Cです。"
    plan = syn.plan_synthesis(script)
    assert len(plan) == 3
    assert plan[0][2] == syn.SILENCE_BETWEEN_NEWS_MS
    assert plan[1][2] == syn.SILENCE_BETWEEN_NEWS_MS
    assert plan[2][2] == 0

    wavs = [_silent_wav_bytes(speech_ms) for _ in plan]
    audio = syn.assemble_from_plan(plan, wavs)

    expected_ms = speech_ms * 3 + syn.SILENCE_BETWEEN_NEWS_MS * 2
    # pydub の長さはフレーム丸めで ±数ms ずれることがある
    assert abs(len(audio) - expected_ms) <= 20

def test_silence_between_news_is_at_least_two_seconds() -> None:
    assert syn.SILENCE_BETWEEN_NEWS_MS >= 2000
    assert syn.SILENCE_BETWEEN_NEWS_MS <= 5000  # 極端に長くしない上限の目安
