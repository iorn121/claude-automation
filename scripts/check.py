"""セットアップ確認スクリプト（read-only）.

.env と各種認証情報が正しく揃っているかを、副作用なしで検証する。
- カレンダーに書き込みはしない
- Notion を更新しない
- Claude Code CLI は存在確認のみ（API 呼び出しなし）

使い方:
    python scripts/check.py

すべて ✅ になったら `python scripts/schedule.py` を実行できる状態。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
TOKEN_PATH = ROOT / "token.json"

load_dotenv()

CLAUDE_BIN = os.getenv("CLAUDE_BIN", "claude")


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def warn(msg: str) -> None:
    print(f"  ⚠️  {msg}")


def fail(msg: str) -> None:
    print(f"  ❌ {msg}")


def check_env() -> dict[str, str | None]:
    section("環境変数")
    keys = [
        "NOTION_API_KEY",
        "NOTION_DATABASE_ID",
        "GOOGLE_CALENDAR_ID",
    ]
    values: dict[str, str | None] = {}
    for k in keys:
        v = os.getenv(k)
        values[k] = v
        if not v:
            fail(f"{k} が未設定")
        else:
            preview = v if len(v) <= 12 else f"{v[:6]}...{v[-4:]}"
            ok(f"{k} = {preview}")
    return values


def check_claude_cli() -> bool:
    section("Claude Code CLI")
    path = shutil.which(CLAUDE_BIN)
    if not path:
        fail(f"`{CLAUDE_BIN}` コマンドが PATH に見つかりません。Claude Code をインストールしてください。")
        return False
    ok(f"発見: {path}")
    try:
        result = subprocess.run(
            [CLAUDE_BIN, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        ok(f"バージョン: {result.stdout.strip() or result.stderr.strip()}")
        return True
    except Exception as e:
        fail(f"`{CLAUDE_BIN} --version` 失敗: {e}")
        return False


def check_notion(api_key: str | None, db_id: str | None) -> bool:
    section("Notion API")
    if not api_key or not db_id:
        fail("NOTION_API_KEY または NOTION_DATABASE_ID が未設定なのでスキップ")
        return False
    try:
        from notion_client import Client as NotionClient
    except ImportError:
        fail("notion-client が入っていません")
        return False
    try:
        notion = NotionClient(auth=api_key)
        db = notion.databases.retrieve(database_id=db_id)
        title = "".join([t.get("plain_text", "") for t in db.get("title", [])]) or "(無題)"
        ok(f"DB取得OK: {title}")

        # 新API: properties は data_source 側にある
        sources = db.get("data_sources") or []
        if not sources:
            fail("data_sources が見つかりません（API バージョン要確認）")
            return False
        data_source_id = sources[0]["id"]
        ok(f"Data Source ID: {data_source_id}")

        if hasattr(notion, "data_sources"):
            ds = notion.data_sources.retrieve(data_source_id=data_source_id)
        else:
            ds = notion.request(path=f"data_sources/{data_source_id}", method="GET")

        props = ds.get("properties", {})
        expected = {
            "タスク名": "title",
            "ステータス": "select",
            "期限": "date",
        }
        missing = []
        for name, ptype in expected.items():
            actual = props.get(name)
            if not actual:
                missing.append(f"{name} ({ptype})")
            elif actual.get("type") != ptype:
                warn(f"プロパティ `{name}` は存在しますが型が {actual.get('type')} です（期待: {ptype}）")
            else:
                ok(f"プロパティ `{name}` ({ptype}) あり")
        if missing:
            fail(f"不足プロパティ: {', '.join(missing)}")
            return False

        if hasattr(notion, "data_sources"):
            res = notion.data_sources.query(data_source_id=data_source_id, page_size=1)
        else:
            res = notion.request(
                path=f"data_sources/{data_source_id}/query",
                method="POST",
                body={"page_size": 1},
            )
        ok(f"クエリ成功 ({len(res.get('results', []))} 件サンプル取得)")
        return True
    except Exception as e:
        fail(f"接続失敗: {e}")
        return False


REQUIRED_GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
)


def check_google(calendar_id: str | None) -> bool:
    section("Google Calendar API")
    if not TOKEN_PATH.exists():
        fail(f"{TOKEN_PATH} がありません。`python scripts/auth_google.py` を先に実行してください")
        return False
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        fail("google-api-python-client が入っていません")
        return False
    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
        # スコープ確認（古い token.json だと tasks が無い）
        granted = set(creds.scopes or [])
        missing = [s for s in REQUIRED_GOOGLE_SCOPES if s not in granted]
        if missing:
            fail(
                "token.json のスコープが不足しています: "
                + ", ".join(missing)
                + "\n     `python scripts/auth_google.py` を再実行して token.json を再生成してください。"
            )
            return False
        service = build("calendar", "v3", credentials=creds)
        cal = service.calendarList().get(calendarId=calendar_id or "primary").execute()
        ok(f"カレンダー取得OK: {cal.get('summary')} ({cal.get('id')})")
        return True
    except Exception as e:
        fail(f"接続失敗: {e}")
        return False


def check_google_tasks() -> bool:
    section("Google Tasks API（マイタスク）")
    if not TOKEN_PATH.exists():
        fail(f"{TOKEN_PATH} がありません")
        return False
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        fail("google-api-python-client が入っていません")
        return False
    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
        if "https://www.googleapis.com/auth/tasks" not in (creds.scopes or []):
            fail("token.json に tasks スコープがありません。`python scripts/auth_google.py` を再実行してください")
            return False
        service = build("tasks", "v1", credentials=creds)
        result = service.tasklists().list(maxResults=5).execute()
        items = result.get("items", [])
        if not items:
            warn("タスクリストが1件も見つかりません（マイタスクをモバイル/ウェブで一度開いて作成してください）")
            return False
        default = next((i for i in items if i.get("id") == "@default"), items[0])
        ok(f"タスクリスト取得OK: {default.get('title')} ({default.get('id')})")
        return True
    except Exception as e:
        fail(f"接続失敗: {e}")
        return False


def main() -> int:
    print("🔍 claude-automation セットアップ確認\n")
    env = check_env()
    results = {
        "Claude Code CLI": check_claude_cli(),
        "Notion": check_notion(env["NOTION_API_KEY"], env["NOTION_DATABASE_ID"]),
        "Google Calendar": check_google(env["GOOGLE_CALENDAR_ID"]),
        "Google Tasks": check_google_tasks(),
    }

    section("結果")
    all_ok = all(results.values())
    for name, success in results.items():
        mark = "✅" if success else "❌"
        print(f"  {mark} {name}")

    if all_ok:
        print("\n✨ すべてOK!")
        print("   朝: `python scripts/schedule.py`")
        print("   夜: `python scripts/review.py --dry-run` → `python scripts/review.py`")
        return 0
    else:
        print("\n上のエラーを修正してから再実行してください。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
