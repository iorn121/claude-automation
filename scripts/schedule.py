import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
import anthropic
from notion_client import Client as NotionClient
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")


def get_notion_todos():
    """NotionのTODOリストを取得"""
    notion = NotionClient(auth=NOTION_API_KEY)
    response = notion.databases.query(
        database_id=NOTION_DATABASE_ID,
        filter={
            "property": "ステータス",
            "status": {
                "does_not_equal": "完了"
            }
        }
    )
    todos = []
    for page in response["results"]:
        props = page["properties"]
        title = props.get("タスク名", {}).get("title", [])
        task_name = title[0]["text"]["content"] if title else "無題"
        status = props.get("ステータス", {}).get("status", {}).get("name", "")
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


def schedule_with_claude(todos, busy_slots, date):
    """ClaudeにTODOの見積もりとスケジューリングを依頼"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

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
以下のJSON形式のみで返してください。説明文は不要です。
[
  {{
    "task": "タスク名",
    "start": "HH:MM",
    "end": "HH:MM",
    "estimated_minutes": 数値
  }}
]"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = message.content[0].text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


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
    creds = Credentials.from_authorized_user_file("token.json")
    service = build("calendar", "v3", credentials=creds)
    busy_slots = get_calendar_free_slots(service, today)

    # 3. Claudeでスケジューリング
    print("🧠 Claudeがスケジュールを作成中...")
    schedule = schedule_with_claude(todos, busy_slots, today)

    # 4. カレンダーにイベント作成
    print("📌 カレンダーにイベントを追加中...")
    create_calendar_events(service, schedule, today)

    print("\n✨ 完了！")


if __name__ == "__main__":
    main()
