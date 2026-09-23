"""Gemini 要約の 503 リトライとモデル切り替えのユニットテスト。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from google.genai import errors as genai_errors  # noqa: E402

import summarize  # noqa: E402


def _api_error(code: int, status: str, kind: type[genai_errors.APIError]) -> genai_errors.APIError:
    class _Body:
        body_segments = [{"error": {"code": code, "message": status, "status": status}}]

    return kind(code, _Body())


def server_error() -> genai_errors.ServerError:
    return _api_error(503, "UNAVAILABLE", genai_errors.ServerError)


def not_found() -> genai_errors.ClientError:
    return _api_error(404, "NOT_FOUND", genai_errors.ClientError)


class _Response:
    def __init__(self, text: str) -> None:
        self.text = text


class _Models:
    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[str] = []

    def generate_content(self, *, model: str, contents: str, config: dict) -> _Response:
        self.calls.append(model)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome  # type: ignore[return-value]


class _Client:
    def __init__(self, models: _Models) -> None:
        self.models = models


ARTICLES = [{"source": "Example", "title": "題", "text": "本文", "labels": ["AI"]}]


class ResolveModelsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {
            key: summarize.os.environ.get(key)
            for key in ("GEMINI_MODEL", "GEMINI_FALLBACK_MODELS")
        }
        for key in self._saved:
            summarize.os.environ.pop(key, None)

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                summarize.os.environ.pop(key, None)
            else:
                summarize.os.environ[key] = value

    def test_default_chain(self) -> None:
        self.assertEqual(
            summarize.resolve_models(),
            ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-2.5-flash"],
        )

    def test_primary_is_not_repeated_in_fallbacks(self) -> None:
        summarize.os.environ["GEMINI_MODEL"] = "gemini-2.5-flash"
        summarize.os.environ["GEMINI_FALLBACK_MODELS"] = "gemini-2.5-flash, gemini-3.5-flash"
        self.assertEqual(
            summarize.resolve_models(),
            ["gemini-2.5-flash", "gemini-3.5-flash"],
        )

    def test_empty_fallback_env_disables_switch(self) -> None:
        summarize.os.environ["GEMINI_FALLBACK_MODELS"] = ""
        self.assertEqual(summarize.resolve_models(), ["gemini-3.6-flash"])


class SummarizeRetryTests(unittest.TestCase):
    def test_empty_articles_skips_api(self) -> None:
        text = summarize.summarize([], "2026-09-23", "key", client=object())
        self.assertIn("収集できませんでした", text)

    def test_retries_same_model_then_succeeds(self) -> None:
        models = _Models([server_error(), _Response("台本です")])
        sleeps: list[int] = []
        script = summarize.summarize(
            ARTICLES,
            "2026-09-23",
            "key",
            client=_Client(models),
            models=["gemini-3.6-flash"],
            sleep=sleeps.append,
        )
        self.assertEqual(script, "台本です")
        self.assertEqual(models.calls, ["gemini-3.6-flash", "gemini-3.6-flash"])
        self.assertEqual(sleeps, [20])

    def test_switches_model_after_sustained_503(self) -> None:
        models = _Models([server_error(), server_error(), _Response("予備の台本")])
        sleeps: list[int] = []
        script = summarize.summarize(
            ARTICLES,
            "2026-09-23",
            "key",
            client=_Client(models),
            models=["gemini-3.6-flash", "gemini-2.5-flash"],
            sleep=sleeps.append,
        )
        self.assertEqual(script, "予備の台本")
        self.assertEqual(models.calls, ["gemini-3.6-flash", "gemini-3.6-flash", "gemini-2.5-flash"])
        self.assertEqual(sleeps, [20])

    def test_all_models_unavailable_raises(self) -> None:
        models = _Models([server_error(), server_error(), server_error(), server_error()])
        with self.assertRaises(RuntimeError) as ctx:
            summarize.summarize(
                ARTICLES,
                "2026-09-23",
                "key",
                client=_Client(models),
                models=["gemini-3.6-flash", "gemini-2.5-flash"],
                sleep=lambda _sec: None,
            )
        self.assertIn("gemini-3.6-flash", str(ctx.exception))
        self.assertIn("gemini-2.5-flash", str(ctx.exception))

    def test_missing_model_switches_without_retry(self) -> None:
        models = _Models([not_found(), _Response("別モデルの台本")])
        sleeps: list[int] = []
        script = summarize.summarize(
            ARTICLES,
            "2026-09-23",
            "key",
            client=_Client(models),
            models=["gone-model", "gemini-2.5-flash"],
            sleep=sleeps.append,
        )
        self.assertEqual(script, "別モデルの台本")
        self.assertEqual(models.calls, ["gone-model", "gemini-2.5-flash"])
        self.assertEqual(sleeps, [])

    def test_client_error_other_than_404_is_not_retried(self) -> None:
        models = _Models([_api_error(400, "INVALID_ARGUMENT", genai_errors.ClientError)])
        with self.assertRaises(genai_errors.ClientError):
            summarize.summarize(
                ARTICLES,
                "2026-09-23",
                "key",
                client=_Client(models),
                models=["gemini-3.6-flash", "gemini-2.5-flash"],
                sleep=lambda _sec: None,
            )
        self.assertEqual(models.calls, ["gemini-3.6-flash"])


if __name__ == "__main__":
    unittest.main()
