"""The light sharpen after shrinking, shared by the export and the Refine previews."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter


class Sharpener:
    """Sharpens a shrunk photo a little, to bring back the fine detail that shrinking softens.

    It is an unsharp mask with a radius of 0.75 pixel at 75 % strength. Where
    neighbouring pixels differ by 2 levels or less nothing changes, so smooth
    areas and noise stay as they are.
    """

    RADIUS = 0.75
    PERCENT = 75
    THRESHOLD = 2

    def __init__(self) -> None:
        """Prepare the filter."""
        self._filter = ImageFilter.UnsharpMask(self.RADIUS, self.PERCENT, self.THRESHOLD)

    def sharpen(self, pixels: np.ndarray) -> np.ndarray:
        """Sharpen a photo.

        Args:
            pixels: RGB pixels, 8 bits per channel.

        Returns:
            The sharpened pixels, same size.
        """
        image = Image.fromarray(pixels)
        sharpened = image.filter(self._filter)
        return np.array(sharpened)
