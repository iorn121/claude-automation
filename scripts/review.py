"""1日の終わりにマイタスクのチェック状態を見て Notion を更新する.

schedule.py が朝に作成した Google Tasks（マイタスク）のうち、
ユーザーがチェック（完了）したものに対応する Notion タスクを「完了」に更新する。

判定はユーザーの明示的なチェック操作を根拠にする（Claude による推測は行わない）。
マイタスクに存在しない / 未チェックのものは触らない。

使い方:
    python scripts/review.py             # 判定して Notion を更新
    python scripts/review.py --dry-run   # 更新せず結果のみ表示
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from notion_client import Client as NotionClient

# schedule.py と共通の設定・ヘルパー
from schedule import (
    GOOGLE_TASKLIST_ID,
    NOTION_API_KEY,
    TOKEN_PATH,
    extract_notion_id,
    get_notion_todos,
)
from notify import STATUS_PATH, notify, write_status

load_dotenv()


def _already_succeeded_today(today: str) -> dict | None:
    """last-run.json を見て、当日 review が success/skipped で完了済みかを返す."""
    if not STATUS_PATH.exists():
        return None
    try:
        data = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    entry = data.get("review")
    if not entry:
        return None
    if entry.get("status") not in ("success", "skipped"):
        return None
    if entry.get("finished_at", "")[:10] != today:
        return None
    return entry

ROOT = Path(__file__).resolve().parent.parent


def get_my_tasks(tasks_service, tasklist_id: str = GOOGLE_TASKLIST_ID) -> list[dict]:
    """マイタスクを全件取得（チェック済み・未チェック両方）.

    Returns:
        各要素は {task_id, notion_id, title, status, completed_at} の dict。
        notes に notion_id が含まれていないタスクはスキップする。
    """
    items: list[dict] = []
    page_token = None
    while True:
        kwargs = {
            "tasklist": tasklist_id,
            "showCompleted": True,
            "showHidden": True,  # 完了済みは隠されることがあるので両方有効化
            "maxResults": 100,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        result = tasks_service.tasks().list(**kwargs).execute()
        for t in result.get("items", []):
            nid = extract_notion_id(t.get("notes", ""))
            if not nid:
                continue
            items.append(
                {
                    "task_id": t["id"],
                    "notion_id": nid,
                    "title": t.get("title", ""),
                    "status": t.get("status", "needsAction"),
                    "completed_at": t.get("completed", ""),
                }
            )
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return items


def decide_completions(todos: list[dict], my_tasks: list[dict]) -> list[dict]:
    """マイタスクのチェック状態をもとに Notion 完了対象を決める.

    - マイタスクが `completed` で、対応する Notion タスクがまだ未完了なら complete
    - それ以外は decisions に含めない（=何もしない）
    """
    todo_by_id = {t["id"]: t for t in todos}
    decisions: list[dict] = []
    for mt in my_tasks:
        if mt["status"] != "completed":
            continue
        nid = mt["notion_id"]
        if nid not in todo_by_id:
            # Notion 側で既に完了になっている or 別 DB のタスク
            continue
        decisions.append(
            {
                "id": nid,
                "title": mt["title"],
                "completed_at": mt["completed_at"],
                "reason": f"マイタスク「{mt['title']}」がチェック済み",
            }
        )
    return decisions


def apply_completions(decisions: list[dict], todos: list[dict], dry_run: bool) -> int:
    """対象タスクを Notion 上で「完了」に更新する."""
    name_by_id = {t["id"]: t["name"] for t in todos}

    if not decisions:
        print("完了にするタスクはありません。")
        return 0

    if dry_run:
        print("\n[dry-run] 以下を「完了」に更新する予定:")
        for d in decisions:
            print(f"  - {name_by_id.get(d['id'], d['id'])}: {d['reason']}")
        return len(decisions)

    notion = NotionClient(auth=NOTION_API_KEY)
    for d in decisions:
        notion.pages.update(
            page_id=d["id"],
            properties={"ステータス": {"select": {"name": "完了"}}},
        )
        print(f"✅ 完了: {name_by_id.get(d['id'], d['id'])} — {d['reason']}")
    return len(decisions)


def main() -> int:
    parser = argparse.ArgumentParser(description="マイタスクのチェック状態から Notion を更新")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Notion を更新せず判定結果のみ表示",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="今日すでに完了していても強制的に再実行する",
    )
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    started_at = time.time()
    print(f"\n🌙 タスク完了レビュー開始: {today}\n")

    # 冪等性チェック（dry-run はスキップ判定しない）
    if not args.force and not args.dry_run:
        already = _already_succeeded_today(today)
        if already:
            msg = (
                f"本日 {already.get('finished_at', '?')} に "
                f"すでに完了済み: {already.get('summary', '')}"
            )
            print(f"⏭️  {msg}")
            print("再実行したい場合は --force を付けてください。")
            return 0

    try:
        print("📋 Notion から未完了タスク取得中...")
        todos = get_notion_todos()
        print(f"  {len(todos)} 件")

        print("📝 マイタスクの状態を取得中...")
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
        tasks_service = build("tasks", "v1", credentials=creds)
        my_tasks = get_my_tasks(tasks_service)
        checked = sum(1 for m in my_tasks if m["status"] == "completed")
        print(f"  マイタスク {len(my_tasks)} 件（うちチェック済み {checked} 件）")

        if not todos:
            print("未完了タスクがありません。終了します。")
            summary = "未完了タスクなし"
            if not args.dry_run:
                notify("🌙 夜のレビュー（スキップ）", summary, subtitle=today)
                write_status("review", "skipped", summary, started_at)
            return 0

        decisions = decide_completions(todos, my_tasks)

        # 未チェックの参考表示（マイタスクには登録されているが未チェックなもの）
        completed_nids = {d["id"] for d in decisions}
        pending_in_my_tasks = [
            m for m in my_tasks
            if m["status"] != "completed"
            and m["notion_id"] in {t["id"] for t in todos}
            and m["notion_id"] not in completed_nids
        ]
        if pending_in_my_tasks:
            print("\n📌 マイタスクに残っている（未チェック）:")
            for m in pending_in_my_tasks:
                print(f"  - {m['title']}")

        print("\n📝 Notion を更新中..." if not args.dry_run else "\n📝 [dry-run] 更新内容:")
        updated = apply_completions(decisions, todos, dry_run=args.dry_run)

        print(f"\n✨ 完了！ {updated} 件を「完了」に{'する予定' if args.dry_run else '更新'}しました。")

        # dry-run 時は通知・ステータス書き込みしない
        if not args.dry_run:
            summary = (
                f"チェック済み {checked} / 完了反映 {updated} / "
                f"未チェック {len(pending_in_my_tasks)}"
            )
            notify("✨ 夜のレビュー完了", summary, subtitle=today, sound="Glass")
            write_status("review", "success", summary, started_at)
        return 0

    except Exception as e:  # noqa: BLE001
        err_msg = f"{type(e).__name__}: {e}"
        traceback.print_exc()
        if not args.dry_run:
            notify(
                "❌ 夜のレビュー失敗",
                err_msg[:200],
                subtitle=today,
                sound="Basso",
            )
            write_status("review", "error", err_msg, started_at, error=traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
