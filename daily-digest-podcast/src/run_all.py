"""
毎日の実行エントリポイント: 収集 -> 要約 -> 音声合成 -> 公開 を一気に行う。

ローカルでの手動テスト例（.envファイルにキーを貼り付けておけばexportは不要）:
    cp ../.env.example ../.env   # 初回だけ。.envを開いてキーを貼り付けて保存
    docker run -d -p 50021:50021 voicevox/voicevox_engine:cpu-latest
    python src/run_all.py
"""
from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from fetch_feeds import fetch_all
from publish import publish_episode
from summarize import summarize
from synthesize import synthesize_script

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("run_all")

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "feeds.yaml"
LABELS_PATH = ROOT / "config" / "labels.yaml"
LABEL_MAPPING_PATH = ROOT / "config" / "label_mapping.yaml"
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"

# ROOT/.env があれば読み込む（GitHub Actions実行時は.envが無いのでSecretsの環境変数がそのまま使われる）
# override=True: シェルに古い値がexportされたまま残っていても、.envの値を優先させる
load_dotenv(ROOT / ".env", override=True)


def main() -> None:
    target_date = os.environ.get("TARGET_DATE", date.today().isoformat())
    log.info("=== %s 分のダイジェスト生成を開始 ===", target_date)

    log.info("[1/4] RSS収集")
    articles = fetch_all(CONFIG_PATH, LABELS_PATH, LABEL_MAPPING_PATH)
    DATA_DIR.mkdir(exist_ok=True)
    import json

    with open(DATA_DIR / "articles.json", "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)

    log.info("[2/4] 要約・台本生成")
    api_key = os.environ["GEMINI_API_KEY"]  # 未設定なら明示的にKeyErrorで落とす
    script = summarize(articles, target_date, api_key)
    script_path = DATA_DIR / "script.txt"
    script_path.write_text(script, encoding="utf-8")

    log.info("[3/4] 音声合成")
    episode_path = DATA_DIR / "episode.mp3"
    synthesize_script(script, episode_path)

    log.info("[4/4] 公開用ファイル更新")
    publish_episode(episode_path, DOCS_DIR, target_date)

    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
