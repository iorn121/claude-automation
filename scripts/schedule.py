import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from notion_client import Client as NotionClient

load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")

ROOT = Path(__file__).resolve().parent.parent
TOKEN_PATH = ROOT / "token.json"

# Claude Code CLI のパス。環境変数で上書き可能。
CLAUDE_BIN = os.getenv("CLAUDE_BIN", "claude")


def get_notion_todos():
    """NotionのTODOリストを取得"""
    notion = NotionClient(auth=NOTION_API_KEY)
    response = notion.databases.query(
        database_id=NOTION_DATABASE_ID,
        filter={
            "property": "ステータス",
            "select": {
                "does_not_equal": "完了"
            }
        }
    )
    todos = []
    for page in response["results"]:
        props = page["properties"]
        title = props.get("タスク名", {}).get("title", [])
        task_name = title[0]["text"]["content"] if title else "無題"
        status = (props.get("ステータス", {}).get("select") or {}).get("name", "")
        due = props.get("期限", {}).get("date", {})
        due_date = due.get("start", "") if due else ""
        todos.append({
            "id": page["id"],
            "name": task_name,
            "status": status,
            "due": due_date
        })
    return todos


def get_calendar_free_slots(service, date: str):
    """指定日の空き時間を取得"""
    start = f"{date}T09:00:00+09:00"
    end = f"{date}T21:00:00+09:00"
    events_result = service.events().list(
        calendarId=GOOGLE_CALENDAR_ID,
        timeMin=start,
        timeMax=end,
        singleEvents=True,
        orderBy="startTime"
    ).execute()
    events = events_result.get("items", [])
    busy = [(e["start"].get("dateTime", ""), e["end"].get("dateTime", "")) for e in events]
    return busy


def _extract_json_array(text: str):
    """Claude の出力から最初の JSON 配列を抽出"""
    # コードフェンス除去
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = text.replace("```", "")
    # 最初の '[' から対応する ']' までを取り出す
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"JSON 配列が見つかりません: {text[:200]!r}")
    return json.loads(text[start:end + 1])


def schedule_with_claude(todos, busy_slots, date):
    """ローカル Claude Code (CLI) に TODO の見積もりとスケジューリングを依頼"""
    todos_text = "\n".join([
        f"- {t['name']}（ステータス: {t['status']}{'、期限: ' + t['due'] if t['due'] else ''}）"
        for t in todos
    ])
    busy_text = "\n".join([f"- {s[0]} 〜 {s[1]}" for s in busy_slots]) or "なし"

    prompt = f"""今日（{date}）のTODOリストをスケジューリングしてください。

## TODOリスト
{todos_text}

## 今日の既存予定（ブロック済み時間）
{busy_text}

## 条件
- 作業時間は9:00〜21:00（日本時間）
- 集中作業は午前中に配置
- 各タスクの所要時間を現実的に見積もる
- 既存予定と重ならないようにする

## 出力形式
以下のJSON配列のみで返してください。説明文・コードフェンスは不要です。
[
  {{
    "task": "タスク名",
    "start": "HH:MM",
    "end": "HH:MM",
    "estimated_minutes": 数値
  }}
]"""

    # `claude -p` は単発の non-interactive 実行（プロンプトを引数で渡す）
    try:
        result = subprocess.run(
            [CLAUDE_BIN, "-p", prompt],
            capture_output=True,
            text=True,
            timeout=180,
            check=True,
        )
    except FileNotFoundError as e:
        raise RuntimeError(
            f"`{CLAUDE_BIN}` コマンドが見つかりません。Claude Code がインストールされ、PATH に通っているか確認してください。"
        ) from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"claude CLI がエラー終了しました (exit={e.returncode})\nstderr: {e.stderr.strip()[:400]}"
        ) from e

    return _extract_json_array(result.stdout)


def create_calendar_events(service, schedule, date):
    """Googleカレンダーにイベントを一括作成"""
    created = []
    for item in schedule:
        start_dt = f"{date}T{item['start']}:00+09:00"
        end_dt = f"{date}T{item['end']}:00+09:00"
        event = {
            "summary": f"🤖 {item['task']}",
            "description": f"Claude自動スケジュール（見積もり: {item['estimated_minutes']}分）",
            "start": {"dateTime": start_dt, "timeZone": "Asia/Tokyo"},
            "end": {"dateTime": end_dt, "timeZone": "Asia/Tokyo"},
            "colorId": "7"  # Peacock（青緑）
        }
        result = service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=event).execute()
        created.append(result.get("htmlLink"))
        print(f"✅ 作成: {item['task']} ({item['start']}〜{item['end']})")
    return created


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"\n🤖 Claude自動スケジューリング開始: {today}\n")

    # 1. NotionからTODO取得
    print("📋 Notionからタスク取得中...")
    todos = get_notion_todos()
    print(f"  {len(todos)}件のタスクを取得")

    if not todos:
        print("タスクがありません。終了します。")
        return

    # 2. Googleカレンダーの空き時間取得
    print("📅 Googleカレンダーの予定を確認中...")
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
    service = build("calendar", "v3", credentials=creds)
    busy_slots = get_calendar_free_slots(service, today)

    # 3. Claudeでスケジューリング（ローカル Claude Code 経由）
    print("🧠 Claude Code がスケジュールを作成中...")
    schedule = schedule_with_claude(todos, busy_slots, today)

    # 4. カレンダーにイベント作成
    print("📌 カレンダーにイベントを追加中...")
    create_calendar_events(service, schedule, today)

    print("\n✨ 完了！")


if __name__ == "__main__":
    main()
