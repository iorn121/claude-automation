"""
台本テキストを VOICEVOX ENGINE (無料・商用利用可) で音声合成し、1本のmp3にまとめる。

前提: VOICEVOX ENGINE がどこかで起動していて、そのREST APIにアクセスできること。
  - ローカル/CI: `docker run -p 50021:50021 voicevox/voicevox_engine:cpu-latest` などで起動
  - 環境変数 VOICEVOX_URL (デフォルト http://127.0.0.1:50021)
  - 環境変数 VOICEVOX_SPEAKER_HOST (ホスト話者ID。未設定時は VOICEVOX_SPEAKER、さらに無ければ 8
    = "春日部つむぎ(ノーマル)")
  - 環境変数 VOICEVOX_SPEAKER_GUEST (ゲスト話者ID。デフォルト 3 = "ずんだもん(ノーマル)")
  - 互換: VOICEVOX_SPEAKER はホストのフォールバック
    GET {VOICEVOX_URL}/speakers で一覧取得可能

注意: VOICEVOXの利用規約により、使用したキャラクターのクレジット表記が必要です。
  例: 「VOICEVOX:春日部つむぎ および VOICEVOX:ずんだもん を使用」
  台本や配信ページに一言添えてください。

台本はホスト＋コホストの対話形式を想定する。各発言は行頭タグで話者を示す:
  つむぎ: ……
  ずんだもん: ……
タグ自体は読み上げず、話者IDを切り替えて合成する。
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

from reading_dict import apply_readings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("synthesize")

DEFAULT_VOICEVOX_URL = os.environ.get("VOICEVOX_URL", "http://127.0.0.1:50021")
MAX_CHUNK_LEN = 120  # 1リクエストあたりの文字数目安（長すぎると合成が不安定/遅くなるため分割する）
# 同一ニュース内の文チャンク間（短い間）
SILENCE_BETWEEN_CHUNKS_MS = 250
# 読み上げマスタ（config/reading_dict.yaml）。VOICEVOX直前に英字固有名詞などをカタカナへ置換する。
READING_DICT_PATH = Path(__file__).resolve().parent.parent / "config" / "reading_dict.yaml"
# ニュース／段落の区切り（次の話題へ移るときの間）。最低2〜3秒を確保
SILENCE_BETWEEN_NEWS_MS = int(os.environ.get("SILENCE_BETWEEN_NEWS_MS", "2500"))

# 対話台本の行頭タグ → 役割
SPEAKER_TAG_ALIASES: dict[str, str] = {
    "つむぎ": "host",
    "ホスト": "host",
    "host": "host",
    "a": "host",
    "ずんだもん": "guest",
    "ゲスト": "guest",
    "guest": "guest",
    "b": "guest",
}
# 行頭「話者名: 本文」（全角コロンも許容）
_SPEAKER_TAG_RE = re.compile(r"^([^:：\n]{1,20})[:：]\s*(.*)$")


def resolve_host_speaker() -> int:
    raw = os.environ.get("VOICEVOX_SPEAKER_HOST") or os.environ.get("VOICEVOX_SPEAKER", "8")
    return int(raw)


def resolve_guest_speaker() -> int:
    return int(os.environ.get("VOICEVOX_SPEAKER_GUEST", "3"))


# モジュール読み込み時のデフォルト（テストで env を変えたあとは resolve_* を使う）
DEFAULT_HOST_SPEAKER = resolve_host_speaker()
DEFAULT_GUEST_SPEAKER = resolve_guest_speaker()
# 後方互換エイリアス
DEFAULT_SPEAKER = DEFAULT_HOST_SPEAKER


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


def split_into_news_blocks(text: str) -> list[str]:
    """空行で区切られたニュース／セクション単位のブロックに分割する。"""
    blocks = re.split(r"\n\s*\n+", text.strip())
    return [b.strip() for b in blocks if b.strip()]


def resolve_speaker_role(tag_name: str) -> str | None:
    """話者タグ名を host/guest に解決する。未知なら None。"""
    key = tag_name.strip()
    if key in SPEAKER_TAG_ALIASES:
        return SPEAKER_TAG_ALIASES[key]
    lower = key.lower()
    return SPEAKER_TAG_ALIASES.get(lower)


def parse_block_turns(block: str) -> list[tuple[str, str]]:
    """1ニュースブロックを (role, text) の発話列に分解する。

    行頭に既知の話者タグがあれば役割を切り替え、タグ自体は本文から除く。
    タグ無し行は直前の話者（冒頭は host）の続きとみなす。
    """
    turns: list[tuple[str, str]] = []
    current_role = "host"
    current_parts: list[str] = []

    def flush() -> None:
        nonlocal current_parts
        text = "\n".join(current_parts).strip()
        if text:
            turns.append((current_role, text))
        current_parts = []

    for raw_line in block.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        matched = _SPEAKER_TAG_RE.match(line)
        if matched:
            role = resolve_speaker_role(matched.group(1))
            if role is not None:
                flush()
                current_role = role
                rest = matched.group(2).strip()
                current_parts = [rest] if rest else []
                continue
        current_parts.append(line)

    flush()
    return turns


def parse_dialogue(script: str) -> list[tuple[str, str]]:
    """台本全体を話者タグ付き発話の平坦リストにする（テスト・検証用）。"""
    turns: list[tuple[str, str]] = []
    for block in split_into_news_blocks(script):
        turns.extend(parse_block_turns(block))
    return turns


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


def plan_synthesis(
    script: str,
    max_len: int = MAX_CHUNK_LEN,
    *,
    host_speaker: int | None = None,
    guest_speaker: int | None = None,
) -> list[tuple[str, int, int]]:
    """台本を (読み上げテキスト, 話者ID, 直後の無音ms) の列に展開する。

    話者タグは除去済みテキストだけが読み上げ対象になる。
    同一ニュース内の文チャンク間は短い無音、ニュース（段落）境界では長い無音を入れる。
    末尾チャンクの直後の無音は 0。
    """
    host_id = resolve_host_speaker() if host_speaker is None else host_speaker
    guest_id = resolve_guest_speaker() if guest_speaker is None else guest_speaker
    role_to_id = {"host": host_id, "guest": guest_id}

    blocks = split_into_news_blocks(script)
    plan: list[tuple[str, int, int]] = []
    for bi, block in enumerate(blocks):
        turns = parse_block_turns(block)
        # タグも本文も無い空ブロックはスキップ
        turn_chunks: list[tuple[str, int]] = []
        for role, text in turns:
            speaker_id = role_to_id[role]
            for chunk in split_script(text, max_len=max_len):
                turn_chunks.append((chunk, speaker_id))

        for ci, (chunk, speaker_id) in enumerate(turn_chunks):
            is_last_chunk_in_block = ci == len(turn_chunks) - 1
            is_last_block = bi == len(blocks) - 1
            if is_last_chunk_in_block and is_last_block:
                silence_ms = 0
            elif is_last_chunk_in_block:
                silence_ms = SILENCE_BETWEEN_NEWS_MS
            else:
                silence_ms = SILENCE_BETWEEN_CHUNKS_MS
            plan.append((chunk, speaker_id, silence_ms))
    return plan


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


def assemble_from_plan(
    plan: list[tuple[str, int, int]] | list[tuple[str, int]],
    wav_by_index: list[bytes],
) -> AudioSegment:
    """plan と対応する WAV バイト列から最終 AudioSegment を組み立てる。

    plan 要素は (text, speaker_id, silence_ms) または旧形式 (text, silence_ms)。
    """
    if len(plan) != len(wav_by_index):
        raise ValueError("plan と wav_by_index の長さが一致しません")

    combined = AudioSegment.silent(duration=0)
    for item, wav_bytes in zip(plan, wav_by_index):
        silence_ms = item[-1]
        segment = AudioSegment.from_file(io.BytesIO(wav_bytes), format="wav")
        combined += segment
        if silence_ms > 0:
            combined += AudioSegment.silent(duration=silence_ms)
    return combined


def synthesize_script(
    script: str,
    out_path: str | Path,
    base_url: str = DEFAULT_VOICEVOX_URL,
    speaker: int | None = None,
    guest_speaker: int | None = None,
    reading_dict_path: str | Path | None = READING_DICT_PATH,
) -> None:
    """台本を対話形式として合成する。

    speaker はホスト話者ID（未指定時は環境変数）。guest_speaker はゲスト。
    """
    host_id = resolve_host_speaker() if speaker is None else speaker
    guest_id = resolve_guest_speaker() if guest_speaker is None else guest_speaker

    wait_for_engine(base_url)
    plan = plan_synthesis(script, host_speaker=host_id, guest_speaker=guest_id)

    # Issue #3: タグ除去後の本文に読み上げマスタを適用してから合成する
    spoken_plan: list[tuple[str, int, int]] = []
    readings_applied = False
    for text, spk, silence_ms in plan:
        spoken = apply_readings(text, dict_path=reading_dict_path)
        if spoken != text:
            readings_applied = True
        spoken_plan.append((spoken, spk, silence_ms))
    if readings_applied:
        log.info("読み上げマスタを適用しました（%s）", reading_dict_path)

    log.info(
        "音声合成対象: %d チャンク (host=%s guest=%s ニュース区切り無音=%dms)",
        len(spoken_plan),
        host_id,
        guest_id,
        SILENCE_BETWEEN_NEWS_MS,
    )

    wavs: list[bytes] = []
    for i, (chunk, spk, silence_ms) in enumerate(spoken_plan, start=1):
        log.info(
            "合成中 (%d/%d, speaker=%s, 直後無音=%dms): %s",
            i,
            len(spoken_plan),
            spk,
            silence_ms,
            chunk[:30],
        )
        wavs.append(synthesize_chunk(base_url, chunk, spk))

    combined = assemble_from_plan(spoken_plan, wavs)

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
