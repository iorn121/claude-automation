"""
収集した記事を Gemini API (無料枠) でカテゴリ別に要約し、Podcast向けの読み上げ台本を作る。

無料枠のレート制限 (2026年時点の目安):
  - gemini-3.6-flash: 1日1,500リクエスト程度 / 1分10リクエスト (2026年9月時点の目安。Googleのモデル世代交代により
    今後モデル名や上限が変わることがあるので、404エラーが出たら環境変数 GEMINI_MODEL で
    別のモデル名に切り替えてください)
  - 1日1回の実行なら十分すぎるほど余裕がある

環境変数 GEMINI_API_KEY が必要 (https://ai.google.dev で無料取得)。
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from google import genai
from google.genai import errors as genai_errors

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("summarize")

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
MAX_CHARS_PER_ARTICLE = 1500  # 1記事あたり要約対象にするテキストの上限（トークン節約）

# Gemini側が一時的に混雑している(503 UNAVAILABLE)ことがあるため、
# 指数バックオフで数回リトライする(1日1回の実行なので多少待っても問題ない)。
MAX_RETRIES = 5
RETRY_BACKOFF_SECONDS = [15, 30, 60, 120, 180]

SYSTEM_PROMPT = """\
あなたは、エンジニア向けの日刊ニュースPodcastの構成作家 兼 パーソナリティです。
渡された記事リストをもとに、1人語りの読み上げ台本を日本語の口語体で作成してください。

# ルール
- 記事の文章をそのまま引用・転載しない。必ず自分の言葉で要約・言い換えること。
- 記事のカテゴリ(ラベル)ごとにセクションを分ける。記事が無いセクションは丸ごと省略する。
- 各記事は2〜3文程度で要点だけ話す。専門用語には一言だけ補足を添える。
- 同じ話題が複数記事にまたがる場合はまとめて1つの話題として扱う。
- 冒頭に短い挨拶（日付・今日のトピック数など）、末尾に短い締めの一言を入れる。
- 出力はそのままTTS（音声合成）にかけるプレーンテキストのみ。見出し記号(#, *, -)や絵文字、Markdown装飾は使わない。
- 各ニュース（各話題）のあいだと、カテゴリが変わるときは必ず空行を1行入れる。
  聞き手が前のニュースと混同しないよう、話題の区切りがテキスト上で分かるようにする。
- 全体の長さは合計3000〜6000文字程度を目安にする。
"""


def _build_user_prompt(articles: list[dict[str, Any]], target_date: str) -> str:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for a in articles:
        # 記事ごとに分類されたジャンル(labels)の先頭を見出しに使う。
        primary_label = (a.get("labels") or ["その他"])[0]
        grouped[primary_label].append(a)

    lines = [f"対象日: {target_date}", ""]
    for category, items in grouped.items():
        lines.append(f"## {category}")
        for a in items:
            text = a["text"][:MAX_CHARS_PER_ARTICLE]
            lines.append(f"- 出典: {a['source']} / タイトル: {a['title']}\n  本文抜粋: {text}")
        lines.append("")

    return "\n".join(lines)


def summarize(articles: list[dict[str, Any]], target_date: str, api_key: str) -> str:
    if not articles:
        return f"{target_date}分のニュースは収集できませんでした。対象フィードの設定を確認してください。"

    client = genai.Client(api_key=api_key)
    user_prompt = _build_user_prompt(articles, target_date)

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=user_prompt,
                config={
                    "system_instruction": SYSTEM_PROMPT,
                    "temperature": 0.6,
                },
            )
            script = (response.text or "").strip()
            if not script:
                raise RuntimeError("Gemini APIから空の応答が返りました")
            return script
        except genai_errors.ServerError as e:
            last_error = e
            if attempt >= MAX_RETRIES:
                break
            wait_sec = RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
            log.warning(
                "Gemini APIが一時的に利用できません(%s回目/%s回): %s -- %d秒待ってリトライします",
                attempt, MAX_RETRIES, e, wait_sec,
            )
            time.sleep(wait_sec)

    raise RuntimeError(f"Gemini APIへの要約リクエストが{MAX_RETRIES}回とも失敗しました: {last_error}")


def main() -> None:
    articles_path = sys.argv[1] if len(sys.argv) > 1 else "data/articles.json"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "data/script.txt"
    target_date = sys.argv[3] if len(sys.argv) > 3 else date.today().isoformat()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("環境変数 GEMINI_API_KEY を設定してください")

    with open(articles_path, encoding="utf-8") as f:
        articles = json.load(f)

    script = summarize(articles, target_date, api_key)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(script)

    log.info("台本を保存しました: %s (%d文字)", out_path, len(script))


if __name__ == "__main__":
    main()
