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


def _resolve_data_source_id(notion: "NotionClient", database_id: str) -> str:
    """新API用: DB の最初の data_source の ID を返す."""
    db = notion.databases.retrieve(database_id=database_id)
    sources = db.get("data_sources") or []
    if not sources:
        raise RuntimeError(
            f"DB {database_id} に data_sources が見つかりません。Notion API のバージョンを確認してください。"
        )
    return sources[0]["id"]


def _query_data_source(notion: "NotionClient", data_source_id: str, body: dict) -> dict:
    """notion-client が data_sources.query を持たない場合に備えた汎用ラッパー."""
    if hasattr(notion, "data_sources"):
        return notion.data_sources.query(data_source_id=data_source_id, **body)
    # SDK が未対応なら REST を直叩き
    return notion.request(
        path=f"data_sources/{data_source_id}/query",
        method="POST",
        body=body,
    )


# ---------------------------------------------------------------------------
# Google Tasks（マイタスク）連携ヘルパー
# ---------------------------------------------------------------------------

# review.py との共有用。マイタスクの notes 先頭にこのプレフィックス付きで
# Notion の page id を書き込んでおき、後で確実にマッピングできるようにする。
NOTION_ID_PREFIX = "notion_id: "
GOOGLE_TASKLIST_ID = os.getenv("GOOGLE_TASKLIST_ID", "@default")


def encode_notion_id(notion_id: str, extra: str = "") -> str:
    """Google Tasks の notes 用文字列を生成する."""
    lines = [f"{NOTION_ID_PREFIX}{notion_id}"]
    if extra:
        lines.append("")
        lines.append(extra)
    return "\n".join(lines)


def extract_notion_id(notes: str | None) -> str | None:
    """notes から notion_id を取り出す。無ければ None."""
    if not notes:
        return None
    for line in notes.splitlines():
        line = line.strip()
        if line.startswith(NOTION_ID_PREFIX):
            return line[len(NOTION_ID_PREFIX):].strip()
    return None


def get_notion_todos():
    """NotionのTODOリストを取得"""
    notion = NotionClient(auth=NOTION_API_KEY)
    data_source_id = _resolve_data_source_id(notion, NOTION_DATABASE_ID)
    response = _query_data_source(notion, data_source_id, {
        "filter": {
            "property": "ステータス",
            "select": {
                "does_not_equal": "完了"
            }
        }
    })
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
            "due": due_date,
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
        f"- [id: {t['id']}] {t['name']}（ステータス: {t['status']}"
        f"{'、期限: ' + t['due'] if t['due'] else ''}）"
        for t in todos
    ])
    busy_text = "\n".join([f"- {s[0]} 〜 {s[1]}" for s in busy_slots]) or "なし"

    prompt = f"""今日（{date}）のTODOリストをスケジューリングしてください。

## TODOリスト
{todos_text}

## 今日の既存予定（ブロック済み時間）
{busy_text}

## スケジューリングのルール
1. 期限の近いタスクや重要度が高そうなタスクから順に空き時間へ割り当てる
2. 作業時間は9:00〜22:00（日本時間）、集中作業は午前中に優先配置する
3. 各タスクの所要時間を現実的に見積もり、既存予定と重複しないようにする
4. **今日の空き時間に収まらないタスクはスケジュールに含めない**（無理に詰め込まない）
5. **ひとつのタスクが曖昧・抽象的、または見積もりが3時間を超える場合は、具体的なサブタスクに分割してからスケジュールに入れる**
   - 例: 「〇〇の設計をする」→「要件整理（60分）」「構成図の作成（90分）」など

## 出力形式
以下のJSON配列のみで返してください。説明文・コードフェンスは不要です。
- `notion_id` には上記 TODO リストの `[id: xxxx]` の xxxx をそのまま入れる
- タスクを複数のサブタスクに分割した場合も、すべて同じ親タスクの notion_id を使う

[
  {{
    "task": "タスク名（分割した場合はサブタスク名）",
    "notion_id": "元の Notion タスク id",
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


def _list_existing_notion_ids(tasks_service, tasklist_id: str = GOOGLE_TASKLIST_ID) -> set[str]:
    """未完了のマイタスクから notion_id を抽出してセットで返す（重複登録防止用）."""
    existing: set[str] = set()
    page_token = None
    while True:
        kwargs = {
            "tasklist": tasklist_id,
            "showCompleted": False,
            "showHidden": False,
            "maxResults": 100,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        result = tasks_service.tasks().list(**kwargs).execute()
        for item in result.get("items", []):
            nid = extract_notion_id(item.get("notes", ""))
            if nid:
                existing.add(nid)
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return existing


def create_google_tasks(tasks_service, todos, schedule, date, tasklist_id: str = GOOGLE_TASKLIST_ID):
    """全 Notion 未完了タスクを Google Tasks（マイタスク）に登録する.

    - 既にマイタスクに同じ notion_id があれば作り直さない（重複防止）
    - スケジュール対象のタスクは notes に時間割り情報を併記する
    - 期限: Notion の `期限` プロパティ or 今日（YYYY-MM-DD）
    """
    schedule_by_nid: dict[str, list[dict]] = {}
    unknown_items: list[dict] = []
    for item in schedule:
        nid = item.get("notion_id")
        if nid:
            schedule_by_nid.setdefault(nid, []).append(item)
        else:
            unknown_items.append(item)
    if unknown_items:
        # notion_id を返してくれなかったスケジュール項目はマイタスク化を諦める
        # （カレンダーには既に入っている）
        print(f"⚠️  notion_id 不明のスケジュール {len(unknown_items)} 件はマイタスク化スキップ")

    existing_nids = _list_existing_notion_ids(tasks_service, tasklist_id)

    created = 0
    skipped = 0
    for todo in todos:
        if todo["id"] in existing_nids:
            skipped += 1
            print(f"⏭️  既にマイタスクあり: {todo['name']}")
            continue

        sched_items = schedule_by_nid.get(todo["id"], [])
        extra_lines: list[str] = []
        if sched_items:
            extra_lines.append("今日のスケジュール:")
            for s in sched_items:
                extra_lines.append(
                    f"- {s.get('start', '?')}〜{s.get('end', '?')} {s.get('task', '')}"
                    f"（{s.get('estimated_minutes', '?')}分）"
                )
        notes = encode_notion_id(todo["id"], "\n".join(extra_lines))

        # マイタスクの期限。日付のみ。RFC3339（UTC, 時刻部分は無視される）。
        due_date = todo.get("due") or date
        # Notion の date は "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM:SS..." を想定
        due_day = due_date[:10] if due_date else date
        body = {
            "title": todo["name"],
            "notes": notes,
            "due": f"{due_day}T00:00:00.000Z",
        }
        tasks_service.tasks().insert(tasklist=tasklist_id, body=body).execute()
        created += 1
        print(f"📝 マイタスク作成: {todo['name']}（期限 {due_day}）")

    if skipped:
        print(f"  既存マイタスクのため作成スキップ: {skipped} 件")
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

    # 5. マイタスク（Google Tasks）に登録（完了チェック用）
    print("📝 Google Tasks（マイタスク）に登録中...")
    tasks_service = build("tasks", "v1", credentials=creds)
    create_google_tasks(tasks_service, todos, schedule, today)

    print("\n✨ 完了！")


if __name__ == "__main__":
    main()
