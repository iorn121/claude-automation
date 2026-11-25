"""朝ブリーフィングの純関数。

カレンダー・タスク・ニュースを読み上げ用の文に整え、Alexa Flash Briefing の
フィード（JSON / RSS）を組み立てる。ネットワークも外部ライブラリも使わない。
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html import unescape
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
WEEKDAYS = "月火水木金土日"
VOICE_CREDIT_LINE = "この音声は、VOICEVOXの春日部つむぎを使用しています。"
MAX_SCRIPT_CHARS = 1200
BUCKET_ORDER = {"overdue": 0, "today": 1, "tomorrow": 2, "undated": 3}

_TAG_RE = re.compile(r"<[^>]+>")
_URL_RE = re.compile(r"https?://\S+")
_WS_RE = re.compile(r"[ \t\u3000]+")
_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF]+")


@dataclass(frozen=True)
class CalendarEvent:
    title: str
    when: str
    all_day: bool
    location: str


@dataclass(frozen=True)
class TaskItem:
    title: str
    due: date | None
    bucket: str


@dataclass(frozen=True)
class NewsItem:
    source: str
    title: str
    summary: str
    published: datetime | None = None


def japanese_date(day: date) -> str:
    return f"{day.month}月{day.day}日{WEEKDAYS[day.weekday()]}曜日"


def validate_path_token(token: str) -> str:
    """公開 URL のパスに使うトークン。空や推測しやすい記号は拒否する。"""
    if not TOKEN_RE.fullmatch(token or ""):
        raise ValueError(
            "BRIEFING_PATH_TOKEN は 16〜128 文字の英数字・ハイフン・アンダースコアにしてください"
        )
    return token


def sanitize_spoken(text: str, limit: int = 80) -> str:
    """読み上げと Flash Briefing の本文に載せられるプレーンテキストへ整える。"""
    cleaned = unescape(_TAG_RE.sub(" ", text or ""))
    cleaned = _URL_RE.sub("", cleaned)
    cleaned = _EMOJI_RE.sub("", cleaned)
    cleaned = cleaned.replace("&", "と").replace("<", " ").replace(">", " ")
    cleaned = cleaned.replace("…", "。").replace("—", "、").replace("–", "、")
    cleaned = _WS_RE.sub(" ", cleaned).replace("\n", " ").strip()
    cleaned = cleaned.strip("・-‐ ")
    if len(cleaned) > limit:
        cleaned = cleaned[:limit].rstrip() + "。"
    return cleaned


def for_tts(script: str) -> str:
    """改行や Markdown の残りを除き、Alexa の TTS が読める一文の連続にする。"""
    text = script.replace("\r\n", "\n").replace("\n", "")
    text = sanitize_spoken(text, limit=MAX_SCRIPT_CHARS + 200)
    return text


def clean_model_script(text: str) -> str:
    """モデル出力から見出し記号やコードフェンスを外す。"""
    lines: list[str] = []
    for raw in text.replace("```", "").splitlines():
        line = raw.strip()
        if not line or line.lower() in {"text", "plaintext"}:
            continue
        line = line.lstrip("#").strip()
        line = re.sub(r"^[\-*・]+\s*", "", line)
        line = sanitize_spoken(line, limit=400)
        if line:
            lines.append(line if line.endswith(("。", "！", "？")) else line + "。")
    return "\n".join(lines)


def finalize_script(script: str) -> str:
    """長さを揃え、VOICEVOX のクレジット行を必ず末尾に付ける。"""
    body = clean_model_script(script)
    credit_lines = [line for line in body.split("\n") if "VOICEVOX" in line]
    spoken = [line for line in body.split("\n") if "VOICEVOX" not in line]
    joined = "".join(spoken)
    if len(joined) > MAX_SCRIPT_CHARS:
        cut = joined[:MAX_SCRIPT_CHARS]
        pivot = max(cut.rfind("。"), cut.rfind("！"), cut.rfind("？"))
        joined = cut[: pivot + 1] if pivot > MAX_SCRIPT_CHARS // 2 else cut.rstrip("、, ") + "。"
    lines = [joined] if joined else []
    lines.append(credit_lines[-1] if credit_lines else VOICE_CREDIT_LINE)
    return "\n".join(line for line in lines if line)


def truncate_for_speech(text: str, limit: int = 1000) -> str:
    """Voice Monkey の読み上げは長いと途中で切れるため、文の境界で短くする。"""
    flat = for_tts(text)
    if len(flat) <= limit:
        return flat
    cut = flat[:limit]
    pivot = max(cut.rfind("。"), cut.rfind("！"), cut.rfind("？"))
    if pivot > limit // 2:
        return cut[: pivot + 1]
    return cut.rstrip("、, ") + "。"


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _ensure_period(text: str) -> str:
    text = text.strip()
    if text.endswith(("。", "！", "？")):
        return text
    return text + "。"


def _spoken_name(text: str, limit: int, fallback: str) -> str:
    name = sanitize_spoken(text, limit=limit).rstrip("。．.！？!?、 ")
    return name or fallback


def _clock(moment: datetime) -> str:
    if moment.minute == 0:
        return f"{moment.hour}時"
    return f"{moment.hour}時{moment.minute}分"


def is_declined(event: dict) -> bool:
    for attendee in event.get("attendees") or []:
        if attendee.get("self") and attendee.get("responseStatus") == "declined":
            return True
    return False


def calendar_event_from_api(event: dict, tz: ZoneInfo) -> CalendarEvent | None:
    if event.get("status") == "cancelled" or is_declined(event):
        return None
    title = _spoken_name(event.get("summary") or "", 60, "無題の予定")
    location = _spoken_name(event.get("location") or "", 40, "")
    start = event.get("start") or {}
    end = event.get("end") or {}
    if "dateTime" not in start:
        if "date" not in start:
            return None
        return CalendarEvent(title=title, when="終日", all_day=True, location=location)

    start_dt = _parse_datetime(start["dateTime"]).astimezone(tz)
    if "dateTime" in end:
        end_dt = _parse_datetime(end["dateTime"]).astimezone(tz)
        when = f"{_clock(start_dt)}から{_clock(end_dt)}"
    else:
        when = _clock(start_dt)
    return CalendarEvent(title=title, when=when, all_day=False, location=location)


def task_due_date(due: str | None) -> date | None:
    """Google Tasks の due は日付だけが意味を持つ（UTC 0時として入っている）。"""
    if not due:
        return None
    return date.fromisoformat(due[:10])


def classify_tasks(raw_tasks: list[dict], today: date, limit: int = 8) -> list[TaskItem]:
    """期限切れ・今日・明日と、期限なしを少数だけ残す。"""
    dated: list[TaskItem] = []
    undated: list[TaskItem] = []
    for task in raw_tasks:
        if task.get("status") == "completed":
            continue
        title = _spoken_name(task.get("title") or "", 60, "無題のタスク")
        due = task_due_date(task.get("due"))
        if due is None:
            undated.append(TaskItem(title=title, due=None, bucket="undated"))
            continue
        if due < today:
            bucket = "overdue"
        elif due == today:
            bucket = "today"
        elif due == today + timedelta(days=1):
            bucket = "tomorrow"
        else:
            continue
        dated.append(TaskItem(title=title, due=due, bucket=bucket))
    dated.sort(key=lambda item: (BUCKET_ORDER[item.bucket], item.due or date.max))
    merged = dated + undated[:3]
    return merged[:limit]


def select_news(items: list[NewsItem], limit: int = 5, per_source: int = 2) -> list[NewsItem]:
    """新しい順の候補から、1サイトに偏らないよう交互に選ぶ。"""
    ordered = sorted(
        items,
        key=lambda item: item.published or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    by_source: dict[str, list[NewsItem]] = {}
    for item in ordered:
        bucket = by_source.setdefault(item.source, [])
        if len(bucket) < per_source:
            bucket.append(item)
    selected: list[NewsItem] = []
    while len(selected) < limit and any(by_source.values()):
        for source in list(by_source):
            if len(selected) >= limit:
                break
            bucket = by_source[source]
            if bucket:
                selected.append(bucket.pop(0))
    return selected


def _event_sentence(event: CalendarEvent) -> str:
    sentence = _ensure_period(f"{event.when}、{event.title}")
    if event.location:
        sentence += f"場所は{event.location}です。"
    return sentence


def _task_sentence(label: str, tasks: list[TaskItem]) -> str | None:
    if not tasks:
        return None
    names = "、".join(task.title for task in tasks)
    return _ensure_period(f"{label}。{names}")


def build_fallback_script(
    today: date,
    events: list[CalendarEvent],
    tasks: list[TaskItem],
    news: list[NewsItem],
) -> str:
    """API キーが無い、または要約に失敗したときにそのまま読める台本。"""
    lines = [f"おはようございます。{japanese_date(today)}の朝のブリーフィングです。"]
    if not events:
        lines.append("今日のカレンダーに予定はありません。")
    else:
        lines.append(f"今日の予定は{len(events)}件です。")
        lines.extend(_event_sentence(event) for event in events)

    if not tasks:
        lines.append("朝の時点で、期限が近い未完了タスクはありません。")
    else:
        for sentence in (
            _task_sentence("期限を過ぎているタスク", [t for t in tasks if t.bucket == "overdue"]),
            _task_sentence("今日が期限のタスク", [t for t in tasks if t.bucket == "today"]),
            _task_sentence("明日が期限のタスク", [t for t in tasks if t.bucket == "tomorrow"]),
            _task_sentence("期限の無いタスク", [t for t in tasks if t.bucket == "undated"]),
        ):
            if sentence:
                lines.append(sentence)

    headlines = [item for item in news if item.title][:5]
    if not headlines:
        lines.append("新しいニュースは拾えませんでした。")
    else:
        lines.append("ニュースです。")
        lines.extend(_ensure_period(f"{item.source}より、{item.title}") for item in headlines)

    lines.append("以上です。よい一日を。")
    return finalize_script("\n".join(lines))


def build_model_prompt(
    today: date,
    events: list[CalendarEvent],
    tasks: list[TaskItem],
    news: list[NewsItem],
) -> str:
    """要約モデルへ渡す材料。台本そのものではなく事実の列挙。"""
    lines = [
        f"日付: {japanese_date(today)}",
        "",
        "予定:",
    ]
    if events:
        lines.extend(f"- {event.when} {event.title}" + (f" 場所 {event.location}" if event.location else "") for event in events)
    else:
        lines.append("- なし")
    lines.append("")
    lines.append("タスク:")
    if tasks:
        labels = {
            "overdue": "期限切れ",
            "today": "今日が期限",
            "tomorrow": "明日が期限",
            "undated": "期限なし",
        }
        lines.extend(f"- {labels[task.bucket]} {task.title}" for task in tasks)
    else:
        lines.append("- なし")
    lines.append("")
    lines.append("ニュース:")
    if news:
        for item in news:
            summary = f"（{item.summary}）" if item.summary else ""
            lines.append(f"- {item.source}: {item.title}{summary}")
    else:
        lines.append("- なし")
    return "\n".join(lines)


def alexa_timestamp(moment: datetime) -> str:
    """Flash Briefing が要求する UTC の ISO 8601（例: 2016-05-23T22:34:51.0Z）。"""
    utc = moment.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.0Z")


def episode_id(moment: datetime, run_id: str | None = None) -> str:
    stamp = moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if run_id and run_id.isdigit():
        return f"{stamp}-{run_id}"
    return stamp


def build_flash_briefing(
    *,
    script: str,
    audio_url: str | None,
    redirection_url: str,
    moment: datetime,
    title: str,
) -> tuple[list[dict], list[dict] | None]:
    """テキスト用フィードと、音声がある場合の音声用フィードを返す。"""
    updated = alexa_timestamp(moment)
    text_item = {
        "uid": f"urn:uuid:{uuid.uuid4()}",
        "updateDate": updated,
        "titleText": title,
        "mainText": for_tts(script),
        "redirectionUrl": redirection_url,
    }
    audio_items = None
    if audio_url:
        audio_items = [
            {
                "uid": f"urn:uuid:{uuid.uuid4()}",
                "updateDate": updated,
                "titleText": title,
                "mainText": "",
                "streamUrl": audio_url,
                "redirectionUrl": redirection_url,
            }
        ]
    return [text_item], audio_items


def render_audio_rss(
    *,
    title: str,
    audio_url: str,
    file_size: int,
    redirection_url: str,
    moment: datetime,
    guid: str,
) -> str:
    updated = alexa_timestamp(moment)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <ttl>15</ttl>
    <item>
      <guid>{escape(guid)}</guid>
      <title>{escape(title)}</title>
      <description></description>
      <link>{escape(redirection_url)}</link>
      <pubDate>{updated}</pubDate>
      <enclosure url="{escape(audio_url)}" length="{file_size}" type="audio/mpeg"/>
    </item>
  </channel>
</rss>
"""
