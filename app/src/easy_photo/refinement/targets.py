"""Brightness levels learned from reference photos."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class BrightnessTargets:
    """Brightness levels of a set of reference photos, in linear light (0 to 1).

    The four levels are the 25th, 50th, 75th and 90th percentiles of the
    references' key brightness: the brightness of their faces when enough
    faces were found, otherwise the brightness of the whole photos.
    """

    low: float
    typical: float
    high: float
    ceiling: float
    uses_faces: bool
    reference_count: int

    def target_for(self, current: float) -> float | None:
        """Tell which brightness a photo should get.

        A photo darker than the lower quarter of the references is raised to
        their typical level. A photo brighter than nine in ten references is
        lowered to their upper quarter. Anything in between is left alone, so
        the changes stay small. This is the face standard of the manual runs.

        Args:
            current: The photo's key brightness, in linear light.

        Returns:
            The brightness to move to, or None when the photo is fine as it is.
        """
        if current < self.low:
            return self.typical
        if current > self.ceiling:
            return self.high
        return None

    def to_data(self) -> dict:
        """The levels as a dictionary, for the project manifest.

        Returns:
            A dictionary that :meth:`from_data` reads back.
        """
        return asdict(self)

    @classmethod
    def from_data(cls, data: dict) -> BrightnessTargets:
        """Read levels saved by :meth:`to_data`.

        Args:
            data: The saved dictionary.

        Returns:
            The levels.
        """
        return cls(
            low=data["low"],
            typical=data["typical"],
            high=data["high"],
            ceiling=data["ceiling"],
            uses_faces=data["uses_faces"],
            reference_count=data["reference_count"],
        )
