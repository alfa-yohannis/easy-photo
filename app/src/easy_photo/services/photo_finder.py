"""Finds photo files in the folders and files the user picked."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from easy_photo.model.photo import FileKind, Photo


class PhotoFinder:
    """Finds the photo files in folders and file lists, each file once."""

    def __init__(self, include_subfolders: bool = True) -> None:
        """Create a finder.

        Args:
            include_subfolders: Also look inside the folders of a folder.
        """
        self._include_subfolders = include_subfolders

    def find(self, sources: Iterable[Path]) -> list[Photo]:
        """List the photos in the given folders and files.

        Hidden files, and files the app cannot read, are skipped. A file
        reached twice (for example through two sources) is listed once.

        Args:
            sources: Folders and files.

        Returns:
            The photos, folder by folder, in name order.
        """
        seen: set[Path] = set()
        photos: list[Photo] = []
        for source in sources:
            candidates = self._files_in(source)
            for path in candidates:
                kind = FileKind.of(path)
                if kind is None or path.name.startswith("."):
                    continue
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                photo = Photo(path, kind)
                photos.append(photo)
        return photos

    def _files_in(self, source: Path) -> list[Path]:
        """The files of a folder in name order, or the file itself.

        Args:
            source: A folder or a file.

        Returns:
            The files; an empty list when the source does not exist.
        """
        if source.is_file():
            return [source]
        if not source.is_dir():
            return []
        pattern = "**/*" if self._include_subfolders else "*"
        found = [path for path in source.glob(pattern) if path.is_file()]
        found.sort()
        return found
