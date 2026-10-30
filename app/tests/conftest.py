"""Shared test setup: Qt runs without a screen, and a helper writes small test photos."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import ExifTags, Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class PhotoMaker:
    """Writes small JPEG test photos with a chosen look and an EXIF time.

    A "scene" is a tinted picture with sharp blocks and fine lines; the tint
    tells scenes apart, and the seed makes each photo of a scene a little
    different.
    """

    WIDTH = 640
    HEIGHT = 480
    TIME_FORMAT = "%Y:%m:%d %H:%M:%S"

    def __init__(self, folder: Path) -> None:
        """Create a maker that writes into a folder.

        Args:
            folder: Where the photos go.
        """
        self._folder = folder
        self._folder.mkdir(parents=True, exist_ok=True)

    def scene(self, tint: tuple[float, float, float], seed: int) -> np.ndarray:
        """Make a sharp, detailed test picture.

        Args:
            tint: Color of the scene as RGB factors from 0 to 1.
            seed: Makes each picture a little different.

        Returns:
            RGB pixels, 8 bits per channel.
        """
        generator = np.random.default_rng(seed)
        blocks = generator.random((12, 16))
        block_shape = np.ones((40, 40))
        large = np.kron(blocks, block_shape)
        rows = np.arange(self.HEIGHT)
        stripes = (rows % 6 < 3).astype(np.float64)
        lines = stripes[:, np.newaxis] * 0.25
        grey = 0.25 + 0.5 * large + lines
        tint_array = np.array(tint)
        color = grey[..., np.newaxis] * tint_array
        scaled = np.clip(color * 255.0, 0, 255)
        return scaled.astype(np.uint8)

    def blurred(self, pixels: np.ndarray) -> np.ndarray:
        """Blur a picture so much that no part is sharp.

        Args:
            pixels: The picture.

        Returns:
            The blurred picture.
        """
        return cv2.GaussianBlur(pixels, (0, 0), 9)

    def write(self, name: str, pixels: np.ndarray, taken_at: datetime) -> Path:
        """Save a picture as a JPEG file with an EXIF time and camera.

        Args:
            name: File name without extension.
            pixels: The picture.
            taken_at: The time to write into the EXIF data.

        Returns:
            The file.
        """
        image = Image.fromarray(pixels)
        exif = Image.Exif()
        exif[ExifTags.Base.DateTime] = taken_at.strftime(self.TIME_FORMAT)
        exif[ExifTags.Base.Model] = "Test Camera"
        exif_bytes = exif.tobytes()
        path = self._folder / f"{name}.jpg"
        image.save(path, "JPEG", quality=92, exif=exif_bytes)
        return path


@pytest.fixture
def photo_maker(tmp_path: Path) -> PhotoMaker:
    """A photo maker that writes into a fresh folder.

    Args:
        tmp_path: pytest's temporary folder for the test.

    Returns:
        The maker.
    """
    folder = tmp_path / "photos"
    return PhotoMaker(folder)
