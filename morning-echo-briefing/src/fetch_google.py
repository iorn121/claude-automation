"""Google カレンダーと Google Tasks から、今日の朝に読む材料を取る。"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from content import CalendarEvent, TaskItem, calendar_event_from_api, classify_tasks

log = logging.getLogger("fetch_google")

# 既存の scripts/auth_google.py が発行するトークンと同じスコープ。
# 読み取りしかしないが、スコープを狭めると手元の token.json が使えなくなる。
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
]

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_credentials() -> Credentials:
    raw = os.environ.get("GOOGLE_TOKEN_JSON", "").strip()
    token_path = Path(os.environ.get("GOOGLE_TOKEN_PATH", str(REPO_ROOT / "token.json")))
    if raw:
        creds = Credentials.from_authorized_user_info(json.loads(raw), SCOPES)
    elif token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    else:
        raise RuntimeError(
            "Google の認証情報が見つかりません。"
            "ローカルならリポジトリ直下の token.json、"
            "GitHub Actions なら Secrets の GOOGLE_TOKEN_JSON を設定してください。"
        )

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            raise RuntimeError(
                "Google トークンの更新に失敗しました（invalid_grant のことが多いです）。"
                "OAuth 同意画面が「テスト」のままだとリフレッシュトークンは7日で切れます。"
                "同意画面を本番に切り替えるか、python scripts/auth_google.py で再認証してください。"
            ) from exc
    if not creds.valid:
        raise RuntimeError("Google トークンが無効です。python scripts/auth_google.py を実行してください。")
    return creds


def fetch_events(creds: Credentials, today_start: datetime, tz: ZoneInfo) -> list[CalendarEvent]:
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "primary") or "primary"
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    window_end = today_start + timedelta(days=1)
    events: list[dict] = []
    page_token = None
    while True:
        response = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=today_start.isoformat(),
                timeMax=window_end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                timeZone=str(tz),
                maxResults=50,
                pageToken=page_token,
            )
            .execute()
        )
        events.extend(response.get("items") or [])
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    parsed = [calendar_event_from_api(event, tz) for event in events]
    result = [event for event in parsed if event is not None]
    log.info("カレンダー %d 件（取得 %d 件、辞退・キャンセルを除く）", len(result), len(events))
    return result


def fetch_tasks(creds: Credentials, today: datetime) -> list[TaskItem]:
    tasklist_id = os.environ.get("GOOGLE_TASKLIST_ID", "@default") or "@default"
    service = build("tasks", "v1", credentials=creds, cache_discovery=False)
    raw: list[dict] = []
    page_token = None
    while len(raw) < 300:
        response = (
            service.tasks()
            .list(
                tasklist=tasklist_id,
                maxResults=100,
                showCompleted=False,
                showHidden=False,
                pageToken=page_token,
            )
            .execute()
        )
        raw.extend(response.get("items") or [])
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    result = classify_tasks(raw, today.date())
    log.info("タスク %d 件（未完了の取得 %d 件から、期限が近いものを選択）", len(result), len(raw))
    return result
