"""Photos found in the user's folders, and the camera details read from them."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

RAW_EXTENSIONS = frozenset(
    {".rw2", ".cr2", ".cr3", ".nef", ".nrw", ".arw", ".orf", ".raf", ".dng", ".pef", ".srw", ".rwl"}
)
"""Extensions of camera raw files. They are read with LibRaw, through the rawpy package."""

IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"})
"""Extensions of ordinary image files. They are read with Pillow."""


class FileKind(Enum):
    """Whether a photo file is a camera raw file or an ordinary image."""

    RAW = "raw"
    IMAGE = "image"

    @classmethod
    def of(cls, path: Path) -> FileKind | None:
        """Tell the kind of a file from its extension.

        Args:
            path: The file to look at.

        Returns:
            The kind of file, or None when the app cannot read this type of file.
        """
        suffix = path.suffix.lower()
        if suffix in RAW_EXTENSIONS:
            return cls.RAW
        if suffix in IMAGE_EXTENSIONS:
            return cls.IMAGE
        return None


@dataclass(frozen=True)
class PhotoInfo:
    """Camera details of a photo. Any of them can be missing."""

    taken_at: datetime | None = None
    camera: str = ""

    focal_length: float | None = None
    """Focal length in millimetres."""

    exposure_time: float | None = None
    """Shutter time in seconds."""

    f_number: float | None = None
    iso: int | None = None

    def exposure_text(self) -> str:
        """Describe the exposure the way photographers write it.

        Returns:
            Text such as "1/500 s   f/5.6   ISO 200   35 mm", or an empty text
            when nothing is known.
        """
        parts: list[str] = []
        if self.exposure_time:
            shutter = self._shutter_text()
            parts.append(shutter)
        if self.f_number:
            parts.append(f"f/{self.f_number:g}")
        if self.iso:
            parts.append(f"ISO {self.iso}")
        if self.focal_length:
            parts.append(f"{self.focal_length:g} mm")
        return "   ".join(parts)

    def _shutter_text(self) -> str:
        """Write the shutter time, as a fraction when it is shorter than a second.

        Returns:
            Text such as "1/250 s" or "2 s".
        """
        if self.exposure_time >= 1:
            return f"{self.exposure_time:g} s"
        denominator = 1 / self.exposure_time
        rounded = round(denominator)
        return f"1/{rounded} s"


class Photo:
    """One photo file from the user's sources.

    A photo is known by its file path. The scan step fills in its camera
    details. The results of later steps are kept in the
    :class:`~easy_photo.model.project.Project`, under the photo's id.
    """

    def __init__(self, path: Path, kind: FileKind) -> None:
        """Create a photo for a file.

        Args:
            path: The photo file.
            kind: Whether the file is a raw file or an ordinary image.
        """
        self._path = path
        self._kind = kind
        self._info = PhotoInfo()

    @property
    def id(self) -> str:
        """A unique text id: the full path of the file."""
        return str(self._path)

    @property
    def path(self) -> Path:
        """The photo file."""
        return self._path

    @property
    def name(self) -> str:
        """The file name, such as "P1199075.RW2"."""
        return self._path.name

    @property
    def stem(self) -> str:
        """The file name without its extension, such as "P1199075"."""
        return self._path.stem

    @property
    def kind(self) -> FileKind:
        """Whether the file is a raw file or an ordinary image."""
        return self._kind

    @property
    def is_raw(self) -> bool:
        """True for camera raw files."""
        return self._kind is FileKind.RAW

    @property
    def info(self) -> PhotoInfo:
        """The camera details read by the scan step."""
        return self._info

    @info.setter
    def info(self, info: PhotoInfo) -> None:
        """Store the camera details read by the scan step.

        Args:
            info: The camera details.
        """
        self._info = info

    def sort_key(self) -> tuple[datetime, str]:
        """Key that sorts photos by the time they were taken, then by file name.

        Returns:
            A tuple of the time (the earliest possible time when unknown) and the name.
        """
        taken_at = self._info.taken_at or datetime.min
        return (taken_at, self.name)
