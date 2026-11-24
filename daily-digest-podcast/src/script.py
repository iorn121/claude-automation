"""台本の話者タグと、読み上げ用の文の区切り。合成APIは知らない。"""

from __future__ import annotations

import re

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
_SPEAKER_TAG_RE = re.compile(r"^([^:：\n]{1,20})[:：]\s*(.*)$")


def resolve_speaker_role(tag_name: str) -> str | None:
    key = tag_name.strip()
    if key in SPEAKER_TAG_ALIASES:
        return SPEAKER_TAG_ALIASES[key]
    return SPEAKER_TAG_ALIASES.get(key.lower())


def split_into_news_blocks(text: str) -> list[str]:
    blocks = re.split(r"\n\s*\n+", text.strip())
    return [block.strip() for block in blocks if block.strip()]


def parse_block_turns(block: str) -> list[tuple[str, str]]:
    turns: list[tuple[str, str]] = []
    current_role = "host"
    current_parts: list[str] = []

    def flush() -> None:
        nonlocal current_parts
        spoken = "\n".join(current_parts).strip()
        if spoken:
            turns.append((current_role, spoken))
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
    turns: list[tuple[str, str]] = []
    for block in split_into_news_blocks(script):
        turns.extend(parse_block_turns(block))
    return turns


def split_script(text: str, max_len: int = 120) -> list[str]:
    raw_sentences = re.split(r"(?<=[。！？\n])", text)
    sentences = [sentence.strip() for sentence in raw_sentences if sentence.strip()]
    chunks: list[str] = []
    buf = ""
    for sentence in sentences:
        if buf and len(buf) + len(sentence) > max_len:
            chunks.append(buf)
            buf = sentence
        else:
            buf += sentence
    if buf:
        chunks.append(buf)
    return chunks
