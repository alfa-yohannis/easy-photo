"""Developing photos: the pixels each refinement option starts from."""

from __future__ import annotations

import numpy as np

from easy_photo.model.photo import Photo
from easy_photo.refinement.pipeline import RefinementPipeline
from easy_photo.services.darktable import DarktableError, DarktableRenderer
from easy_photo.services.darktable_edit import DarktableEdit, DarktableEditError
from easy_photo.services.photo_reader import PhotoReader, PhotoReadError


class DevelopError(Exception):
    """Raised when a photo cannot be developed."""


class PhotoDeveloper:
    """Gives the pixels a refinement option starts from.

    A raw file is developed from its raw data with darktable-cli when it is
    installed. When the option carries a darktable edit, darktable applies
    that edit; otherwise it uses the photo's own darktable sidecar, or its
    default development when the photo has none.

    Without darktable-cli, a raw file gives the JPEG preview the camera stores
    inside it, which is small and already compressed. Ordinary image files are
    read as they are, and a darktable edit is not applied to them, because its
    settings (white balance, for one) were made for raw data.
    """

    def __init__(self, reader: PhotoReader, darktable: DarktableRenderer) -> None:
        """Create a developer.

        Args:
            reader: Reads ordinary images, and raw previews when darktable-cli is missing.
            darktable: Develops raw files.
        """
        self._reader = reader
        self._darktable = darktable

    @property
    def uses_darktable(self) -> bool:
        """True when raw files are developed with darktable-cli."""
        return self._darktable.available

    def applies_edit(self, photo: Photo, pipeline: RefinementPipeline) -> bool:
        """Tell whether an option's darktable edit is applied to a photo.

        Args:
            photo: The photo.
            pipeline: The option.

        Returns:
            True when the option has a darktable edit and the photo is a raw file.
        """
        return pipeline.darktable_edit is not None and photo.is_raw

    def develop(self, photo: Photo, pipeline: RefinementPipeline, max_side: int, high_quality: bool) -> np.ndarray:
        """Develop a photo for an option, before the option's steps.

        Args:
            photo: The photo.
            pipeline: The option; only its darktable edit matters here.
            max_side: Longest side of the result.
            high_quality: For darktable: develop at full size and shrink at
                the end (for the export), or shrink early (for previews).

        Returns:
            Upright RGB values from 0 to 1 (float32), in sRGB.

        Raises:
            DevelopError: When the photo cannot be developed.
        """
        if photo.is_raw and self._darktable.available:
            return self._develop_raw(photo, pipeline, max_side, high_quality)
        if self.applies_edit(photo, pipeline):
            raise DevelopError("darktable-cli was not found, so the darktable edit cannot be applied.")
        try:
            pixels = self._reader.load_pixels(photo, max_side)
        except PhotoReadError as error:
            message = str(error)
            raise DevelopError(message) from error
        values = pixels.astype(np.float32)
        values /= 255.0
        return values

    def _develop_raw(
        self,
        photo: Photo,
        pipeline: RefinementPipeline,
        max_side: int,
        high_quality: bool,
    ) -> np.ndarray:
        """Develop a raw file with darktable-cli.

        Args:
            photo: The raw photo.
            pipeline: The option, with or without a darktable edit.
            max_side: Longest side of the result.
            high_quality: Develop at full size and shrink at the end.

        Returns:
            RGB values from 0 to 1 (float32).

        Raises:
            DevelopError: When the edit cannot be read or darktable-cli fails.
        """
        edit_text = None
        if pipeline.darktable_edit is not None:
            try:
                edit = DarktableEdit.read(pipeline.darktable_edit)
            except DarktableEditError as error:
                message = str(error)
                raise DevelopError(message) from error
            edit_text = edit.sidecar_text()
        try:
            return self._darktable.render(photo.path, edit_text, max_side, high_quality)
        except DarktableError as error:
            message = str(error)
            raise DevelopError(message) from error
