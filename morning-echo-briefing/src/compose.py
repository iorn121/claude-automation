"""事実の列挙から、そのまま読める短い台本を作る。

Gemini が使えるときは口語の台本に整える。失敗したとき、キーが無いときは
定型文を返す。朝の通知自体は止めない。
"""

from __future__ import annotations

import logging
import os
from datetime import date

from content import (
    CalendarEvent,
    NewsItem,
    TaskItem,
    build_fallback_script,
    build_model_prompt,
    finalize_script,
)

log = logging.getLogger("compose")

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = [10, 20, 40]

SYSTEM_PROMPT = """\
あなたは、個人の朝の予定を Echo スピーカーで読み上げる台本作家です。
渡された予定・タスク・ニュースだけを使い、1人語りの日本語の口語体にしてください。

# ルール
- 渡されていない予定やニュースを足さない。数字や時刻を変えない。
- ニュース記事の文章は転載しない。見出しの内容を1文で言い換える。
- 予定は時刻が分かるようにすべて触れる。件数が8件を超える場合だけ、近い時刻を優先してまとめる。
- タスクは期限切れ、今日、明日の順に触れる。
- 出力は TTS にかけるプレーンテキストのみ。Markdown、箇条書き、絵文字、URL、見出し記号は使わない。
- 全体は 500〜900 文字。短く、句点で区切る。
- 冒頭は「おはようございます」と日付。末尾は「以上です。よい一日を。」で終える。
- 音声クレジットの文は書かない。後段で付ける。
"""


def _from_model(prompt: str, api_key: str) -> str:
    import time

    from google import genai
    from google.genai import errors as genai_errors

    client = genai.Client(api_key=api_key)
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config={
                    "system_instruction": SYSTEM_PROMPT,
                    "temperature": 0.4,
                },
            )
            text = (response.text or "").strip()
            if len(text) < 40:
                raise RuntimeError("応答が短すぎます")
            return finalize_script(text)
        except Exception as exc:
            last_error = exc
            transient = isinstance(exc, (genai_errors.ServerError, RuntimeError, TimeoutError))
            if not transient or attempt >= MAX_RETRIES:
                break
            wait_sec = RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
            log.warning(
                "台本生成を再試行します (%d/%d, %s)。%d秒待ちます",
                attempt,
                MAX_RETRIES,
                type(exc).__name__,
                wait_sec,
            )
            time.sleep(wait_sec)
    raise RuntimeError(type(last_error).__name__ if last_error else "unknown")


def compose_script(
    today: date,
    events: list[CalendarEvent],
    tasks: list[TaskItem],
    news: list[NewsItem],
    api_key: str | None,
) -> tuple[str, str]:
    fallback = build_fallback_script(today, events, tasks, news)
    if not api_key:
        log.info("GEMINI_API_KEY が無いため定型の台本を使います")
        return fallback, "fallback"
    try:
        script = _from_model(build_model_prompt(today, events, tasks, news), api_key)
    except Exception as exc:
        log.warning("定型の台本に切り替えます (%s)", type(exc).__name__)
        return fallback, "fallback"
    log.info("台本を生成しました (%d文字)", len(script))
    return script, "gemini"
