"""macOS 通知センターへの通知ヘルパー.

launchd 経由でバックグラウンド実行されたスクリプトの結果を
通知センターに出すことで、実施可否がすぐ分かるようにする。

osascript を利用するため macOS でのみ動作する。
osascript が無い環境（Linux など）では何もしない（黙ってスキップ）。

使い方:
    from notify import notify
    notify("✅ 朝のスケジュール完了", "カレンダー 8件 / マイタスク 12件")
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS_PATH = ROOT / "launchd" / "last-run.json"


def _escape(s: str) -> str:
    """AppleScript 文字列向けのエスケープ."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def notify(title: str, message: str, subtitle: str = "", sound: str = "default") -> None:
    """macOS 通知センターに通知を出す.

    Args:
        title: 通知のタイトル
        message: 通知の本文
        subtitle: 任意のサブタイトル
        sound: 通知音の名前（"default" / "Glass" / "Basso" など / "" で無音）
    """
    if not shutil.which("osascript"):
        return  # macOS 以外では何もしない

    parts = [
        f'display notification "{_escape(message)}"',
        f'with title "{_escape(title)}"',
    ]
    if subtitle:
        parts.append(f'subtitle "{_escape(subtitle)}"')
    if sound:
        parts.append(f'sound name "{_escape(sound)}"')

    script = " ".join(parts)
    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except Exception:
        # 通知に失敗しても本処理を止めない
        pass


def write_status(job: str, status: str, summary: str, started_at: float, error: str = "") -> None:
    """last-run.json に最新の実行結果を書き込む（job ごとに更新）.

    Args:
        job: "schedule" または "review"
        status: "success" / "error" / "skipped"
        summary: 一行サマリ（通知本文と同じものを想定）
        started_at: time.time() で取得した開始時刻
        error: エラー時の例外内容（先頭400字）
    """
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if STATUS_PATH.exists():
        try:
            data = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    now = time.time()
    data[job] = {
        "status": status,
        "summary": summary,
        "started_at": datetime.fromtimestamp(started_at).isoformat(timespec="seconds"),
        "finished_at": datetime.fromtimestamp(now).isoformat(timespec="seconds"),
        "duration_seconds": round(now - started_at, 2),
        "error": error[:400] if error else "",
    }
    STATUS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    # 手動テスト用: `python scripts/notify.py` で通知が出るか確認
    notify(
        "🔔 claude-automation テスト通知",
        "通知センターに表示されれば設定OK",
        subtitle="notify.py のテスト",
        sound="Glass",
    )
