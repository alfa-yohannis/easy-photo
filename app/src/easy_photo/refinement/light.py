"""Conversions between sRGB and linear light, the brightness curve, and brightness measuring."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np


class LinearLight:
    """Converts pixel values between sRGB, as stored in JPEG files, and linear light.

    Brightness changes are made in linear light, where twice the value means
    twice the light, so they behave like a change of exposure. Lookup tables
    make the conversions fast.
    """

    LUMA_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    """How much red, green and blue add to the brightness we see (Rec. 709)."""

    TABLE_SIZE = 16384
    """Number of entries in the table used to go from linear light back to sRGB."""

    def __init__(self) -> None:
        """Build the two lookup tables."""
        levels = np.arange(256, dtype=np.float32)
        srgb_levels = levels / 255.0
        self._to_linear_table = self._decode(srgb_levels)
        steps = np.arange(self.TABLE_SIZE, dtype=np.float32)
        linear_levels = steps / (self.TABLE_SIZE - 1)
        self._to_srgb_table = self._encode(linear_levels)

    def to_linear(self, pixels: np.ndarray) -> np.ndarray:
        """Turn sRGB pixels into linear light.

        Args:
            pixels: RGB pixels with values from 0 to 255 (uint8), or sRGB
                values from 0 to 1 (float), such as a 16-bit development from
                darktable.

        Returns:
            Float values from 0 to 1, same shape.
        """
        if pixels.dtype == np.uint8:
            return self._to_linear_table[pixels]
        return self.to_linear_values(pixels)

    def to_srgb_8bit(self, linear: np.ndarray) -> np.ndarray:
        """Turn linear light into 8-bit sRGB pixels. Values outside 0..1 are clipped.

        Args:
            linear: Float values in linear light.

        Returns:
            RGB pixels with values from 0 to 255 (uint8).
        """
        srgb = self.to_srgb_values(linear)
        return self.to_8bit(srgb)

    def to_8bit(self, pixels: np.ndarray) -> np.ndarray:
        """Turn sRGB values from 0 to 1 into 8-bit pixels, rounding to the nearest level.

        Args:
            pixels: Float sRGB values from 0 to 1 (values outside are clipped),
                or pixels that are already 8-bit, which are returned as they are.

        Returns:
            RGB pixels with values from 0 to 255 (uint8).
        """
        if pixels.dtype == np.uint8:
            return pixels
        clipped = np.clip(pixels, 0.0, 1.0)
        scaled = clipped * 255.0 + 0.5
        return scaled.astype(np.uint8)

    def to_srgb_values(self, linear: np.ndarray) -> np.ndarray:
        """Turn linear light into sRGB values from 0 to 1, which look evenly spaced to the eye.

        Args:
            linear: Float values in linear light. Values outside 0..1 are clipped.

        Returns:
            Float sRGB values from 0 to 1, same shape.
        """
        clipped = np.clip(linear, 0.0, 1.0)
        positions = clipped * (self.TABLE_SIZE - 1) + 0.5
        indexes = positions.astype(np.int32)
        return self._to_srgb_table[indexes]

    def to_linear_values(self, srgb: np.ndarray) -> np.ndarray:
        """Turn sRGB values from 0 to 1 into linear light.

        Args:
            srgb: Float sRGB values. Values outside 0..1 are clipped.

        Returns:
            Float values in linear light, same shape.
        """
        clipped = np.clip(srgb, 0.0, 1.0)
        return self._decode(clipped)

    def luma(self, rgb: np.ndarray) -> np.ndarray:
        """Brightness as the eye sees it, from RGB values.

        Args:
            rgb: Values with the three channels on the last axis.

        Returns:
            One brightness value per pixel.
        """
        return rgb @ self.LUMA_WEIGHTS

    def _decode(self, srgb: np.ndarray) -> np.ndarray:
        """The sRGB formula from sRGB values to linear light.

        Args:
            srgb: sRGB values from 0 to 1.

        Returns:
            Linear light values as float32.
        """
        low = srgb / 12.92
        shifted = (srgb + 0.055) / 1.055
        high = np.power(shifted, 2.4)
        result = np.where(srgb <= 0.04045, low, high)
        return result.astype(np.float32)

    def _encode(self, linear: np.ndarray) -> np.ndarray:
        """The sRGB formula from linear light to sRGB values.

        Args:
            linear: Linear light values from 0 to 1.

        Returns:
            sRGB values as float32.
        """
        low = linear * 12.92
        powered = np.power(linear, 1 / 2.4)
        high = 1.055 * powered - 0.055
        result = np.where(linear <= 0.0031308, low, high)
        return result.astype(np.float32)


class BrightnessCurve:
    """A brightness change for the whole photo that keeps black, white and the colors.

    For every pixel, the brightest of its three channels, n, becomes
    ``n * g / (1 + n * (g - 1))``, and all three channels are multiplied by
    the same factor. Black (0) and white (1) stay where they are. Dark and
    middle tones change like an exposure change of log2(g) stops, and the
    highlights roll off instead of clipping. Because the channels keep their
    ratios, hue and saturation do not change. This is the curve of the manual
    runs, where the user asked for brightness changes without color changes.
    """

    MIN_GAIN = 2.0 ** -2.0
    MAX_GAIN = 2.0 ** 3.0

    def __init__(self, gain: float = 1.0) -> None:
        """Create a curve.

        Args:
            gain: Above 1 brightens, below 1 darkens, 1 changes nothing.
        """
        self._gain = gain

    @classmethod
    def from_stops(cls, stops: float) -> BrightnessCurve:
        """Make the curve that works like an exposure change.

        Args:
            stops: Exposure change in stops (EV); +1 doubles the light in the dark tones.

        Returns:
            The curve.
        """
        gain = 2.0 ** stops
        return cls(gain)

    @classmethod
    def from_levels(cls, current: float, target: float) -> BrightnessCurve:
        """Make the curve that moves one brightness level to another.

        Args:
            current: The level now, in linear light (0 to 1).
            target: The level it should get, in linear light (0 to 1).

        Returns:
            The curve, with its gain kept within a sensible range.
        """
        if current <= 0.0 or target <= 0.0:
            return cls(1.0)
        current = min(current, 0.999)
        target = min(target, 0.999)
        gain = target * (1.0 - current) / (current * (1.0 - target))
        at_least = max(gain, cls.MIN_GAIN)
        limited = min(at_least, cls.MAX_GAIN)
        return cls(limited)

    @property
    def gain(self) -> float:
        """The gain g of the curve."""
        return self._gain

    @property
    def stops(self) -> float:
        """The change in the dark tones, in stops (EV)."""
        return math.log2(self._gain)

    @property
    def is_neutral(self) -> bool:
        """True when the curve changes (almost) nothing."""
        return abs(self._gain - 1.0) < 1e-3

    def apply_to_value(self, value: float) -> float:
        """Apply the curve to one brightness value.

        Args:
            value: Linear light value from 0 to 1.

        Returns:
            The new value.
        """
        return value * self._gain / (1.0 + value * (self._gain - 1.0))

    def apply(self, linear: np.ndarray) -> np.ndarray:
        """Apply the curve to a photo.

        Args:
            linear: RGB values in linear light, channels on the last axis.

        Returns:
            The changed values, same shape.
        """
        if self.is_neutral:
            return linear
        gain = self._gain
        brightest = linear.max(axis=-1, keepdims=True)
        curved = brightest * gain / (1.0 + brightest * (gain - 1.0))
        safe = np.maximum(brightest, 1e-6)
        factor = np.where(brightest > 1e-6, curved / safe, gain)
        return linear * factor


class BrightnessMeter:
    """Measures how bright a photo, or the faces in it, are, in linear light.

    Brightness here is the value of each pixel's brightest channel, the same
    value the :class:`BrightnessCurve` works on.
    """

    FACE_PERCENTILE = 40
    """Faces are measured at their 40th percentile, so shiny spots count little."""

    FACE_INNER_SHARE = 0.6
    """Only the middle 60 % of a face box is measured, to leave out hair and background."""

    MIN_FACE_PIXELS = 60

    def photo_brightness(self, linear: np.ndarray) -> float:
        """The median brightness of the whole photo.

        Args:
            linear: RGB values in linear light.

        Returns:
            The median of the brightest channel of every pixel.
        """
        brightest = linear.max(axis=-1)
        median = np.median(brightest)
        return float(median)

    def face_brightness(self, linear: np.ndarray, boxes: Sequence[tuple[int, int, int, int]]) -> float | None:
        """The typical brightness of the faces in a photo.

        Args:
            linear: RGB values in linear light.
            boxes: Face boxes in pixels, as (x, y, width, height).

        Returns:
            The median of the faces' brightness, or None when no box holds enough pixels.
        """
        values: list[float] = []
        border = (1.0 - self.FACE_INNER_SHARE) / 2.0
        for x, y, width, height in boxes:
            top = int(y + border * height)
            bottom = int(y + (1.0 - border) * height)
            left = int(x + border * width)
            right = int(x + (1.0 - border) * width)
            patch = linear[top:bottom, left:right]
            if patch.size < self.MIN_FACE_PIXELS:
                continue
            brightest = patch.max(axis=-1)
            value = np.percentile(brightest, self.FACE_PERCENTILE)
            face_value = float(value)
            values.append(face_value)
        if not values:
            return None
        middle = np.median(values)
        return float(middle)

    def key_brightness(
        self,
        linear: np.ndarray,
        boxes: Sequence[tuple[int, int, int, int]],
        use_faces: bool,
    ) -> float:
        """The brightness that a pipeline compares with its targets.

        Args:
            linear: RGB values in linear light.
            boxes: Face boxes in pixels, as (x, y, width, height).
            use_faces: Measure the faces when there are any.

        Returns:
            The faces' brightness when asked for and found, otherwise the photo's.
        """
        if use_faces and boxes:
            faces = self.face_brightness(linear, boxes)
            if faces is not None:
                return faces
        return self.photo_brightness(linear)
