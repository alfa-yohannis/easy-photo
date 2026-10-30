"""Writing the finished photos as JPEG files."""

from __future__ import annotations

import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageFilter

from easy_photo.model.face import Face
from easy_photo.model.photo import Photo
from easy_photo.refinement.pipeline import RefinementPipeline
from easy_photo.services.developer import DevelopError, PhotoDeveloper
from easy_photo.services.photo_reader import PhotoReader, PhotoReadError
from easy_photo.services.refiner import Refiner
from easy_photo.settings import ExportSettings


class ExportStatus(Enum):
    """What happened to one photo during the export."""

    WRITTEN = "Written"
    SKIPPED = "Skipped, a file with this name exists"
    FAILED = "Failed"


@dataclass(frozen=True)
class ExportResult:
    """The outcome of exporting one photo."""

    photo_id: str
    target: Path
    status: ExportStatus
    message: str = ""


class Exporter:
    """Develops, refines and writes photos as JPEG files, and never overwrites a file.

    Raw files are developed at the export size from their raw data (see
    :class:`PhotoDeveloper`), so the JPEG is compressed only once, at the end.
    Shrinking softens fine detail a little; an optional light sharpen brings
    it back.

    Each file is written under a temporary name first and only gets its real
    name when that name is still free, so a stopped export never leaves a
    half-written photo behind.
    """

    SHARPEN_RADIUS = 0.75
    SHARPEN_PERCENT = 75
    SHARPEN_THRESHOLD = 2
    """The light sharpen: radius 0.75 pixel, strength 75 %, and no change where neighbours differ
    by 2 levels or less, so smooth areas and noise stay as they are."""

    EDIT_LEFT_OUT = "without the darktable edit, which is only applied to raw files"

    def __init__(self, reader: PhotoReader, developer: PhotoDeveloper, refiner: Refiner) -> None:
        """Create an exporter.

        Args:
            reader: Reads the camera details of the photos.
            developer: Develops the photos.
            refiner: Applies the refinement steps.
        """
        self._reader = reader
        self._developer = developer
        self._refiner = refiner
        profile = ImageCms.createProfile("sRGB")
        wrapped = ImageCms.ImageCmsProfile(profile)
        self._srgb_profile = wrapped.tobytes()

    def target_for(self, photo: Photo, folder: Path) -> Path:
        """The file a photo is exported to.

        Args:
            photo: The photo.
            folder: The export folder.

        Returns:
            The JPEG file, named after the photo, such as P1199075.jpg.
        """
        return folder / f"{photo.stem}.jpg"

    def export(
        self,
        photo: Photo,
        pipeline: RefinementPipeline,
        faces: Sequence[Face],
        settings: ExportSettings,
    ) -> ExportResult:
        """Develop and refine one photo and write it.

        Args:
            photo: The photo.
            pipeline: The refinement chosen for its group.
            faces: The faces found in the photo.
            settings: Folder, size, quality, sharpening and metadata options.

        Returns:
            What happened.
        """
        folder = Path(settings.output_folder)
        target = self.target_for(photo, folder)
        if target.exists():
            return ExportResult(photo.id, target, ExportStatus.SKIPPED)
        try:
            values = self._developer.develop(photo, pipeline, settings.long_side, True)
            refined = self._refiner.refine(values, pipeline, faces)
            exif_bytes = self._exif_of(photo) if settings.copy_metadata else None
            placed = self._write(refined, target, settings, exif_bytes)
        except (DevelopError, OSError, ValueError) as error:
            message = str(error)
            return ExportResult(photo.id, target, ExportStatus.FAILED, message)
        if not placed:
            return ExportResult(photo.id, target, ExportStatus.SKIPPED)
        message = ""
        if pipeline.darktable_edit is not None and not self._developer.applies_edit(photo, pipeline):
            message = self.EDIT_LEFT_OUT
        return ExportResult(photo.id, target, ExportStatus.WRITTEN, message)

    def _exif_of(self, photo: Photo) -> bytes | None:
        """The camera details to copy into the exported file.

        For a raw file they come from the camera's preview inside it, which
        holds the same details as the raw file.

        Args:
            photo: The photo.

        Returns:
            The EXIF data, or None when the photo has none or it cannot be read.
        """
        try:
            image = self._reader.open_upright(photo)
        except PhotoReadError:
            return None
        return self._reader.exif_bytes_of(image)

    def _write(self, pixels: np.ndarray, target: Path, settings: ExportSettings, exif_bytes: bytes | None) -> bool:
        """Save pixels as a JPEG file under the target name, if that name is still free.

        Args:
            pixels: RGB pixels, 8 bits per channel.
            target: The file to write.
            settings: The JPEG quality and whether to sharpen.
            exif_bytes: Camera details to store in the file, or None.

        Returns:
            False when a file with the target name appeared in the meantime.
        """
        target.parent.mkdir(parents=True, exist_ok=True)
        unique = uuid.uuid4().hex
        temporary = target.with_name(f".{target.stem}.{unique}.part")
        image = Image.fromarray(pixels)
        if settings.sharpen:
            sharpen = ImageFilter.UnsharpMask(self.SHARPEN_RADIUS, self.SHARPEN_PERCENT, self.SHARPEN_THRESHOLD)
            image = image.filter(sharpen)
        options: dict = {"quality": settings.quality, "optimize": True, "icc_profile": self._srgb_profile}
        if settings.quality >= 90:
            # Full color resolution; at high quality, halving it would waste the quality.
            options["subsampling"] = 0
        if exif_bytes:
            options["exif"] = exif_bytes
        image.save(temporary, "JPEG", **options)
        return self._place(temporary, target)

    def _place(self, temporary: Path, target: Path) -> bool:
        """Give the finished file its real name, but only when that name is free.

        A hard link fails when the name exists, so no file can be overwritten,
        even by a second export running at the same time. File systems without
        hard links fall back to a check followed by a rename.

        Args:
            temporary: The finished file under its temporary name.
            target: The real name.

        Returns:
            True when the file got its real name.
        """
        try:
            os.link(temporary, target)
        except FileExistsError:
            temporary.unlink(missing_ok=True)
            return False
        except OSError:
            if target.exists():
                temporary.unlink(missing_ok=True)
                return False
            os.replace(temporary, target)
            return True
        temporary.unlink(missing_ok=True)
        return True
