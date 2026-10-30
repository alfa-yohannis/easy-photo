"""The refinement steps that pipelines are made of.

Every step works on RGB values in linear light (floats, normally 0 to 1) and
returns new values of the same shape. The brightness steps scale the three
channels of a pixel by the same factor, so they leave the colors alone. Only
the saturation and warmth steps change colors, and only when the user asks.

Each step can turn itself into a dictionary (:meth:`RefinementStep.to_data`),
so pipelines can be saved in the project manifest and read back with
:class:`StepCatalog`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

from easy_photo.refinement.light import BrightnessCurve, BrightnessMeter, LinearLight
from easy_photo.refinement.targets import BrightnessTargets
from easy_photo.wording import count_text


@dataclass
class StepContext:
    """What a step may need besides the pixels: the face boxes and the measuring tools."""

    face_boxes: tuple[tuple[int, int, int, int], ...] = ()
    """Face boxes in pixels of the picture being refined, as (x, y, width, height)."""

    light: LinearLight = field(default_factory=LinearLight)
    meter: BrightnessMeter = field(default_factory=BrightnessMeter)


class RefinementStep(ABC):
    """One change made to a photo, such as "Exposure +0.3 EV"."""

    KIND = ""
    """Name of the step in the project manifest. Every subclass sets its own."""

    @abstractmethod
    def apply(self, linear: np.ndarray, context: StepContext) -> np.ndarray:
        """Change the pixels.

        Args:
            linear: RGB values in linear light, shape (height, width, 3).
            context: Face boxes and measuring tools for this photo.

        Returns:
            The changed values, same shape.
        """

    @abstractmethod
    def describe(self) -> str:
        """Short text for the window.

        Returns:
            Text such as "Exposure +0.3 EV".
        """

    @abstractmethod
    def to_data(self) -> dict:
        """The step as a dictionary for the project manifest.

        Returns:
            A dictionary with the key "kind" and the step's settings.
        """


class AmountStep(RefinementStep):
    """A step controlled by one number, its amount.

    Subclasses set ``LOWEST`` and ``HIGHEST``; amounts outside that range
    are moved to the nearest end, so a typed "+50" cannot ruin a photo.
    """

    LOWEST = -1.0
    HIGHEST = 1.0

    def __init__(self, amount: float) -> None:
        """Create the step.

        Args:
            amount: How strong the change is; its meaning depends on the step.
        """
        at_least = max(amount, self.LOWEST)
        self._amount = min(at_least, self.HIGHEST)

    @property
    def amount(self) -> float:
        """How strong the change is."""
        return self._amount

    def to_data(self) -> dict:
        """The step as a dictionary for the project manifest.

        Returns:
            A dictionary with the step's kind and amount.
        """
        return {"kind": self.KIND, "amount": self._amount}


class ToneCurveStep(AmountStep):
    """A step that changes brightness through a curve on each pixel's brightest channel.

    Subclasses give the curve in :meth:`curve`. The curve works on sRGB
    values (0 to 1), which look evenly spaced to the eye, so a change looks
    equally strong in dark and bright parts. The three channels of a pixel are
    multiplied by the same factor, so the colors stay.
    """

    def apply(self, linear: np.ndarray, context: StepContext) -> np.ndarray:
        """Change the pixels with the subclass's curve.

        Args:
            linear: RGB values in linear light.
            context: Gives the sRGB conversions.

        Returns:
            The changed values.
        """
        brightest = linear.max(axis=-1)
        before = context.light.to_srgb_values(brightest)
        after = self.curve(before)
        after_linear = context.light.to_linear_values(after)
        safe = np.maximum(brightest, 1e-6)
        factor = np.where(brightest > 1e-6, after_linear / safe, 1.0)
        return linear * factor[..., np.newaxis]

    @abstractmethod
    def curve(self, values: np.ndarray) -> np.ndarray:
        """Map brightness values to new ones.

        Args:
            values: sRGB brightness values from 0 to 1.

        Returns:
            The new values, from 0 to 1.
        """


class ExposureStep(AmountStep):
    """Makes the whole photo brighter or darker, like the exposure setting of a camera.

    The amount is in stops (EV). Highlights roll off instead of clipping.
    """

    KIND = "exposure"
    LOWEST = -3.0
    HIGHEST = 3.0

    def apply(self, linear: np.ndarray, context: StepContext) -> np.ndarray:
        """Change the exposure.

        Args:
            linear: RGB values in linear light.
            context: Not used by this step.

        Returns:
            The changed values.
        """
        curve = BrightnessCurve.from_stops(self._amount)
        return curve.apply(linear)

    def describe(self) -> str:
        """Short text for the window.

        Returns:
            Text such as "Exposure +0.3 EV".
        """
        return f"Exposure {self._amount:+.1f} EV"


class ContrastStep(ToneCurveStep):
    """More or less contrast in the middle tones; black and white stay where they are.

    The amount is a percentage from -100 to 100. The curve mixes each value
    with an S-shaped curve (``3v² - 2v³``) for more contrast, or moves it away
    from that curve for less.
    """

    KIND = "contrast"
    LOWEST = -100.0
    HIGHEST = 100.0

    def curve(self, values: np.ndarray) -> np.ndarray:
        """Mix the values with the S-shaped curve.

        Args:
            values: sRGB brightness values from 0 to 1.

        Returns:
            The new values.
        """
        s_curve = values * values * (3.0 - 2.0 * values)
        strength = self._amount / 100.0
        return values + strength * (s_curve - values)

    def describe(self) -> str:
        """Short text for the window.

        Returns:
            Text such as "Contrast +20 %".
        """
        return f"Contrast {self._amount:+.0f} %"


class ShadowsStep(ToneCurveStep):
    """Brightens or darkens the dark tones and leaves the bright tones almost alone.

    The curve adds ``0.9 * amount * v * (1 - v)²``, which is largest at a
    third of the way up and zero at black and white. Within the allowed range
    the curve never reverses, so the order of tones stays.
    """

    KIND = "shadows"
    LOWEST = -1.0
    HIGHEST = 1.5

    def curve(self, values: np.ndarray) -> np.ndarray:
        """Lift or lower the dark tones.

        Args:
            values: sRGB brightness values from 0 to 1.

        Returns:
            The new values.
        """
        darkness = 1.0 - values
        return values + 0.9 * self._amount * values * darkness * darkness

    def describe(self) -> str:
        """Short text for the window.

        Returns:
            Text such as "Shadows +0.6".
        """
        return f"Shadows {self._amount:+.1f}"


class HighlightsStep(ToneCurveStep):
    """Brightens or darkens the bright tones and leaves the dark tones almost alone.

    The curve adds ``0.9 * amount * v² * (1 - v)``, which is largest at two
    thirds of the way up and zero at black and white.
    """

    KIND = "highlights"
    LOWEST = -1.5
    HIGHEST = 1.0

    def curve(self, values: np.ndarray) -> np.ndarray:
        """Lift or lower the bright tones.

        Args:
            values: sRGB brightness values from 0 to 1.

        Returns:
            The new values.
        """
        darkness = 1.0 - values
        return values + 0.9 * self._amount * values * values * darkness

    def describe(self) -> str:
        """Short text for the window.

        Returns:
            Text such as "Highlights -0.6".
        """
        return f"Highlights {self._amount:+.1f}"


class SaturationStep(AmountStep):
    """Makes colors stronger or weaker; -100 gives a black and white photo.

    Each pixel is moved away from (or toward) its own grey value, so the
    brightness stays the same.
    """

    KIND = "saturation"
    LOWEST = -100.0
    HIGHEST = 100.0

    def apply(self, linear: np.ndarray, context: StepContext) -> np.ndarray:
        """Change the color strength.

        Args:
            linear: RGB values in linear light.
            context: Gives the brightness weights.

        Returns:
            The changed values.
        """
        grey = context.light.luma(linear)
        grey_pixels = grey[..., np.newaxis]
        factor = 1.0 + self._amount / 100.0
        changed = grey_pixels + (linear - grey_pixels) * factor
        return np.maximum(changed, 0.0)

    def describe(self) -> str:
        """Short text for the window.

        Returns:
            Text such as "Saturation +20 %", or "Black and white".
        """
        if self._amount <= -100.0:
            return "Black and white"
        return f"Saturation {self._amount:+.0f} %"


class WarmthStep(AmountStep):
    """Makes the light warmer (more orange) or cooler (more blue).

    The amount is a percentage: red is multiplied by ``1 + amount / 100`` and
    blue by ``1 - amount / 100``.
    """

    KIND = "warmth"
    LOWEST = -30.0
    HIGHEST = 30.0

    def apply(self, linear: np.ndarray, context: StepContext) -> np.ndarray:
        """Shift the color of the light.

        Args:
            linear: RGB values in linear light.
            context: Not used by this step.

        Returns:
            The changed values.
        """
        share = self._amount / 100.0
        gains = np.array([1.0 + share, 1.0, 1.0 - share], dtype=np.float32)
        return linear * gains

    def describe(self) -> str:
        """Short text for the window.

        Returns:
            Text such as "Warmth +6".
        """
        return f"Warmth {self._amount:+.0f}"


class NeutralColorStep(AmountStep):
    """Removes a color cast, so the photo is neither warm nor cool.

    The cast is measured on the pixels that are already nearly grey (little
    color, neither very dark nor very bright). Measuring only those pixels
    keeps a red maple or green grass from counting as a cast. Red and blue are
    then scaled so that, on those pixels, they match green. The amount, from 0
    to 1, says how much of the cast is removed. The change is limited to 25 %
    per channel, so an unusual scene cannot turn strange.
    """

    KIND = "neutral_colors"
    LOWEST = 0.0
    HIGHEST = 1.0
    MAX_CHANGE = 0.25
    """Largest change of the red or blue channel, as a share."""

    MAX_COLORFULNESS = 0.3
    """Pixels with less color than this (0 = grey) are used to measure the cast."""

    MIN_SHARE = 0.01
    """When fewer nearly grey pixels than this share exist, all usable pixels are measured."""

    def apply(self, linear: np.ndarray, context: StepContext) -> np.ndarray:
        """Scale red and blue to remove the cast.

        Args:
            linear: RGB values in linear light.
            context: Not used by this step.

        Returns:
            The changed values.
        """
        red_gain, blue_gain = self.gains_for(linear)
        red_factor = 1.0 + self._amount * (red_gain - 1.0)
        blue_factor = 1.0 + self._amount * (blue_gain - 1.0)
        factors = np.array([red_factor, 1.0, blue_factor], dtype=np.float32)
        return linear * factors

    def gains_for(self, linear: np.ndarray) -> tuple[float, float]:
        """Measure how much red and blue must change to remove the cast.

        Args:
            linear: RGB values in linear light.

        Returns:
            The full gains for red and blue (1 means no change).
        """
        brightest = linear.max(axis=-1)
        darkest = linear.min(axis=-1)
        safe = np.maximum(brightest, 1e-6)
        colorfulness = (brightest - darkest) / safe
        usable = (brightest > 0.02) & (brightest < 0.9)
        greyish = usable & (colorfulness < self.MAX_COLORFULNESS)
        greyish_share = greyish.mean()
        chosen = greyish if greyish_share >= self.MIN_SHARE else usable
        if not chosen.any():
            return 1.0, 1.0
        means = linear[chosen].mean(axis=0)
        red_mean, green_mean, blue_mean = means
        if red_mean <= 0.0 or blue_mean <= 0.0:
            return 1.0, 1.0
        red_gain = self._limit(green_mean / red_mean)
        blue_gain = self._limit(green_mean / blue_mean)
        return red_gain, blue_gain

    def describe(self) -> str:
        """Short text for the window.

        Returns:
            "Neutral colors", with the share when it is not the full correction.
        """
        if self._amount >= 1.0:
            return "Neutral colors"
        return f"Neutral colors ({self._amount:.0%})"

    def _limit(self, gain: float) -> float:
        """Keep a gain within the allowed change.

        Args:
            gain: The measured gain.

        Returns:
            The gain, at most 25 % away from 1.
        """
        at_least = max(gain, 1.0 - self.MAX_CHANGE)
        limited = min(at_least, 1.0 + self.MAX_CHANGE)
        return float(limited)


class FaceBrightnessStep(AmountStep):
    """Brightens or darkens the whole photo so that the faces change by the amount, in stops.

    The change is one curve for the whole photo, never a patch on the faces:
    in the manual runs a lift on the faces alone looked like a bright spot on
    a darker photo. Without faces, the step uses the photo's own brightness.
    """

    KIND = "face_brightness"
    LOWEST = -2.0
    HIGHEST = 2.0

    def apply(self, linear: np.ndarray, context: StepContext) -> np.ndarray:
        """Change the brightness so the faces move by the amount.

        Args:
            linear: RGB values in linear light.
            context: Gives the face boxes and the brightness meter.

        Returns:
            The changed values.
        """
        current = context.meter.key_brightness(linear, context.face_boxes, True)
        if current <= 0.0:
            return linear
        wanted = current * 2.0 ** self._amount
        target = min(wanted, 0.95)
        curve = BrightnessCurve.from_levels(current, target)
        return curve.apply(linear)

    def describe(self) -> str:
        """Short text for the window.

        Returns:
            Text such as "Faces +0.4 EV".
        """
        return f"Faces {self._amount:+.1f} EV"


class MatchBrightnessStep(RefinementStep):
    """Brings a photo to the brightness of a set of reference photos.

    The photo's key brightness (its faces when the references were measured
    on faces, otherwise the whole photo) is compared with the targets, and one
    :class:`BrightnessCurve` for the whole photo moves it there.
    """

    KIND = "match_brightness"

    def __init__(self, targets: BrightnessTargets, reference_name: str) -> None:
        """Create the step.

        Args:
            targets: Brightness levels of the references.
            reference_name: What the references are, for the window, such as "your history".
        """
        self._targets = targets
        self._reference_name = reference_name

    @property
    def targets(self) -> BrightnessTargets:
        """Brightness levels of the references."""
        return self._targets

    def apply(self, linear: np.ndarray, context: StepContext) -> np.ndarray:
        """Move the photo to the references' brightness when it is outside their range.

        Args:
            linear: RGB values in linear light.
            context: Gives the face boxes and the brightness meter.

        Returns:
            The changed values, or the same values when no change is needed.
        """
        uses_faces = self._targets.uses_faces
        current = context.meter.key_brightness(linear, context.face_boxes, uses_faces)
        target = self._targets.target_for(current)
        if target is None:
            return linear
        curve = BrightnessCurve.from_levels(current, target)
        return curve.apply(linear)

    def describe(self) -> str:
        """Short text for the window.

        Returns:
            Text such as "Brightness of your history (209 photos, faces)".
        """
        photos_text = count_text(self._targets.reference_count, "photo")
        measured = "faces" if self._targets.uses_faces else "whole photos"
        return f"Brightness of {self._reference_name} ({photos_text}, {measured})"

    def to_data(self) -> dict:
        """The step as a dictionary for the project manifest.

        Returns:
            A dictionary with the kind, the reference name and the targets.
        """
        targets = self._targets.to_data()
        return {"kind": self.KIND, "reference_name": self._reference_name, "targets": targets}


class StepCatalog:
    """Turns dictionaries from the project manifest back into steps."""

    def __init__(self) -> None:
        """List the step classes that are read by their amount."""
        self._amount_steps: dict[str, type[AmountStep]] = {
            ExposureStep.KIND: ExposureStep,
            ContrastStep.KIND: ContrastStep,
            ShadowsStep.KIND: ShadowsStep,
            HighlightsStep.KIND: HighlightsStep,
            SaturationStep.KIND: SaturationStep,
            WarmthStep.KIND: WarmthStep,
            NeutralColorStep.KIND: NeutralColorStep,
            FaceBrightnessStep.KIND: FaceBrightnessStep,
        }

    def load(self, data: dict) -> RefinementStep:
        """Make a step from its dictionary.

        Args:
            data: A dictionary written by :meth:`RefinementStep.to_data`.

        Returns:
            The step.

        Raises:
            ValueError: When the kind of step is unknown.
        """
        kind = data.get("kind", "")
        if kind == MatchBrightnessStep.KIND:
            targets_data = data["targets"]
            targets = BrightnessTargets.from_data(targets_data)
            return MatchBrightnessStep(targets, data["reference_name"])
        step_class = self._amount_steps.get(kind)
        if step_class is None:
            raise ValueError(f"Unknown refinement step: {kind!r}")
        return step_class(data["amount"])
