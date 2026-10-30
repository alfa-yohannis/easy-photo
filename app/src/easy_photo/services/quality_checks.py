"""The rules of the filter step: badly blurred, no clear subject, too dark, too bright."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from easy_photo.model.quality import CheckResult, Decision, Problem, QualityResult, QualityScores
from easy_photo.settings import CheckSettings


class QualityCheck(ABC):
    """One rule of the filter step, such as "badly blurred".

    A check reads one value from a photo's scores and compares it with a
    limit. Values past the limit set the photo aside. Values within the
    margin before the limit make the photo "unsure", so the user decides.
    """

    def __init__(self, limit: float, margin: float) -> None:
        """Create a check.

        Args:
            limit: The value from which the photo is set aside.
            margin: How far before the limit a photo already counts as unsure.
        """
        self._limit = limit
        self._margin = margin

    @property
    @abstractmethod
    def problem(self) -> Problem:
        """The problem this check looks for."""

    @abstractmethod
    def value_of(self, scores: QualityScores) -> float:
        """Read the value this check compares with its limit.

        Args:
            scores: The photo's scores.

        Returns:
            The value.
        """

    @abstractmethod
    def decide(self, value: float) -> Decision:
        """Compare a value with the limit and the margin.

        Args:
            value: The value read by :meth:`value_of`.

        Returns:
            The decision for the photo.
        """

    def check(self, scores: QualityScores) -> CheckResult:
        """Run the check on a photo.

        Args:
            scores: The photo's scores.

        Returns:
            The result, with the value and the limit for the window.
        """
        value = self.value_of(scores)
        decision = self.decide(value)
        return CheckResult(self.problem, decision, value, self._limit)


class TooLowCheck(QualityCheck):
    """A check that fails when its value is below the limit."""

    def decide(self, value: float) -> Decision:
        """Set aside below the limit, unsure just above it, keep otherwise.

        Args:
            value: The photo's value.

        Returns:
            The decision.
        """
        if value < self._limit:
            return Decision.SET_ASIDE
        if value < self._limit + self._margin:
            return Decision.UNSURE
        return Decision.KEEP


class TooHighCheck(QualityCheck):
    """A check that fails when its value is above the limit."""

    def decide(self, value: float) -> Decision:
        """Set aside above the limit, unsure just below it, keep otherwise.

        Args:
            value: The photo's value.

        Returns:
            The decision.
        """
        if value > self._limit:
            return Decision.SET_ASIDE
        if value > self._limit - self._margin:
            return Decision.UNSURE
        return Decision.KEEP


class BlurCheck(TooLowCheck):
    """Badly blurred: even the sharpest half of the photo has no fine edges."""

    @property
    def problem(self) -> Problem:
        """This check looks for blur."""
        return Problem.BLURRED

    def value_of(self, scores: QualityScores) -> float:
        """Read the sharpness of the sharpest half.

        Args:
            scores: The photo's scores.

        Returns:
            The sharpness.
        """
        return scores.sharpness


class UnclearCheck(TooLowCheck):
    """No clear subject: even the most detailed half of the photo is flat."""

    @property
    def problem(self) -> Problem:
        """This check looks for photos without a clear subject."""
        return Problem.UNCLEAR

    def value_of(self, scores: QualityScores) -> float:
        """Read the contrast of the most detailed half.

        Args:
            scores: The photo's scores.

        Returns:
            The contrast.
        """
        return scores.contrast


class TooDarkCheck(TooLowCheck):
    """Too dark to recover: even the brightest parts of the photo are dark."""

    @property
    def problem(self) -> Problem:
        """This check looks for photos that are too dark."""
        return Problem.TOO_DARK

    def value_of(self, scores: QualityScores) -> float:
        """Read the brightness of the brightest 5 % of the pixels.

        Args:
            scores: The photo's scores.

        Returns:
            The brightness.
        """
        return scores.highlight


class TooBrightCheck(TooHighCheck):
    """Too bright to recover: a large part of the photo is pure white."""

    @property
    def problem(self) -> Problem:
        """This check looks for photos that are too bright."""
        return Problem.TOO_BRIGHT

    def value_of(self, scores: QualityScores) -> float:
        """Read the share of blown-out pixels.

        Args:
            scores: The photo's scores.

        Returns:
            The share, from 0 to 1.
        """
        return scores.blown_share


class QualityChecker:
    """Runs all quality checks on a photo's scores."""

    def __init__(self, checks: Sequence[QualityCheck]) -> None:
        """Create a checker.

        Args:
            checks: The checks to run, in the order they are shown.
        """
        self._checks = tuple(checks)

    @classmethod
    def from_settings(cls, settings: CheckSettings) -> QualityChecker:
        """Make the four standard checks with the user's limits.

        Args:
            settings: The limits and margins.

        Returns:
            The checker.
        """
        blur = BlurCheck(settings.min_sharpness, settings.sharpness_margin)
        unclear = UnclearCheck(settings.min_contrast, settings.contrast_margin)
        too_dark = TooDarkCheck(settings.min_highlight, settings.highlight_margin)
        too_bright = TooBrightCheck(settings.max_blown_share, settings.blown_margin)
        return cls([blur, unclear, too_dark, too_bright])

    def evaluate(self, scores: QualityScores) -> QualityResult:
        """Run every check on a photo.

        Args:
            scores: The photo's scores.

        Returns:
            The results of all checks.
        """
        results = [check.check(scores) for check in self._checks]
        result_tuple = tuple(results)
        return QualityResult(scores, result_tuple)
