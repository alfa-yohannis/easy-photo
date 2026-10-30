"""Refinement commands typed by the user, such as "brighter, more contrast"."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from easy_photo.refinement.steps import (
    ContrastStep,
    ExposureStep,
    FaceBrightnessStep,
    HighlightsStep,
    NeutralColorStep,
    RefinementStep,
    SaturationStep,
    ShadowsStep,
    WarmthStep,
)

NUMBER = r"(?P<amount>[+-]?\d+(?:[.,]\d+)?)"
"""A signed number such as "+0.5" or "-10". A comma also works as the decimal mark."""


@dataclass(frozen=True)
class ParsedCommands:
    """The steps read from a typed command, and the parts that were not understood."""

    steps: tuple[RefinementStep, ...]
    unknown: tuple[str, ...]

    @property
    def is_complete(self) -> bool:
        """True when every part was understood and at least one step was found."""
        return bool(self.steps) and not self.unknown


class CommandRule:
    """One way of saying a refinement, such as "more contrast" or "contrast +20"."""

    def __init__(
        self,
        pattern: str,
        make_step: Callable[[float], RefinementStep],
        default_amount: float,
        example: str,
    ) -> None:
        """Create a rule.

        Args:
            pattern: Regular expression the whole phrase must match. A group
                named "amount" takes a number from the phrase.
            make_step: Makes the step from an amount; usually a step class.
            default_amount: Amount used when the phrase has no number.
            example: A phrase that matches, shown to the user as a hint.
        """
        self._pattern = re.compile(pattern)
        self._make_step = make_step
        self._default_amount = default_amount
        self._example = example

    @property
    def example(self) -> str:
        """A phrase that matches this rule."""
        return self._example

    def match(self, phrase: str, strength: float) -> RefinementStep | None:
        """Make a step from a phrase when the phrase matches this rule.

        Args:
            phrase: One part of a command, in lower case.
            strength: Factor from words such as "slightly" (0.5) or "much" (2),
                used when the phrase has no number.

        Returns:
            The step, or None when the phrase does not match.
        """
        found = self._pattern.fullmatch(phrase)
        if found is None:
            return None
        amount = self._amount_from(found, strength)
        return self._make_step(amount)

    def _amount_from(self, found: re.Match, strength: float) -> float:
        """Read the amount from a match, or use the default amount times the strength.

        Args:
            found: The regular expression match.
            strength: Factor for the default amount.

        Returns:
            The amount for the step.
        """
        groups = found.groupdict()
        text = groups.get("amount")
        if text is None:
            return self._default_amount * strength
        cleaned = text.replace(",", ".")
        return float(cleaned)


class CommandParser:
    """Reads refinement commands typed by the user.

    A command is a list of short phrases separated by commas, "and", "then"
    or new lines, for example "brighter, more contrast and slightly warmer".
    Words such as "slightly" or "much" make a phrase weaker or stronger.
    Phrases can also give a number, such as "exposure +0.5" or "contrast -10".
    """

    SEPARATOR = re.compile(r"\s*(?:[;\n]|(?<!\d),|,(?!\d)|\band\b|\bthen\b)\s*")
    """Splits a command into phrases. A comma between two digits is a decimal mark, not a separator."""

    KEPT_TOGETHER = (("black and white", "black & white"),)
    """Phrases that contain a separator word, rewritten so they are not split."""

    HINT_COUNT = 6
    """How many example phrases a "not understood" message shows."""

    STRENGTH_WORDS = (
        ("a little ", 0.5),
        ("a bit ", 0.5),
        ("a touch ", 0.5),
        ("slightly ", 0.5),
        ("much ", 2.0),
        ("a lot ", 2.0),
        ("way ", 2.0),
        ("very ", 1.5),
    )
    """Words at the start of a phrase that make its default amount weaker or stronger."""

    def __init__(self) -> None:
        """Prepare the list of rules."""
        self._rules = self._make_rules()

    def parse(self, text: str) -> ParsedCommands:
        """Read a typed command.

        Args:
            text: What the user typed.

        Returns:
            The steps, in the order they were typed, and the phrases that were not understood.
        """
        steps: list[RefinementStep] = []
        unknown: list[str] = []
        seen: list[dict] = []
        lowered = text.lower()
        for phrase, replacement in self.KEPT_TOGETHER:
            lowered = lowered.replace(phrase, replacement)
        parts = self.SEPARATOR.split(lowered)
        for part in parts:
            phrase = self._clean(part)
            if not phrase:
                continue
            step = self._read_phrase(phrase)
            if step is None:
                unknown.append(phrase)
                continue
            # The same change said twice ("neutral, not warm") is made once.
            data = step.to_data()
            if data in seen:
                continue
            seen.append(data)
            steps.append(step)
        step_list = tuple(steps)
        unknown_list = tuple(unknown)
        return ParsedCommands(step_list, unknown_list)

    def examples(self) -> list[str]:
        """Phrases the parser understands, one per rule, for hints in the window.

        Returns:
            The example phrases.
        """
        return [rule.example for rule in self._rules]

    def explain(self, unknown: Sequence[str]) -> str:
        """Say which phrases were not understood, with examples that work.

        Args:
            unknown: The phrases that were not understood.

        Returns:
            The message for the user.
        """
        examples = self.examples()
        some = examples[: self.HINT_COUNT]
        hint = ", ".join(some)
        if not unknown:
            return f"Type what to change, for example: {hint}."
        quoted = [f'"{phrase}"' for phrase in unknown]
        joined = ", ".join(quoted)
        return f"Not understood: {joined}. Try for example: {hint}."

    def _clean(self, part: str) -> str:
        """Remove extra spaces and closing punctuation from a phrase.

        Args:
            part: One part of the command.

        Returns:
            The cleaned phrase.
        """
        words = part.split()
        joined = " ".join(words)
        return joined.strip(" .!")

    def _read_phrase(self, phrase: str) -> RefinementStep | None:
        """Find the rule that matches a phrase and make its step.

        Args:
            phrase: One cleaned phrase in lower case.

        Returns:
            The step, or None when no rule matches.
        """
        strength, rest = self._split_strength(phrase)
        for rule in self._rules:
            step = rule.match(rest, strength)
            if step is not None:
                return step
        return None

    def _split_strength(self, phrase: str) -> tuple[float, str]:
        """Take a strength word such as "slightly" off the start of a phrase.

        Args:
            phrase: One cleaned phrase.

        Returns:
            The strength factor (1 when there is no such word) and the rest of the phrase.
        """
        for word, factor in self.STRENGTH_WORDS:
            if phrase.startswith(word):
                rest = phrase[len(word):]
                return factor, rest
        return 1.0, phrase

    def _make_rules(self) -> list[CommandRule]:
        """The phrases the parser understands.

        Returns:
            The rules. Each rule must match a whole phrase, so their order only
            matters for phrases that two rules could both match.
        """
        return [
            CommandRule(r"brighter|lighter|more exposure|brighten(?: it)?(?: up)?", ExposureStep, 0.3, "brighter"),
            CommandRule(r"darker|less exposure|darken(?: it)?", ExposureStep, -0.3, "darker"),
            CommandRule(rf"(?:exposure|brightness|ev)\s*{NUMBER}\s*(?:ev|stops?)?", ExposureStep, 0.0, "exposure +0.5"),
            CommandRule(
                r"more contrast|higher contrast|stronger contrast|punchier|more punch|crisper",
                ContrastStep,
                20.0,
                "more contrast",
            ),
            CommandRule(r"less contrast|lower contrast|softer|flatter|less punch", ContrastStep, -20.0, "less contrast"),
            CommandRule(rf"contrast\s*{NUMBER}\s*%?", ContrastStep, 0.0, "contrast +15"),
            CommandRule(
                r"(?:lift|brighten|open(?: up)?)(?: the)? shadows|brighter shadows|shadows brighter|more shadow detail",
                ShadowsStep,
                0.6,
                "lift shadows",
            ),
            CommandRule(
                r"(?:deepen|darken)(?: the)? shadows|darker shadows|deeper shadows|shadows darker",
                ShadowsStep,
                -0.5,
                "deeper shadows",
            ),
            CommandRule(rf"shadows?\s*{NUMBER}", ShadowsStep, 0.0, "shadows +0.5"),
            CommandRule(
                r"(?:recover|soften|tame|tone down|darken)(?: the)? highlights|softer highlights|darker highlights",
                HighlightsStep,
                -0.6,
                "recover highlights",
            ),
            CommandRule(
                r"(?:brighten|lift|boost)(?: the)? highlights|brighter highlights|highlights brighter",
                HighlightsStep,
                0.4,
                "brighter highlights",
            ),
            CommandRule(rf"highlights?\s*{NUMBER}", HighlightsStep, 0.0, "highlights -0.5"),
            CommandRule(
                r"more (?:colou?r|saturation)|more colou?rful|colou?rful|more vivid|vivid|vibrant|more saturated",
                SaturationStep,
                20.0,
                "more color",
            ),
            CommandRule(
                r"less (?:colou?r|saturation)|less colou?rful|muted|less saturated|desaturated?",
                SaturationStep,
                -20.0,
                "less color",
            ),
            CommandRule(rf"saturation\s*{NUMBER}\s*%?", SaturationStep, 0.0, "saturation +10"),
            CommandRule(
                r"black and white|black & white|b ?& ?w|monochrome|gr[ae]y ?scale",
                SaturationStep,
                -100.0,
                "black and white",
            ),
            CommandRule(r"warmer|more warmth|warm(?: it up)?", WarmthStep, 6.0, "warmer"),
            CommandRule(r"cooler|colder|less warmth|cool(?: it down)?", WarmthStep, -6.0, "cooler"),
            CommandRule(rf"(?:warmth|temperature)\s*{NUMBER}", WarmthStep, 0.0, "warmth +5"),
            CommandRule(
                r"neutral(?: colou?rs?| white balance| wb| tones?)?|not warm|not cool|no colou?r cast"
                r"|remove(?: the)? colou?r cast|auto white balance",
                NeutralColorStep,
                1.0,
                "neutral colors",
            ),
            CommandRule(
                r"brighter faces?|faces? brighter|(?:brighten|lift)(?: the)? faces?",
                FaceBrightnessStep,
                0.4,
                "brighter faces",
            ),
            CommandRule(
                r"darker faces?|faces? darker|darken(?: the)? faces?",
                FaceBrightnessStep,
                -0.3,
                "darker faces",
            ),
            CommandRule(rf"faces?\s*{NUMBER}\s*(?:ev|stops?)?", FaceBrightnessStep, 0.0, "faces +0.3"),
        ]
