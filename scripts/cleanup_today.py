"""「やり直し」用クリーンアップスクリプト.

schedule.py が作成した以下のリソースを一括削除する:

1. 今日（JST）の Google カレンダー予定で summary が `🤖 ` で始まるもの
2. マイタスクのうち notes に `notion_id:` が含まれるもの（チェック済み含む）

手動で作成・編集したものは触らない（プレフィックス / notion_id で判別）。
削除後は schedule.py を `--force` で再実行することでまっさらな状態から作り直せる。

使い方:
    python scripts/cleanup_today.py             # 確認プロンプトあり
    python scripts/cleanup_today.py --yes       # 確認なし即実行
    python scripts/cleanup_today.py --dry-run   # 削除対象の表示のみ
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from schedule import (
    GOOGLE_CALENDAR_ID,
    GOOGLE_TASKLIST_ID,
    TOKEN_PATH,
    extract_notion_id,
)

load_dotenv()

AUTO_EVENT_PREFIX = "🤖 "


def list_today_auto_events(service, date: str) -> list[dict]:
    """今日の🤖イベント一覧."""
    start = f"{date}T00:00:00+09:00"
    end = f"{date}T23:59:59+09:00"
    result = (
        service.events()
        .list(
            calendarId=GOOGLE_CALENDAR_ID,
            timeMin=start,
            timeMax=end,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    return [
        e for e in result.get("items", [])
        if (e.get("summary") or "").startswith(AUTO_EVENT_PREFIX)
    ]


def list_managed_my_tasks(tasks_service, tasklist_id: str = GOOGLE_TASKLIST_ID) -> list[dict]:
    """notion_id 付きマイタスク（チェック済み含む全部）."""
    items: list[dict] = []
    page_token = None
    while True:
        kwargs = {
            "tasklist": tasklist_id,
            "showCompleted": True,
            "showHidden": True,
            "maxResults": 100,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        result = tasks_service.tasks().list(**kwargs).execute()
        for t in result.get("items", []):
            if extract_notion_id(t.get("notes", "")):
                items.append(t)
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description="今日の🤖イベントと管理下のマイタスクを全削除")
    parser.add_argument("--yes", action="store_true", help="確認プロンプトをスキップ")
    parser.add_argument("--dry-run", action="store_true", help="削除せず対象を表示のみ")
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    print(f"\n🧹 クリーンアップ — 今日: {today}\n")

    if not TOKEN_PATH.exists():
        print(f"❌ {TOKEN_PATH} がありません。先に auth_google.py を実行してください。")
        return 1

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
    calendar_service = build("calendar", "v3", credentials=creds)
    tasks_service = build("tasks", "v1", credentials=creds)

    events = list_today_auto_events(calendar_service, today)
    my_tasks = list_managed_my_tasks(tasks_service)

    print(f"=== 削除対象 ===")
    print(f"📅 今日のカレンダー予定（🤖）: {len(events)} 件")
    for e in events:
        start = (e.get("start") or {}).get("dateTime", "?")[11:16]
        print(f"  - {start}  {e.get('summary', '')}")
    print()
    print(f"📝 マイタスク（notion_id 付き）: {len(my_tasks)} 件")
    for t in my_tasks:
        status = "✅" if t.get("status") == "completed" else "⬜"
        print(f"  - {status} {t.get('title', '')}")
    print()

    if not events and not my_tasks:
        print("削除対象なし。終了します。")
        return 0

    if args.dry_run:
        print("[dry-run] 何も削除しませんでした。実行するには --yes か対話確認で。")
        return 0

    if not args.yes:
        try:
            ans = input("本当に削除しますか？ [y/N]: ").strip().lower()
        except EOFError:
            ans = ""
        if ans not in ("y", "yes"):
            print("中止しました。")
            return 0

    # カレンダー削除
    deleted_events = 0
    for e in events:
        try:
            calendar_service.events().delete(
                calendarId=GOOGLE_CALENDAR_ID, eventId=e["id"]
            ).execute()
            deleted_events += 1
        except Exception as ex:  # noqa: BLE001
            print(f"⚠️  カレンダー削除失敗 {e.get('summary')}: {ex}")
    print(f"✅ カレンダー予定 {deleted_events} 件削除")

    # マイタスク削除
    deleted_tasks = 0
    for t in my_tasks:
        try:
            tasks_service.tasks().delete(
                tasklist=GOOGLE_TASKLIST_ID, task=t["id"]
            ).execute()
            deleted_tasks += 1
        except Exception as ex:  # noqa: BLE001
            print(f"⚠️  マイタスク削除失敗 {t.get('title')}: {ex}")
    print(f"✅ マイタスク {deleted_tasks} 件削除")

    print(
        f"\n✨ クリーンアップ完了。次にやり直すなら:\n"
        f"  .venv/bin/python scripts/schedule.py --force"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
