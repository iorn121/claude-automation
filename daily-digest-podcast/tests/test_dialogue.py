"""対話台本の話者タグ分割と話者割当のユニットテスト。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import synthesize as syn  # noqa: E402
from reading_dict import apply_readings  # noqa: E402


SAMPLE_DIALOGUE = """\
つむぎ: こんにちは、今日のダイジェストです。

つむぎ: AI関連です。新しいモデルが公開されました。精度が上がっています。
ずんだもん: それは気になるのだ。

つむぎ: セキュリティです。Qiitaで話題の脆弱性対策を紹介します。
ずんだもん: 早めのアップデートが大事なのだ。
"""


def test_parse_dialogue_strips_tags_and_assigns_roles() -> None:
    turns = syn.parse_dialogue(SAMPLE_DIALOGUE)
    assert turns[0] == ("host", "こんにちは、今日のダイジェストです。")
    assert turns[1][0] == "host"
    assert "AI関連" in turns[1][1]
    assert turns[2] == ("guest", "それは気になるのだ。")
    assert turns[3][0] == "host"
    assert "Qiita" in turns[3][1]
    assert turns[4][0] == "guest"
    # タグ文字列自体が本文に残らない
    flat = " ".join(text for _, text in turns)
    assert "つむぎ:" not in flat
    assert "ずんだもん:" not in flat


def test_parse_block_turns_accepts_fullwidth_colon_and_aliases() -> None:
    block = "ホスト：要点です。\nゲスト: 補足なのだ。"
    turns = syn.parse_block_turns(block)
    assert turns == [("host", "要点です。"), ("guest", "補足なのだ。")]


def test_untagged_script_defaults_to_host() -> None:
    turns = syn.parse_dialogue("一人語りの台本です。続きもあります。")
    assert len(turns) == 1
    assert turns[0][0] == "host"
    assert "一人語り" in turns[0][1]


def test_plan_synthesis_assigns_distinct_speakers() -> None:
    plan = syn.plan_synthesis(SAMPLE_DIALOGUE, host_speaker=8, guest_speaker=3)
    speakers = {spk for _, spk, _ in plan}
    assert speakers == {8, 3}
    # タグが読み上げテキストに混入しない
    for text, _spk, _sil in plan:
        assert not text.startswith("つむぎ")
        assert not text.startswith("ずんだもん")
        assert "つむぎ:" not in text
        assert "ずんだもん:" not in text


def test_plan_synthesis_keeps_news_silence_with_dialogue() -> None:
    plan = syn.plan_synthesis(SAMPLE_DIALOGUE, host_speaker=8, guest_speaker=3)
    assert plan[-1][2] == 0
    long_gaps = [sil for _, _, sil in plan if sil >= syn.SILENCE_BETWEEN_NEWS_MS]
    # 挨拶 / AI話題 / セキュリティ話題 → 境界は2つ以上
    assert len(long_gaps) >= 2
    assert all(sil == syn.SILENCE_BETWEEN_NEWS_MS for sil in long_gaps)


def test_reading_dict_applies_after_tag_strip() -> None:
    """タグ除去後の本文に対して reading_dict が効くこと（合成前と同じ順序）。"""
    turns = syn.parse_dialogue(SAMPLE_DIALOGUE)
    host_security = next(t for role, t in turns if role == "host" and "Qiita" in t)
    spoken = apply_readings(host_security, entries=[("Qiita", "キータ")])
    assert "キータ" in spoken
    assert "Qiita" not in spoken


def test_unknown_tag_is_not_stripped() -> None:
    """未知の話者名付き行はロール切替せず、行全体を本文として残す。"""
    turns = syn.parse_block_turns("ナレーター: これは未知タグです。")
    assert len(turns) == 1
    assert turns[0][0] == "host"
    assert "ナレーター:" in turns[0][1]


def test_resolve_speakers_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICEVOX_SPEAKER_HOST", "10")
    monkeypatch.setenv("VOICEVOX_SPEAKER_GUEST", "3")
    monkeypatch.delenv("VOICEVOX_SPEAKER", raising=False)
    assert syn.resolve_host_speaker() == 10
    assert syn.resolve_guest_speaker() == 3


def test_host_falls_back_to_voicevox_speaker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOICEVOX_SPEAKER_HOST", raising=False)
    monkeypatch.setenv("VOICEVOX_SPEAKER", "8")
    assert syn.resolve_host_speaker() == 8


def test_system_prompt_requests_dialogue_tags() -> None:
    import summarize

    prompt = summarize.SYSTEM_PROMPT
    assert "つむぎ:" in prompt or "つむぎ" in prompt
    assert "ずんだもん" in prompt
    assert "ホスト" in prompt


def test_voice_credit_names_both_characters() -> None:
    import publish

    assert "春日部つむぎ" in publish.VOICE_CREDIT
    assert "ずんだもん" in publish.VOICE_CREDIT
