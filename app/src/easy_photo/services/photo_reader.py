"""Reads photos as upright RGB pixels, and reads their camera details."""

from __future__ import annotations

import io
import math
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import rawpy
from PIL import ExifTags, Image, ImageOps

from easy_photo.model.photo import Photo, PhotoInfo
from easy_photo.services.preview_cache import PreviewCache


class PhotoReadError(Exception):
    """Raised when a photo file cannot be read."""


@dataclass(frozen=True)
class PhotoData:
    """What the scan step reads from a photo: its camera details and its pixels."""

    info: PhotoInfo

    pixels: np.ndarray
    """Upright RGB pixels, 8 bits per channel."""


class PhotoReader:
    """Opens photos as upright RGB pixels and reads their camera details.

    Raw files are not developed. The reader uses the JPEG picture that the
    camera stores inside every raw file: it is quick to read and shows the
    camera's own colors. The first time a raw file is read, its picture is
    turned upright and saved in the :class:`PreviewCache`, with the camera
    details kept in it.
    """

    RAW_TURNS = {
        3: Image.Transpose.ROTATE_180,
        5: Image.Transpose.ROTATE_90,
        6: Image.Transpose.ROTATE_270,
    }
    """LibRaw's "flip" codes, and the turn that makes each picture upright."""

    CACHE_QUALITY = 95
    EXIF_TIME_FORMAT = "%Y:%m:%d %H:%M:%S"

    def __init__(self, cache: PreviewCache) -> None:
        """Create a reader.

        Args:
            cache: Where the previews of raw files are kept.
        """
        self._cache = cache

    def read(self, photo: Photo, max_side: int) -> PhotoData:
        """Read a photo's camera details and a shrunk copy of its pixels.

        Args:
            photo: The photo.
            max_side: Longest side of the returned pixels.

        Returns:
            The camera details and the pixels.

        Raises:
            PhotoReadError: When the file cannot be read.
        """
        image = self.open_upright(photo)
        info = self.info_of(image, photo)
        pixels = self.pixels_of(image, max_side)
        return PhotoData(info, pixels)

    def load_pixels(self, photo: Photo, max_side: int | None = None) -> np.ndarray:
        """Read a photo's upright pixels.

        Args:
            photo: The photo.
            max_side: Longest side of the returned pixels; None keeps the full size.

        Returns:
            RGB pixels, 8 bits per channel.

        Raises:
            PhotoReadError: When the file cannot be read.
        """
        image = self.open_upright(photo)
        return self.pixels_of(image, max_side)

    def open_upright(self, photo: Photo) -> Image.Image:
        """Open a photo as an upright Pillow image.

        Args:
            photo: The photo.

        Returns:
            The image, turned so that it is upright, with its camera details.

        Raises:
            PhotoReadError: When the file cannot be read.
        """
        if photo.is_raw:
            return self._open_raw(photo.path)
        return self._open_file(photo.path)

    def pixels_of(self, image: Image.Image, max_side: int | None) -> np.ndarray:
        """Turn a Pillow image into RGB pixels, shrunk when it is larger than asked.

        Args:
            image: The image. It is not changed.
            max_side: Longest side of the returned pixels; None keeps the full size.

        Returns:
            RGB pixels, 8 bits per channel.
        """
        rgb_image = image.convert("RGB")
        if max_side is not None:
            rgb_image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        return np.array(rgb_image)

    def info_of(self, image: Image.Image, photo: Photo) -> PhotoInfo:
        """Read the camera details from an image's EXIF data.

        When the photo has no time in its EXIF data, the file's change time is used.

        Args:
            image: The opened image.
            photo: The photo the image belongs to.

        Returns:
            The camera details.
        """
        exif = image.getexif()
        details = exif.get_ifd(ExifTags.IFD.Exif)
        taken_text = details.get(ExifTags.Base.DateTimeOriginal)
        if taken_text is None:
            taken_text = exif.get(ExifTags.Base.DateTime)
        taken_at = self._parse_time(taken_text)
        if taken_at is None:
            taken_at = self._file_time(photo.path)
        make = exif.get(ExifTags.Base.Make, "")
        model = exif.get(ExifTags.Base.Model, "")
        camera = self._camera_name(make, model)
        focal_value = details.get(ExifTags.Base.FocalLength)
        exposure_value = details.get(ExifTags.Base.ExposureTime)
        f_value = details.get(ExifTags.Base.FNumber)
        iso_value = details.get(ExifTags.Base.ISOSpeedRatings)
        focal_length = self._number(focal_value)
        exposure_time = self._number(exposure_value)
        f_number = self._number(f_value)
        iso_number = self._number(iso_value)
        iso = None if iso_number is None else round(iso_number)
        return PhotoInfo(taken_at, camera, focal_length, exposure_time, f_number, iso)

    def exif_bytes_of(self, image: Image.Image) -> bytes | None:
        """The image's EXIF data for a copy whose pixels are already upright.

        The orientation tag is set to "upright"; otherwise viewers would turn
        the picture a second time.

        Args:
            image: The opened image.

        Returns:
            The EXIF data, or None when there is none or it cannot be written.
        """
        exif = image.getexif()
        if len(exif) == 0:
            return None
        exif[ExifTags.Base.Orientation] = 1
        try:
            return exif.tobytes()
        except (ValueError, TypeError, KeyError, OverflowError):
            # Some maker notes cannot be written back; the copy then simply has no EXIF data.
            return None

    def _open_file(self, path: Path) -> Image.Image:
        """Open an ordinary image file and turn it upright from its EXIF orientation.

        Args:
            path: The file.

        Returns:
            The upright image.

        Raises:
            PhotoReadError: When the file cannot be opened.
        """
        try:
            image = Image.open(path)
            upright = ImageOps.exif_transpose(image)
        except (OSError, ValueError, SyntaxError) as error:
            raise PhotoReadError(f"Cannot open {path.name}: {error}") from error
        return upright

    def _open_raw(self, path: Path) -> Image.Image:
        """Open the upright preview of a raw file, making it first when it is not cached.

        Args:
            path: The raw file.

        Returns:
            The upright preview.

        Raises:
            PhotoReadError: When the raw file has no readable preview.
        """
        try:
            cached = self._cache.path_for(path)
        except OSError as error:
            raise PhotoReadError(f"Cannot read {path.name}: {error}") from error
        if cached.exists():
            return self._open_file(cached)
        image = self._extract_preview(path)
        self._save_preview(image, cached)
        return image

    def _extract_preview(self, path: Path) -> Image.Image:
        """Take the camera's JPEG picture out of a raw file and turn it upright.

        Args:
            path: The raw file.

        Returns:
            The upright picture, with the camera details of the raw file.

        Raises:
            PhotoReadError: When LibRaw cannot read the file or find a picture in it.
        """
        path_text = str(path)
        try:
            with rawpy.imread(path_text) as raw:
                thumb = raw.extract_thumb()
                flip = raw.sizes.flip
        except (rawpy.LibRawError, OSError) as error:
            raise PhotoReadError(f"Cannot read the preview in {path.name}: {error}") from error
        image = self._thumb_to_image(thumb)
        turn = self.RAW_TURNS.get(flip)
        if turn is None:
            return image
        return image.transpose(turn)

    def _thumb_to_image(self, thumb: rawpy.Thumbnail) -> Image.Image:
        """Turn the picture LibRaw found into a Pillow image.

        Args:
            thumb: The picture, as JPEG data or as pixels.

        Returns:
            The image.
        """
        if thumb.format == rawpy.ThumbFormat.JPEG:
            stream = io.BytesIO(thumb.data)
            image = Image.open(stream)
            image.load()
            return image
        return Image.fromarray(thumb.data)

    def _save_preview(self, image: Image.Image, target: Path) -> None:
        """Save an upright preview in the cache, with its camera details.

        The file is written under a temporary name first, so two threads
        saving the same preview never leave a half-written file.

        Args:
            image: The upright preview.
            target: Its file in the cache.
        """
        target.parent.mkdir(parents=True, exist_ok=True)
        unique = uuid.uuid4().hex
        temporary = target.with_name(f"{target.stem}.{unique}.part")
        exif_bytes = self.exif_bytes_of(image)
        options: dict = {"quality": self.CACHE_QUALITY}
        if exif_bytes:
            options["exif"] = exif_bytes
        rgb_image = image.convert("RGB")
        rgb_image.save(temporary, "JPEG", **options)
        os.replace(temporary, target)

    def _parse_time(self, text: object) -> datetime | None:
        """Read an EXIF time such as "2024:12:14 14:27:14".

        Args:
            text: The EXIF value.

        Returns:
            The time, or None when the value is missing or not a valid time.
        """
        if not isinstance(text, str):
            return None
        cleaned = text.strip("\x00 ")
        start = cleaned[:19]
        try:
            return datetime.strptime(start, self.EXIF_TIME_FORMAT)
        except ValueError:
            return None

    def _file_time(self, path: Path) -> datetime | None:
        """The time a file was last changed, used when the photo has no EXIF time.

        Args:
            path: The file.

        Returns:
            The time, or None when the file cannot be read.
        """
        try:
            status = path.stat()
        except OSError:
            return None
        return datetime.fromtimestamp(status.st_mtime)

    def _camera_name(self, make: object, model: object) -> str:
        """Join the camera maker and model, without saying the maker twice.

        Args:
            make: The EXIF maker, such as "Panasonic".
            model: The EXIF model, such as "DC-S5".

        Returns:
            Text such as "Panasonic DC-S5".
        """
        make_text = f"{make}".strip("\x00 ")
        model_text = f"{model}".strip("\x00 ")
        lowered_model = model_text.lower()
        lowered_make = make_text.lower()
        if lowered_model.startswith(lowered_make):
            return model_text
        joined = f"{make_text} {model_text}"
        return joined.strip()

    def _number(self, value: object) -> float | None:
        """Turn an EXIF number (often a fraction) into a float.

        Args:
            value: The EXIF value; a tuple uses its first item.

        Returns:
            The number, or None when it is missing or not a finite number.
        """
        if isinstance(value, tuple):
            value = value[0] if value else None
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError, ZeroDivisionError):
            return None
        if not math.isfinite(number):
            return None
        return number
