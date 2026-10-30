"""Tests of reading typed refinements with Claude, using a stand-in client (no network, no cost)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from easy_photo.refinement.steps import StepCatalog
from easy_photo.services.ai_words import AiWordsError, AiWordsReader


class FakeMessages:
    """Stands in for ``client.beta.messages``: remembers each request and returns a prepared answer."""

    def __init__(self, answer: dict, stop_reason: str = "end_turn") -> None:
        """Prepare the answer.

        Args:
            answer: The JSON answer Claude would give.
            stop_reason: Why Claude would stop, such as "end_turn" or "refusal".
        """
        self.requests: list[dict] = []
        self._answer = answer
        self._stop_reason = stop_reason

    def create(self, **request: object) -> SimpleNamespace:
        """Remember the request and return a response that holds the prepared answer.

        Args:
            request: The request's parameters.

        Returns:
            A response with a thinking block and a text block, like the real API.
        """
        self.requests.append(request)
        text = json.dumps(self._answer)
        thinking = SimpleNamespace(type="thinking", thinking="")
        answer_block = SimpleNamespace(type="text", text=text)
        return SimpleNamespace(stop_reason=self._stop_reason, content=[thinking, answer_block])


class FakeClient:
    """Stands in for ``anthropic.Anthropic``, with only ``beta.messages``."""

    def __init__(self, messages: FakeMessages) -> None:
        """Wrap the stand-in messages.

        Args:
            messages: The stand-in for ``client.beta.messages``.
        """
        self.beta = SimpleNamespace(messages=messages)


def make_reader(answer: dict, stop_reason: str = "end_turn") -> tuple[AiWordsReader, FakeMessages]:
    """A reader that talks to a stand-in client.

    Args:
        answer: The JSON answer the stand-in gives.
        stop_reason: Why the stand-in stops.

    Returns:
        The reader and the stand-in messages, which keep the requests.
    """
    messages = FakeMessages(answer, stop_reason)
    client = FakeClient(messages)
    catalog = StepCatalog()
    reader = AiWordsReader(catalog, client=client)
    return reader, messages


def test_reader_turns_the_answer_into_steps() -> None:
    """The steps in the answer become step objects, with amounts kept in range."""
    answer = {
        "understood": True,
        "steps": [{"kind": "neutral_colors", "amount": 1}, {"kind": "contrast", "amount": -500}],
        "explanation": "Neutral colors, a little softer.",
    }
    reader, _messages = make_reader(answer)
    reading = reader.read("neutral, not warm, not cool, soft")
    kinds = [step.KIND for step in reading.steps]
    amounts = [step.amount for step in reading.steps]
    assert kinds == ["neutral_colors", "contrast"]
    assert amounts == [1.0, -100.0]
    assert reading.explanation == "Neutral colors, a little softer."


def test_reader_asks_with_the_schema_and_the_fallback() -> None:
    """The request names the model, asks for JSON with the schema, and opts into the default fallback."""
    answer = {"understood": True, "steps": [{"kind": "exposure", "amount": 0.3}], "explanation": "Brighter."}
    reader, messages = make_reader(answer)
    reader.read("a bit brighter please")
    request = messages.requests[0]
    output_format = request["output_config"]["format"]
    assert request["model"] == "claude-opus-5-5"
    assert request["fallbacks"] == "default"
    assert request["betas"] == ["server-side-fallback-2026-07-01"]
    assert output_format["type"] == "json_schema"
    assert request["messages"] == [{"role": "user", "content": "a bit brighter please"}]


def test_reader_says_what_claude_cannot_do() -> None:
    """When Claude says the app cannot do it, its explanation becomes the error."""
    answer = {"understood": False, "steps": [], "explanation": "Removing a person needs a retouch tool."}
    reader, _messages = make_reader(answer)
    with pytest.raises(AiWordsError, match="retouch"):
        reader.read("remove the man on the left")


def test_reader_reports_a_refusal() -> None:
    """A declined request ends in a clear error."""
    answer = {"understood": True, "steps": [], "explanation": ""}
    reader, _messages = make_reader(answer, "refusal")
    with pytest.raises(AiWordsError, match="declined"):
        reader.read("something")


def test_reader_skips_kinds_it_does_not_know() -> None:
    """Steps of an unknown kind are left out; the known ones stay."""
    answer = {
        "understood": True,
        "steps": [{"kind": "dehaze", "amount": 1}, {"kind": "warmth", "amount": -5}],
        "explanation": "",
    }
    reader, _messages = make_reader(answer)
    reading = reader.read("clear the haze and cool it a little")
    kinds = [step.KIND for step in reading.steps]
    assert kinds == ["warmth"]


def test_reader_needs_credentials(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Without a key, a token or an ant login, the reader says how to add a key and sends nothing.

    Args:
        monkeypatch: Changes the environment for this test only.
        tmp_path: An empty home folder, so no ant login profile is found.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    home_text = str(tmp_path)
    monkeypatch.setenv("HOME", home_text)
    catalog = StepCatalog()
    reader = AiWordsReader(catalog)
    assert not reader.has_credentials
    with pytest.raises(AiWordsError, match="API key"):
        reader.read("dramatic")
