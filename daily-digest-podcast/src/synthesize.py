"""
台本テキストを VOICEVOX ENGINE (無料・商用利用可) で音声合成し、1本のmp3にまとめる。

前提: VOICEVOX ENGINE がどこかで起動していて、そのREST APIにアクセスできること。
  - ローカル/CI: `docker run -p 50021:50021 voicevox/voicevox_engine:cpu-latest` などで起動
  - 環境変数 VOICEVOX_URL (デフォルト http://127.0.0.1:50021)
  - 環境変数 VOICEVOX_SPEAKER (話者ID。デフォルト 8 = "春日部つむぎ(ノーマル)"。
    GET {VOICEVOX_URL}/speakers で一覧取得可能)

注意: VOICEVOXの利用規約により、使用したキャラクターのクレジット表記が必要です。
  例: 「このPodcastの音声は VOICEVOX:春日部つむぎ を使用しています」
  台本や配信ページに一言添えてください。
"""
from __future__ import annotations

import io
import logging
import os
import re
import sys
import time
from pathlib import Path

import requests
from pydub import AudioSegment

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("synthesize")

DEFAULT_VOICEVOX_URL = os.environ.get("VOICEVOX_URL", "http://127.0.0.1:50021")
DEFAULT_SPEAKER = int(os.environ.get("VOICEVOX_SPEAKER", "8"))
MAX_CHUNK_LEN = 120  # 1リクエストあたりの文字数目安（長すぎると合成が不安定/遅くなるため分割する）
SILENCE_BETWEEN_CHUNKS_MS = 250


def wait_for_engine(base_url: str, timeout_sec: int = 120) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            r = requests.get(f"{base_url}/version", timeout=5)
            if r.ok:
                log.info("VOICEVOX ENGINE 起動確認OK (%s)", r.text.strip())
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    raise RuntimeError(f"VOICEVOX ENGINE ({base_url}) に接続できませんでした")


def split_script(text: str, max_len: int = MAX_CHUNK_LEN) -> list[str]:
    """句点・改行で区切りつつ、max_len程度のまとまりに再結合する。"""
    raw_sentences = re.split(r"(?<=[。！？\n])", text)
    sentences = [s.strip() for s in raw_sentences if s.strip()]

    chunks: list[str] = []
    buf = ""
    for sent in sentences:
        if buf and len(buf) + len(sent) > max_len:
            chunks.append(buf)
            buf = sent
        else:
            buf += sent
    if buf:
        chunks.append(buf)
    return chunks


def synthesize_chunk(base_url: str, text: str, speaker: int) -> bytes:
    query_res = requests.post(
        f"{base_url}/audio_query",
        params={"text": text, "speaker": speaker},
        timeout=30,
    )
    query_res.raise_for_status()
    query = query_res.json()

    synth_res = requests.post(
        f"{base_url}/synthesis",
        params={"speaker": speaker},
        json=query,
        timeout=60,
    )
    synth_res.raise_for_status()
    return synth_res.content  # WAVバイト列


def synthesize_script(
    script: str,
    out_path: str | Path,
    base_url: str = DEFAULT_VOICEVOX_URL,
    speaker: int = DEFAULT_SPEAKER,
) -> None:
    wait_for_engine(base_url)
    chunks = split_script(script)
    log.info("音声合成対象: %d チャンク", len(chunks))

    combined = AudioSegment.silent(duration=0)
    silence = AudioSegment.silent(duration=SILENCE_BETWEEN_CHUNKS_MS)

    for i, chunk in enumerate(chunks, start=1):
        log.info("合成中 (%d/%d): %s", i, len(chunks), chunk[:30])
        wav_bytes = synthesize_chunk(base_url, chunk, speaker)
        segment = AudioSegment.from_file(io.BytesIO(wav_bytes), format="wav")
        combined += segment + silence

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    combined.export(out_path, format="mp3", bitrate="128k")
    log.info(
        "音声ファイルを書き出しました: %s (%.1f分)",
        out_path,
        len(combined) / 1000 / 60,
    )


def main() -> None:
    script_path = sys.argv[1] if len(sys.argv) > 1 else "data/script.txt"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "data/episode.mp3"

    with open(script_path, encoding="utf-8") as f:
        script = f.read()

    synthesize_script(script, out_path)


if __name__ == "__main__":
    main()
