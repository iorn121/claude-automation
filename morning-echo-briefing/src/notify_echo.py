"""Voice Monkey 経由で Echo Dot に朝のブリーフィングを再生させる。

音声 URL があるときはその mp3 を再生する（VOICEVOX の声）。
無いときは台本を Alexa の日本語音声で読む。トークンはログに出さない。
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

from clock import seconds_until
from content import truncate_for_speech

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("notify_echo")

ROOT = Path(__file__).resolve().parent.parent
ANNOUNCE_URL = "https://api-v3.voicemonkey.io/announce"
DEFAULT_CHIME = "soundbank://soundlibrary/ui/gameshow/amzn_ui_sfx_gameshow_positive_response_01"
DEFAULT_VOICE = "Mizuki"


def _chime() -> str | None:
    if "VOICE_MONKEY_CHIME" not in os.environ:
        return DEFAULT_CHIME
    value = os.environ["VOICE_MONKEY_CHIME"].strip()
    return value or None


def announce(
    *,
    token: str,
    device: str,
    speech: str | None = None,
    audio_url: str | None = None,
    voice: str = DEFAULT_VOICE,
    language: str = "ja-JP",
    chime: str | None = DEFAULT_CHIME,
) -> None:
    use_audio = bool(audio_url and audio_url.startswith("https://"))
    body: dict[str, str] = {"token": token, "device": device}
    if chime:
        body["chime"] = chime
    if use_audio:
        body["audio"] = audio_url or ""
    else:
        if not speech:
            raise RuntimeError("読み上げる台本がありません")
        body["speech"] = truncate_for_speech(speech)
        body["voice"] = voice
        body["language"] = language

    response = _post(body)
    if response is None:
        return
    # 音声 ID を Alexa 側が拒否したときは、声の指定だけ外して一度だけやり直す。
    if response.status_code == 400 and not use_audio and (body.get("voice") or body.get("language")):
        log.warning("音声の指定が拒否されたため、デフォルトの声で再送します")
        body.pop("voice", None)
        body.pop("language", None)
        response = _post(body)
        if response is None:
            return
    _raise_for_status(response)
    log.info("Echo へのアナウンスを受け付けました（%s）", "音声ファイル" if use_audio else "テキスト読み上げ")


def _post(body: dict[str, str]) -> requests.Response | None:
    last: requests.Response | None = None
    for attempt in range(1, 3):
        response = requests.post(ANNOUNCE_URL, json=body, timeout=45)
        if response.status_code != 500:
            return response
        last = response
        log.warning("Voice Monkey が一時エラーを返しました (%d/2)", attempt)
        time.sleep(3)
    return last


def _raise_for_status(response: requests.Response) -> None:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.ok and payload.get("success", True):
        return
    error = payload.get("error") or response.status_code
    raise RuntimeError(f"Voice Monkey のアナウンスに失敗しました ({error})")


def _load_script() -> str:
    path = ROOT / "data" / "script.txt"
    if not path.exists():
        raise RuntimeError(f"台本がありません: {path}")
    return path.read_text(encoding="utf-8")


def main() -> None:
    load_dotenv(ROOT / ".env", override=True)
    token = os.environ.get("VOICE_MONKEY_TOKEN", "").strip()
    device = os.environ.get("VOICE_MONKEY_DEVICE", "").strip()
    if not token or not device:
        log.info("VOICE_MONKEY_TOKEN または VOICE_MONKEY_DEVICE が未設定のため、Echo への送信はしません")
        return

    tz = ZoneInfo(os.environ.get("BRIEFING_TIMEZONE", "Asia/Tokyo"))
    wait = seconds_until(
        datetime.now(tz),
        os.environ.get("ANNOUNCE_AT", "07:00"),
        max_wait_sec=int(os.environ.get("ANNOUNCE_MAX_WAIT_SEC", str(40 * 60))),
    )
    if wait:
        log.info("アナウンス時刻まで %d 秒待ちます", wait)
        time.sleep(wait)

    audio_url = os.environ.get("BRIEFING_AUDIO_URL", "").strip() or None
    if audio_url and not audio_url.startswith("https://"):
        log.warning("音声URLが https ではないため、テキスト読み上げに切り替えます")
        audio_url = None
    speech = None if audio_url else _load_script()
    announce(
        token=token,
        device=device,
        speech=speech,
        audio_url=audio_url,
        voice=os.environ.get("VOICE_MONKEY_VOICE", DEFAULT_VOICE),
        language=os.environ.get("VOICE_MONKEY_LANGUAGE", "ja-JP"),
        chime=_chime(),
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log.error("%s", exc)
        sys.exit(1)
