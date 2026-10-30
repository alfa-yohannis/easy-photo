"""Where the upright JPEG previews of raw files are kept."""

from __future__ import annotations

import hashlib
from pathlib import Path


class PreviewCache:
    """Keeps upright JPEG previews of raw files in the user's cache folder.

    A preview's file name comes from the raw file's path, size and change
    time, so a raw file that is replaced or edited gets a new preview. The
    folder can be deleted at any time; previews are made again when needed.
    """

    def __init__(self, folder: Path) -> None:
        """Create the cache.

        Args:
            folder: Folder for the preview files. It is created when the first preview is saved.
        """
        self._folder = folder

    @property
    def folder(self) -> Path:
        """Folder for the preview files."""
        return self._folder

    def path_for(self, source: Path) -> Path:
        """The preview file that belongs to a raw file.

        Args:
            source: The raw file.

        Returns:
            The path of its preview, whether or not the preview exists yet.
        """
        status = source.stat()
        resolved = source.resolve()
        key_text = f"{resolved}|{status.st_size}|{status.st_mtime_ns}"
        key_bytes = key_text.encode("utf-8")
        digest = hashlib.sha1(key_bytes, usedforsecurity=False).hexdigest()
        return self._folder / f"{digest[:24]}.jpg"
