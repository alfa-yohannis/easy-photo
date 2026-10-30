"""Applying a refinement pipeline to a photo's pixels."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from easy_photo.model.face import Face
from easy_photo.refinement.light import BrightnessMeter, LinearLight
from easy_photo.refinement.pipeline import RefinementPipeline
from easy_photo.refinement.steps import StepContext


class Refiner:
    """Applies a refinement pipeline's steps to a photo.

    The pixels are turned into linear light, every step of the pipeline runs,
    and the result is turned back into 8-bit sRGB. A darktable edit in the
    pipeline is not applied here; darktable applies it while it develops the
    photo (see :class:`~easy_photo.services.developer.PhotoDeveloper`).
    """

    def __init__(self) -> None:
        """Prepare the conversion tables and the brightness meter, shared by all photos."""
        self._light = LinearLight()
        self._meter = BrightnessMeter()

    def refine(self, pixels: np.ndarray, pipeline: RefinementPipeline, faces: Sequence[Face]) -> np.ndarray:
        """Refine a photo.

        Args:
            pixels: Upright RGB pixels: 8-bit values, or sRGB values from 0 to 1 (float).
            pipeline: The refinement to apply.
            faces: The faces found in the photo; their boxes are fractions, so any size of pixels works.

        Returns:
            The refined pixels as 8-bit sRGB, same size.
        """
        if not pipeline.steps:
            return self._light.to_8bit(pixels)
        height, width = pixels.shape[:2]
        boxes = [face.box.to_pixels(width, height) for face in faces]
        box_tuple = tuple(boxes)
        context = StepContext(box_tuple, self._light, self._meter)
        linear = self._light.to_linear(pixels)
        refined = pipeline.apply(linear, context)
        return self._light.to_srgb_8bit(refined)
