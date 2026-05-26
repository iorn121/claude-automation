"""今日の自動実行状況を確認するスクリプト.

launchd で実行された schedule.py / review.py が、いつ・どんな結果で
終わったかを last-run.json から読み出して人間向けに表示する。

使い方:
    python scripts/status.py

最後の launchd ログも tail で見ると便利:
    tail -30 launchd/stdout.log
    tail -30 launchd/review-stdout.log
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS_PATH = ROOT / "launchd" / "last-run.json"

JOBS = [
    ("schedule", "📅 朝のスケジューリング", "07:00"),
    ("review", "🌙 夜のレビュー", "22:00"),
]

STATUS_MARK = {
    "success": "✅",
    "skipped": "⏭️ ",
    "error": "❌",
}


def main() -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"\n🔍 claude-automation 実行状況 — 今日: {today}\n")

    if not STATUS_PATH.exists():
        print(f"⚠️  {STATUS_PATH} がありません。")
        print("   まだ一度も実行されていないか、古いバージョンで動いている可能性があります。")
        print("   手動で試す: python scripts/schedule.py --force")
        return 1

    try:
        data = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ last-run.json の読み込みに失敗: {e}")
        return 1

    any_today = False
    for job_key, label, scheduled_at in JOBS:
        entry = data.get(job_key)
        print(f"--- {label}（毎日 {scheduled_at}） ---")
        if not entry:
            print("  （実行履歴なし）\n")
            continue

        status = entry.get("status", "?")
        mark = STATUS_MARK.get(status, "❓")
        finished_at = entry.get("finished_at", "?")
        is_today = finished_at[:10] == today
        if is_today:
            any_today = True
        day_label = "今日" if is_today else f"{finished_at[:10]}（古い）"
        duration = entry.get("duration_seconds", "?")

        print(f"  {mark} 状態: {status}")
        print(f"     最終実行: {finished_at}（{day_label}, {duration}s）")
        print(f"     サマリ:  {entry.get('summary', '')}")
        if status == "error":
            err = entry.get("error", "")
            first_line = err.splitlines()[0] if err else ""
            print(f"     エラー:  {first_line}")
        print()

    if not any_today:
        print("⚠️  今日の実行履歴が見つかりません。")
        print("   Mac が起動していなかった / launchd がロードされていない可能性があります。")
        print()
        print("確認手順:")
        print("  launchctl list | grep claude-automation")
        print("  手動実行: python scripts/schedule.py --force")

    return 0


if __name__ == "__main__":
    sys.exit(main())
