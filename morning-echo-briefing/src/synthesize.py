"""台本を VOICEVOX ENGINE で mp3 にする。

Flash Briefing の音声フィードに合わせ、256kbps・11秒以上・およそ -14 LUFS で書き出す。
クレジット表記は台本側（content.VOICE_CREDIT_LINE）で付ける。
"""

from __future__ import annotations

import io
import logging
import os
import re
import time
from pathlib import Path

import requests
from pydub import AudioSegment

log = logging.getLogger("synthesize")

DEFAULT_VOICEVOX_URL = os.environ.get("VOICEVOX_URL", "http://127.0.0.1:50021")
DEFAULT_SPEAKER = int(os.environ.get("VOICEVOX_SPEAKER", "8"))
MAX_CHUNK_LEN = 120
SILENCE_BETWEEN_CHUNKS_MS = 250
MIN_DURATION_MS = 11_000


def wait_for_engine(base_url: str, timeout_sec: int = 120) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            response = requests.get(f"{base_url}/version", timeout=5)
            if response.ok:
                log.info("VOICEVOX ENGINE 起動確認OK")
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    raise RuntimeError(f"VOICEVOX ENGINE ({base_url}) に接続できませんでした")


def split_script(text: str, max_len: int = MAX_CHUNK_LEN) -> list[str]:
    raw_sentences = re.split(r"(?<=[。！？\n])", text)
    sentences = [sentence.strip() for sentence in raw_sentences if sentence.strip()]
    chunks: list[str] = []
    buffer = ""
    for sentence in sentences:
        if buffer and len(buffer) + len(sentence) > max_len:
            chunks.append(buffer)
            buffer = sentence
        else:
            buffer += sentence
    if buffer:
        chunks.append(buffer)
    return chunks


def synthesize_chunk(base_url: str, text: str, speaker: int) -> bytes:
    query_res = requests.post(
        f"{base_url}/audio_query",
        params={"text": text, "speaker": speaker},
        timeout=30,
    )
    query_res.raise_for_status()
    synth_res = requests.post(
        f"{base_url}/synthesis",
        params={"speaker": speaker},
        json=query_res.json(),
        timeout=60,
    )
    synth_res.raise_for_status()
    return synth_res.content


def _export_mp3(segment: AudioSegment, out_path: Path) -> None:
    common = {"format": "mp3", "bitrate": "256k", "parameters": ["-ac", "1"]}
    try:
        segment.export(
            out_path,
            parameters=["-ac", "1", "-af", "loudnorm=I=-14:TP=-2:LRA=11"],
            format="mp3",
            bitrate="256k",
        )
    except Exception:
        log.warning("ラウドネス正規化に失敗したため、音量補正なしで書き出します")
        segment.export(out_path, **common)


def synthesize_script(
    script: str,
    out_path: str | Path,
    base_url: str = DEFAULT_VOICEVOX_URL,
    speaker: int = DEFAULT_SPEAKER,
) -> None:
    wait_for_engine(base_url)
    chunks = split_script(script)
    if not chunks:
        raise RuntimeError("台本が空です")
    log.info("音声合成対象: %d チャンク", len(chunks))

    combined = AudioSegment.silent(duration=0)
    silence = AudioSegment.silent(duration=SILENCE_BETWEEN_CHUNKS_MS)
    for index, chunk in enumerate(chunks, start=1):
        log.info("合成中 (%d/%d)", index, len(chunks))
        wav_bytes = synthesize_chunk(base_url, chunk, speaker)
        segment = AudioSegment.from_file(io.BytesIO(wav_bytes), format="wav")
        combined += segment + silence

    if len(combined) < MIN_DURATION_MS:
        combined += AudioSegment.silent(duration=MIN_DURATION_MS - len(combined))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _export_mp3(combined, out_path)
    log.info("音声ファイルを書き出しました (%.1f秒)", len(combined) / 1000)
