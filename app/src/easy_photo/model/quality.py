"""Results of the quality checks in the filter step."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Decision(Enum):
    """What the filter step does with a photo."""

    KEEP = "Keep"
    UNSURE = "Unsure"
    SET_ASIDE = "Set aside"

    @property
    def severity(self) -> int:
        """0 for keep, 1 for unsure and 2 for set aside, for finding the most serious decision."""
        order = {Decision.KEEP: 0, Decision.UNSURE: 1, Decision.SET_ASIDE: 2}
        return order[self]

    @property
    def is_kept(self) -> bool:
        """True when the photo goes on to the next steps.

        Unsure photos count as kept until the user sets them aside, so the
        app never drops a photo the user has not seen.
        """
        return self is not Decision.SET_ASIDE


class Problem(Enum):
    """A reason to set a photo aside."""

    BLURRED = "Badly blurred"
    UNCLEAR = "No clear subject"
    TOO_DARK = "Too dark"
    TOO_BRIGHT = "Too bright"


@dataclass(frozen=True)
class QualityScores:
    """Measurements of one photo, made on a copy about 1024 pixels wide.

    Sharpness and contrast come from the best of nine overlapping windows,
    each half as wide and half as high as the photo. A photo with a sharp or
    detailed part that a crop could keep therefore scores well.
    """

    sharpness: float
    """Variance of the Laplacian (the strength of fine edges) in the sharpest window."""

    contrast: float
    """Standard deviation of the brightness (0 to 1) in the most detailed window."""

    highlight: float
    """Brightness reached by the brightest 5 % of the pixels (sRGB, 0 to 1)."""

    blown_share: float
    """Share of the pixels that are almost pure white (0 to 1)."""


@dataclass(frozen=True)
class CheckResult:
    """The outcome of one quality check on one photo."""

    problem: Problem
    decision: Decision
    value: float
    limit: float


@dataclass(frozen=True)
class QualityResult:
    """The results of all quality checks on one photo."""

    scores: QualityScores
    checks: tuple[CheckResult, ...]

    @property
    def decision(self) -> Decision:
        """The most serious decision among the checks."""
        worst = Decision.KEEP
        for result in self.checks:
            if result.decision.severity > worst.severity:
                worst = result.decision
        return worst

    @property
    def problems(self) -> list[Problem]:
        """The problems of the checks that did not end in "keep"."""
        return [result.problem for result in self.checks if result.decision is not Decision.KEEP]

    def summary(self) -> str:
        """Short text for a photo tile.

        Returns:
            Text such as "Badly blurred, Too dark", or "Looks fine".
        """
        names = [problem.value for problem in self.problems]
        if not names:
            return "Looks fine"
        return ", ".join(names)
