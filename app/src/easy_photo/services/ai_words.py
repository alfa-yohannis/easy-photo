"""Reading a refinement described in the user's own words with Claude."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import anthropic

from easy_photo.refinement.steps import RefinementStep, StepCatalog


class AiWordsError(Exception):
    """Raised when Claude cannot be asked, or cannot turn the words into refinement steps."""


@dataclass(frozen=True)
class AiReading:
    """What Claude made of the user's words: the steps, and one sentence about them."""

    steps: tuple[RefinementStep, ...]
    explanation: str


class AiWordsReader:
    """Asks Claude to turn a refinement described in the user's own words into refinement steps.

    Only the words are sent to Anthropic, never the photos. Claude answers
    with JSON that follows a fixed schema (structured outputs): a list of
    steps, each of a kind the app knows, with an amount. The app checks the
    answer, and each step keeps its amount within its own range.

    The request asks Anthropic to retry on its recommended fallback model when
    a safety classifier declines (``fallbacks: "default"``), so a false alarm
    does not end in an error.
    """

    DEFAULT_MODEL = "claude-opus-5-5"
    MODELS = (
        ("claude-opus-5-5", "Claude Opus 5.5 (best)"),
        ("claude-sonnet-5-5", "Claude Sonnet 5.5"),
        ("claude-haiku-5-5", "Claude Haiku 5.5 (fastest, cheapest)"),
    )
    """The models the user can choose, with their names for the window."""

    FALLBACK_BETA = "server-side-fallback-2026-07-01"
    MAX_TOKENS = 4096
    TIMEOUT_SECONDS = 60.0
    EFFORT = "low"
    """Reading a short request needs little thinking; low effort keeps the answer quick."""

    STEP_KINDS = (
        "exposure",
        "contrast",
        "shadows",
        "highlights",
        "saturation",
        "warmth",
        "neutral_colors",
        "face_brightness",
    )

    NO_CREDENTIALS = (
        "Claude has no API key yet. Add one in Settings, AI for your own words, "
        "or set ANTHROPIC_API_KEY before starting the app."
    )

    SYSTEM_PROMPT = (
        "You turn a photographer's request, written in their own words, into adjustments for a photo app. "
        "The app can only make these adjustments to the whole photo, each with an amount:\n"
        "- exposure: brightness of the whole photo in stops, from -3 to 3; 0.3 is a small step.\n"
        "- contrast: in percent, from -100 to 100; 20 is a clear step.\n"
        "- shadows: brightens (positive) or deepens (negative) the dark tones, from -1 to 1.5.\n"
        "- highlights: brightens (positive) or tones down (negative) the bright tones, from -1.5 to 1.\n"
        "- saturation: color strength in percent, from -100 (black and white) to 100.\n"
        "- warmth: in percent, from -30 (cooler, bluer) to 30 (warmer, more orange).\n"
        "- neutral_colors: removes a color cast so the photo is neither warm nor cool, "
        "from 0 to 1 (1 removes it fully).\n"
        "- face_brightness: changes the whole photo so the faces get brighter or darker, in stops, from -2 to 2.\n\n"
        "Use as few adjustments as the request needs, in the order they should be applied, with moderate "
        "amounts unless the request asks for strong ones. Do not change colors the request does not mention. "
        "If the request needs something these adjustments cannot do, such as removing an object or cropping, "
        "set understood to false and say why in the explanation. Write the explanation as one short sentence "
        "in the language of the request."
    )

    SCHEMA = {
        "type": "object",
        "properties": {
            "understood": {"type": "boolean"},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": list(STEP_KINDS)},
                        "amount": {"type": "number"},
                    },
                    "required": ["kind", "amount"],
                    "additionalProperties": False,
                },
            },
            "explanation": {"type": "string"},
        },
        "required": ["understood", "steps", "explanation"],
        "additionalProperties": False,
    }
    """The JSON schema Claude's answer must follow."""

    def __init__(
        self,
        catalog: StepCatalog,
        api_key: str = "",
        model: str = DEFAULT_MODEL,
        client: object | None = None,
    ) -> None:
        """Create a reader.

        Args:
            catalog: Turns the steps in Claude's answer into step objects.
            api_key: Anthropic API key; empty uses the environment or an ``ant auth login`` profile.
            model: The Claude model to ask.
            client: A ready client, for tests; normally the reader makes its own.
        """
        self._catalog = catalog
        self._api_key = api_key
        self._model = model
        self._client = client

    @property
    def model(self) -> str:
        """The Claude model the reader asks."""
        return self._model

    @property
    def has_credentials(self) -> bool:
        """True when an API key is set here or in the environment, or an ``ant auth login`` profile exists."""
        if self._client is not None or self._api_key:
            return True
        for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            if os.environ.get(name):
                return True
        profile_folder = Path.home() / ".config" / "anthropic"
        return profile_folder.exists()

    def read(self, text: str) -> AiReading:
        """Ask Claude to read a refinement described in words.

        Args:
            text: What the user typed, such as "neutral, not warm, not cool".

        Returns:
            The steps and Claude's one-sentence explanation.

        Raises:
            AiWordsError: When Claude cannot be reached, declines, or finds nothing it can do.
        """
        cleaned = text.strip()
        if not cleaned:
            raise AiWordsError("Type what you would like to change.")
        if not self.has_credentials:
            raise AiWordsError(self.NO_CREDENTIALS)
        answer = self._ask(cleaned)
        return self._reading_from(answer)

    def _make_client(self) -> object:
        """The client that sends the request: the one given, or a new one.

        Returns:
            An Anthropic client.
        """
        if self._client is not None:
            return self._client
        if self._api_key:
            return anthropic.Anthropic(api_key=self._api_key, timeout=self.TIMEOUT_SECONDS)
        return anthropic.Anthropic(timeout=self.TIMEOUT_SECONDS)

    def _ask(self, text: str) -> dict:
        """Send the words to Claude and return the JSON answer.

        Args:
            text: The cleaned words.

        Returns:
            The answer, as a dictionary that follows :attr:`SCHEMA`.

        Raises:
            AiWordsError: When the request fails or the answer cannot be used.
        """
        client = self._make_client()
        answer_format = {"type": "json_schema", "schema": self.SCHEMA}
        output_config = {"effort": self.EFFORT, "format": answer_format}
        messages = [{"role": "user", "content": text}]
        try:
            response = client.beta.messages.create(
                model=self._model,
                max_tokens=self.MAX_TOKENS,
                betas=[self.FALLBACK_BETA],
                fallbacks="default",
                system=self.SYSTEM_PROMPT,
                output_config=output_config,
                messages=messages,
            )
        except anthropic.AuthenticationError as error:
            raise AiWordsError("Anthropic did not accept the API key. Check it in Settings.") from error
        except anthropic.PermissionDeniedError as error:
            raise AiWordsError("This API key may not use Claude for this request.") from error
        except anthropic.NotFoundError as error:
            raise AiWordsError(f"The model {self._model} is not available to this API key.") from error
        except anthropic.RateLimitError as error:
            raise AiWordsError("Claude is busy right now. Try again in a minute.") from error
        except anthropic.APIStatusError as error:
            raise AiWordsError(f"Claude could not answer (error {error.status_code}). Try again later.") from error
        except anthropic.APIConnectionError as error:
            raise AiWordsError("Claude could not be reached. Check the internet connection.") from error
        return self._answer_from(response)

    def _answer_from(self, response: object) -> dict:
        """Take the JSON answer out of Claude's response.

        Args:
            response: The response of the Messages API.

        Returns:
            The answer as a dictionary.

        Raises:
            AiWordsError: When Claude declined, was cut off, or sent no readable JSON.
        """
        if response.stop_reason == "refusal":
            raise AiWordsError("Claude declined to read these words.")
        if response.stop_reason == "max_tokens":
            raise AiWordsError("Claude's answer was cut off. Try shorter words.")
        texts = [block.text for block in response.content if block.type == "text"]
        if not texts:
            raise AiWordsError("Claude gave no answer.")
        try:
            answer = json.loads(texts[0])
        except json.JSONDecodeError as error:
            raise AiWordsError("Claude's answer could not be read.") from error
        if not isinstance(answer, dict):
            raise AiWordsError("Claude's answer could not be read.")
        return answer

    def _reading_from(self, answer: dict) -> AiReading:
        """Turn Claude's JSON answer into steps.

        Args:
            answer: The answer, following :attr:`SCHEMA`.

        Returns:
            The steps and the explanation.

        Raises:
            AiWordsError: When Claude did not understand the request or found nothing to change.
        """
        explanation_value = answer.get("explanation", "")
        explanation = explanation_value if isinstance(explanation_value, str) else ""
        if not answer.get("understood", False):
            raise AiWordsError(explanation or "Claude could not turn these words into a refinement.")
        steps: list[RefinementStep] = []
        for item in answer.get("steps", []):
            step = self._step_from(item)
            if step is not None:
                steps.append(step)
        if not steps:
            raise AiWordsError(explanation or "Claude found nothing to change.")
        step_tuple = tuple(steps)
        return AiReading(step_tuple, explanation)

    def _step_from(self, item: object) -> RefinementStep | None:
        """Make one step from an entry of Claude's answer.

        Args:
            item: One entry of the "steps" list.

        Returns:
            The step, or None when the entry is not a known kind with a number.
        """
        if not isinstance(item, dict):
            return None
        kind = item.get("kind")
        amount = item.get("amount")
        if kind not in self.STEP_KINDS or not isinstance(amount, (int, float)):
            return None
        data = {"kind": kind, "amount": amount}
        return self._catalog.load(data)
