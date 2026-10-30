"""A small description of how a photo looks, used to compare photos."""

from __future__ import annotations

import numpy as np


class VisualSummary:
    """The colors and the rough layout of a photo.

    The colors are a histogram of hue, saturation and brightness whose values
    add up to 1. The layout is the photo shrunk to 16 x 16 grey pixels, with
    the average taken out and scaled to length 1. Both are small, so many
    photos can be compared quickly.
    """

    def __init__(self, color_histogram: np.ndarray, layout: np.ndarray) -> None:
        """Store the two parts of the summary.

        Args:
            color_histogram: Histogram values that add up to 1.
            layout: Grey values with the average removed, scaled to length 1.
        """
        self._color_histogram = color_histogram
        self._layout = layout

    @property
    def color_histogram(self) -> np.ndarray:
        """The color histogram (its values add up to 1)."""
        return self._color_histogram

    @property
    def layout(self) -> np.ndarray:
        """The grey layout values (length 1)."""
        return self._layout

    def similarity_to(self, other: VisualSummary) -> float:
        """Tell how alike two photos look.

        The result is the average of two parts: how much the color
        histograms overlap, and how well the layouts match (their
        correlation, moved from the -1..1 range to 0..1).

        Args:
            other: The summary of the other photo.

        Returns:
            A value from 0 (nothing alike) to 1 (the same).
        """
        overlap = np.minimum(self._color_histogram, other.color_histogram)
        color_match = overlap.sum()
        correlation = np.dot(self._layout, other.layout)
        layout_match = (correlation + 1.0) / 2.0
        similarity = (color_match + layout_match) / 2.0
        return float(similarity)
