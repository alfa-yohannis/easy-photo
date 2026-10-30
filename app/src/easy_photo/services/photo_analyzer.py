"""Measures each photo once, for the filter and grouping steps."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from easy_photo.model.quality import QualityScores
from easy_photo.model.summary import VisualSummary


@dataclass(frozen=True)
class PhotoAnalysis:
    """Everything measured on one photo."""

    scores: QualityScores
    summary: VisualSummary

    thumbnail: np.ndarray
    """A small RGB copy for the photo grid."""


class PhotoAnalyzer:
    """Measures sharpness, contrast and brightness, and makes the visual summary and the thumbnail.

    Sharpness and contrast are measured in nine overlapping windows, each half
    as wide and half as high as the photo, and the best window counts. A photo
    that is blurred except for one sharp part is therefore not "badly
    blurred": a crop could keep the sharp part.
    """

    ANALYSIS_SIDE = 1024
    """Photos are measured on a copy with this longest side, so results do not depend on the camera."""

    THUMBNAIL_SIDE = 320
    BLOWN_LEVEL = 0.98
    """Brightness (sRGB, 0 to 1) from which a pixel counts as blown out."""

    HISTOGRAM_BINS = [8, 4, 4]
    """Bins for hue, saturation and brightness in the color histogram."""

    LAYOUT_SIDE = 16

    def analyze(self, pixels: np.ndarray) -> PhotoAnalysis:
        """Measure a photo.

        Args:
            pixels: Upright RGB pixels, 8 bits per channel.

        Returns:
            The scores, the visual summary and a thumbnail.
        """
        small = self._shrink(pixels, self.ANALYSIS_SIDE)
        grey = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
        scores = self._scores(grey)
        summary = self._summary(small, grey)
        thumbnail = self._shrink(pixels, self.THUMBNAIL_SIDE)
        return PhotoAnalysis(scores, summary, thumbnail)

    def _scores(self, grey: np.ndarray) -> QualityScores:
        """Measure sharpness, contrast, the brightest tones and the blown-out share.

        Args:
            grey: Grey copy of the photo, 8 bits.

        Returns:
            The scores.
        """
        laplacian = cv2.Laplacian(grey, cv2.CV_32F)
        brightness = grey.astype(np.float32) / 255.0
        windows = self._half_windows(grey.shape)
        best_sharpness = 0.0
        best_contrast = 0.0
        for window in windows:
            sharpness = laplacian[window].var()
            contrast = brightness[window].std()
            best_sharpness = max(best_sharpness, sharpness)
            best_contrast = max(best_contrast, contrast)
        highlight = np.percentile(brightness, 95)
        blown = brightness >= self.BLOWN_LEVEL
        blown_share = blown.mean()
        sharpness_value = float(best_sharpness)
        contrast_value = float(best_contrast)
        highlight_value = float(highlight)
        blown_value = float(blown_share)
        return QualityScores(sharpness_value, contrast_value, highlight_value, blown_value)

    def _half_windows(self, shape: tuple[int, ...]) -> list[tuple[slice, slice]]:
        """The nine overlapping windows, each half the width and half the height of the photo.

        Args:
            shape: Shape of the grey photo, (height, width).

        Returns:
            The windows as (rows, columns) slices.
        """
        height, width = shape[:2]
        half_height = height // 2
        half_width = width // 2
        tops = (0, height // 4, height - half_height)
        lefts = (0, width // 4, width - half_width)
        windows: list[tuple[slice, slice]] = []
        for top in tops:
            for left in lefts:
                rows = slice(top, top + half_height)
                columns = slice(left, left + half_width)
                windows.append((rows, columns))
        return windows

    def _summary(self, rgb: np.ndarray, grey: np.ndarray) -> VisualSummary:
        """Make the color histogram and the grey layout used to compare photos.

        Args:
            rgb: The shrunk photo.
            grey: Its grey copy.

        Returns:
            The visual summary.
        """
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        histogram = cv2.calcHist([hsv], [0, 1, 2], None, self.HISTOGRAM_BINS, [0, 180, 0, 256, 0, 256])
        flat = histogram.flatten()
        total = flat.sum()
        if total > 0:
            flat = flat / total
        layout_size = (self.LAYOUT_SIDE, self.LAYOUT_SIDE)
        tiny = cv2.resize(grey, layout_size, interpolation=cv2.INTER_AREA)
        layout = tiny.astype(np.float32).flatten()
        layout = layout - layout.mean()
        length = np.linalg.norm(layout)
        if length > 0:
            layout = layout / length
        return VisualSummary(flat, layout)

    def _shrink(self, pixels: np.ndarray, max_side: int) -> np.ndarray:
        """Shrink pixels so their longest side is at most ``max_side``.

        Args:
            pixels: The pixels.
            max_side: The longest side allowed.

        Returns:
            The shrunk pixels, or the same pixels when they are small enough.
        """
        height, width = pixels.shape[:2]
        longest = max(height, width)
        if longest <= max_side:
            return pixels
        scale = max_side / longest
        new_width = round(width * scale)
        new_height = round(height * scale)
        return cv2.resize(pixels, (new_width, new_height), interpolation=cv2.INTER_AREA)
