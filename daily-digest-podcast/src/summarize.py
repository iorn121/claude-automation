"""
収集した記事を Gemini API (無料枠) でカテゴリ別に要約し、Podcast向けの読み上げ台本を作る。

無料枠のレート制限 (2026年時点の目安):
  - gemini-3.6-flash: 1日1,500リクエスト程度 / 1分10リクエスト (2026年9月時点の目安。Googleのモデル世代交代により
    今後モデル名や上限が変わることがあるので、404エラーが出たら環境変数 GEMINI_MODEL で
    別のモデル名に切り替えてください)
  - 1日1回の実行なら十分すぎるほど余裕がある

環境変数 GEMINI_API_KEY が必要 (https://ai.google.dev で無料取得)。

同じモデルが 503 (high demand) を返し続けることがある。その場合は待って同じモデルを
叩き直すだけでは復旧しないため、数回失敗したら別モデルへ切り替える。
切り替え先は環境変数 GEMINI_FALLBACK_MODELS（カンマ区切り）で上書きできる。
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

DEFAULT_MODEL = "gemini-3.6-flash"
# 3.6 が混雑しているときでも、世代の違う Flash は通ることが多い。
DEFAULT_FALLBACK_MODELS = ("gemini-3.5-flash", "gemini-2.5-flash")
MAX_CHARS_PER_ARTICLE = 1500  # 1記事あたり要約対象にするテキストの上限（トークン節約）

# 同一モデルへのリトライは短く留め、続いても次のモデルへ移る。
# 2026-09-23 の手動実行は gemini-3.6-flash への 5 回 (約5分) がすべて 503 だった。
ATTEMPTS_PER_MODEL = 2
RETRY_BACKOFF_SECONDS = (20,)

SYSTEM_PROMPT = """\
あなたは、エンジニア向けの日刊ニュースPodcastの構成作家です。
渡された記事リストをもとに、ホスト「つむぎ」とコホスト「ずんだもん」の2人が掛け合う
読み上げ台本を日本語の口語体で作成してください。

# 話者の役割
- つむぎ（ホスト）: 挨拶、ニュースの紹介、要点の説明を担当する。
- ずんだもん（コホスト）: 一言ツッコミ、短い補足、感想で番組感を出す。長話はしない。

# 出力形式（厳守）
- 各発言は必ず行頭に話者名とコロンをつける。例: `つむぎ: ……` / `ずんだもん: ……`
- 1行に1発言。話者タグ以外の見出し記号(#, *, -)や絵文字、Markdown装飾は使わない。
- 出力はそのままTTSにかけるプレーンテキストのみ（前置き・後書きの説明文は不要）。

# ルール
- 記事の文章をそのまま引用・転載しない。必ず自分の言葉で要約・言い換えること。
- 記事のカテゴリ(ラベル)ごとに話題を進める。記事が無いカテゴリは丸ごと省略する。
- 各ニュースはつむぎが2〜3文で要点を話し、ずんだもんが1文程度で反応する。
- 専門用語にはつむぎかずんだもんが一言だけ補足を添える。
- 同じ話題が複数記事にまたがる場合はまとめて1つの話題として扱う。
- 冒頭はつむぎの短い挨拶（日付・今日のトピック数など）、末尾は二人で短い締めの一言を入れる。
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


def resolve_models(models: list[str] | None = None) -> list[str]:
    """使うモデルを優先順に返す。先頭が失敗し続けたとき、後ろへ切り替える。"""
    if models is not None:
        return _dedupe(models)

    primary = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    raw = os.environ.get("GEMINI_FALLBACK_MODELS")
    if raw is None:
        fallbacks = list(DEFAULT_FALLBACK_MODELS)
    else:
        fallbacks = [part.strip() for part in raw.split(",") if part.strip()]
    return _dedupe([primary, *fallbacks])


def _dedupe(models: list[str]) -> list[str]:
    seen: list[str] = []
    for model in models:
        name = model.strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def summarize(
    articles: list[dict[str, Any]],
    target_date: str,
    api_key: str,
    *,
    client: Any = None,
    models: list[str] | None = None,
    sleep: Any = time.sleep,
) -> str:
    if not articles:
        return f"{target_date}分のニュースは収集できませんでした。対象フィードの設定を確認してください。"

    if client is None:
        client = genai.Client(api_key=api_key)
    user_prompt = _build_user_prompt(articles, target_date)
    model_list = resolve_models(models)
    if not model_list:
        raise RuntimeError("使用する Gemini モデルが指定されていません")

    last_error: Exception | None = None
    for index, model in enumerate(model_list):
        for attempt in range(1, ATTEMPTS_PER_MODEL + 1):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=user_prompt,
                    config={
                        "system_instruction": SYSTEM_PROMPT,
                        "temperature": 0.6,
                    },
                )
                script = (response.text or "").strip()
                if not script:
                    raise RuntimeError("Gemini APIから空の応答が返りました")
                if model != model_list[0]:
                    log.warning("モデル %s が使えなかったため %s で台本を生成しました", model_list[0], model)
                return script
            except genai_errors.ServerError as e:
                last_error = e
                if attempt < ATTEMPTS_PER_MODEL:
                    wait_sec = RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
                    log.warning(
                        "Gemini APIが一時的に利用できません(model=%s, %s回目/%s回): %s -- %d秒待ってリトライします",
                        model, attempt, ATTEMPTS_PER_MODEL, e, wait_sec,
                    )
                    sleep(wait_sec)
                    continue
                _log_model_switch(model_list, index, e)
                break
            except genai_errors.ClientError as e:
                # モデル名が無効なときだけ次へ進む。プロンプト不正などはリトライしない。
                if getattr(e, "code", None) == 404 and index < len(model_list) - 1:
                    last_error = e
                    log.warning("モデル %s が見つからないため次のモデルへ切り替えます: %s", model, e)
                    break
                raise

    raise RuntimeError(
        f"Gemini APIへの要約リクエストが失敗しました（試行モデル: {', '.join(model_list)}）: {last_error}"
    )


def _log_model_switch(model_list: list[str], index: int, error: Exception) -> None:
    if index >= len(model_list) - 1:
        return
    log.warning(
        "モデル %s が %s 回とも失敗したため %s に切り替えます: %s",
        model_list[index], ATTEMPTS_PER_MODEL, model_list[index + 1], error,
    )


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
