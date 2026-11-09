"""Small pictures of raw photos as darktable develops them with their sidecars, kept in the cache folder."""

from __future__ import annotations

import hashlib
import os
import threading
import uuid
from pathlib import Path

import cv2
import numpy as np

from easy_photo.model.photo import Photo
from easy_photo.refinement.light import LinearLight
from easy_photo.services.darktable import DarktableRenderer


class DevelopedThumbnails:
    """Develops small pictures of raw photos with darktable-cli, and keeps them in the cache folder.

    The preview a camera stores inside a raw file knows nothing of the
    darktable edit in the photo's sidecar. These pictures show it:
    darktable-cli develops the raw file with its own sidecar, or with
    darktable's defaults when it has none, as the export does. That takes one
    to three seconds a photo, so each picture is kept. It is found again as
    long as the raw file and its sidecar stay the same; a changed sidecar
    needs a new picture, and the photo's older picture is then deleted. The
    folder can be deleted at any time.
    """

    SIDE = 320
    """Longest side of the pictures, the size of the thumbnails made from the camera's preview."""

    QUALITY = 92
    """JPEG quality of the kept pictures."""

    NO_SIDECAR = "no sidecar"
    """Stands for the sidecar in the key of a photo that has none."""

    KEY_LENGTH = 20
    """Characters of each hash used in a picture's file name."""

    def __init__(self, darktable: DarktableRenderer, folder: Path) -> None:
        """Create the pictures' keeper.

        Args:
            darktable: Develops the raw files.
            folder: Folder for the pictures. It is created when the first picture is kept.
        """
        self._darktable = darktable
        self._folder = folder
        self._light = LinearLight()
        self._one_at_a_time = threading.Lock()

    @property
    def available(self) -> bool:
        """True when darktable-cli was found, so pictures can be developed."""
        return self._darktable.available

    @property
    def folder(self) -> Path:
        """Folder for the pictures."""
        return self._folder

    def kept(self, photo: Photo) -> np.ndarray | None:
        """The picture kept for a photo as its raw file and sidecar are now. Quick: darktable does not run.

        Args:
            photo: The photo.

        Returns:
            RGB pixels (8 bits per channel), or None when no picture fits the
            photo as it is now, or the photo is not a raw file.
        """
        if not photo.is_raw:
            return None
        try:
            path = self.path_for(photo)
        except OSError:
            return None
        return self._read(path)

    def develop(self, photo: Photo) -> np.ndarray:
        """The picture of a raw photo as darktable develops it now: the kept one, or a new one that is then kept.

        Photos are developed one at a time, so a photo asked for twice is
        developed once and found the second time.

        Args:
            photo: The raw photo.

        Returns:
            RGB pixels (8 bits per channel), at most :attr:`SIDE` pixels on the longer side.

        Raises:
            DarktableError: When darktable-cli is missing or fails.
            OSError: When the raw file or its sidecar cannot be read.
        """
        with self._one_at_a_time:
            path = self.path_for(photo)
            kept = self._read(path)
            if kept is not None:
                return kept
            values = self._darktable.render(photo.path, None, self.SIDE, False)
            pixels = self._light.to_8bit(values)
            # The sidecar may have changed while darktable worked: such a picture is shown but not kept.
            after = self.path_for(photo)
            if after == path:
                self._keep(pixels, path)
            return pixels

    def path_for(self, photo: Photo) -> Path:
        """The file of a photo's picture, for its raw file and sidecar as they are now.

        The name starts with a hash of the raw file's path, which all pictures
        of the photo share, and ends with a hash of the raw file's size and
        time and of the sidecar's bytes.

        Args:
            photo: The raw photo.

        Returns:
            The file, whether or not it exists.

        Raises:
            OSError: When the raw file or its sidecar cannot be read.
        """
        photo_key = self._photo_key(photo)
        status = photo.path.stat()
        sidecar_key = self._sidecar_key(photo)
        state_text = f"{status.st_size}|{status.st_mtime_ns}|{sidecar_key}|{self.SIDE}"
        state_key = self._hash_of_text(state_text)
        return self._folder / f"{photo_key}-{state_key}.jpg"

    def _photo_key(self, photo: Photo) -> str:
        """The part of a picture's file name that all pictures of a photo share.

        The path is taken as the project has it, without following links,
        because darktable-cli reads the sidecar next to that path.

        Args:
            photo: The photo.

        Returns:
            A hash of the raw file's full path.
        """
        full_path = photo.path.absolute()
        path_text = str(full_path)
        return self._hash_of_text(path_text)

    def _sidecar_key(self, photo: Photo) -> str:
        """A hash of the bytes of a photo's sidecar, so any change to the edit gives a new key.

        Args:
            photo: The raw photo.

        Returns:
            The hash, or :attr:`NO_SIDECAR` when the photo has no sidecar.

        Raises:
            OSError: When the sidecar cannot be read.
        """
        sidecar = self._darktable.sidecar_for(photo.path)
        if sidecar is None:
            return self.NO_SIDECAR
        data = sidecar.read_bytes()
        digest = hashlib.sha1(data, usedforsecurity=False)
        return digest.hexdigest()

    def _hash_of_text(self, text: str) -> str:
        """A short hash of a text, for file names.

        Args:
            text: The text.

        Returns:
            The first :attr:`KEY_LENGTH` characters of its SHA-1 hash.
        """
        data = text.encode("utf-8")
        digest = hashlib.sha1(data, usedforsecurity=False)
        hex_text = digest.hexdigest()
        return hex_text[: self.KEY_LENGTH]

    def _read(self, path: Path) -> np.ndarray | None:
        """Read a kept picture.

        The file is read into memory and decoded there, so folder names with
        any characters work on every system.

        Args:
            path: The picture's file.

        Returns:
            RGB pixels, or None when the file is not there or cannot be decoded.
        """
        try:
            data = path.read_bytes()
        except OSError:
            return None
        buffer = np.frombuffer(data, dtype=np.uint8)
        decoded = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        if decoded is None:
            return None
        return cv2.cvtColor(decoded, cv2.COLOR_BGR2RGB)

    def _keep(self, pixels: np.ndarray, path: Path) -> None:
        """Keep a picture, and delete the older pictures of the same photo.

        The file is written under a temporary name and then renamed, so a
        reader never finds half a picture. A picture that cannot be written
        is not kept, which only means it is developed again next time.

        Args:
            pixels: RGB pixels (8 bits per channel).
            path: The picture's file, from :meth:`path_for`.
        """
        blue_green_red = cv2.cvtColor(pixels, cv2.COLOR_RGB2BGR)
        parameters = [cv2.IMWRITE_JPEG_QUALITY, self.QUALITY]
        encoded_ok, encoded = cv2.imencode(".jpg", blue_green_red, parameters)
        if not encoded_ok:
            return
        data = encoded.tobytes()
        unique = uuid.uuid4().hex
        temporary = path.with_name(f".{path.name}.{unique}.part")
        try:
            self._folder.mkdir(parents=True, exist_ok=True)
            temporary.write_bytes(data)
            os.replace(temporary, path)
        except OSError:
            temporary.unlink(missing_ok=True)
            return
        self._forget_older(path)

    def _forget_older(self, path: Path) -> None:
        """Delete the pictures a photo had for its earlier sidecars.

        Args:
            path: The photo's newest picture, which stays.
        """
        photo_key, _separator, _state_key = path.stem.partition("-")
        older = self._folder.glob(f"{photo_key}-*.jpg")
        for picture in older:
            if picture == path:
                continue
            try:
                picture.unlink()
            except OSError:
                continue
