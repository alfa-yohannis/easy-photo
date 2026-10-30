"""Tests of opening photo files and showing them in the file manager, with stand-ins so no window opens."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from easy_photo.gui.file_locations import FileLocations


class UrlRecorder:
    """Stands in for ``QDesktopServices.openUrl``: remembers the paths instead of opening them."""

    def __init__(self) -> None:
        """Start with no paths."""
        self.paths: list[Path] = []

    def open_url(self, url: QUrl) -> bool:
        """Remember the path of a file address.

        Args:
            url: The address the app wanted to open.

        Returns:
            True, as if the system had opened it.
        """
        path_text = url.toLocalFile()
        path = Path(path_text)
        self.paths.append(path)
        return True


def no_file_manager(_locations: FileLocations, _path: Path) -> bool:
    """Stands in for the file manager request over the session bus, when no file manager answers.

    Args:
        _locations: The object the request belongs to (not used).
        _path: The file (not used).

    Returns:
        False, as when no file manager answered.
    """
    return False


def test_open_file_asks_the_system_for_the_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Opening a file hands its own address to the system.

    Args:
        monkeypatch: Puts the stand-in in place of the real call.
        tmp_path: A folder for the file.
    """
    recorder = UrlRecorder()
    monkeypatch.setattr(QDesktopServices, "openUrl", recorder.open_url)
    photo = tmp_path / "P1000001.RW2"
    locations = FileLocations()
    opened = locations.open_file(photo)
    assert opened
    assert recorder.paths == [photo]


@pytest.mark.skipif(sys.platform in ("win32", "darwin"), reason="Explorer and Finder select the file themselves")
def test_show_in_folder_opens_the_folder_when_no_file_manager_answers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without a file manager on the session bus, the photo's folder opens instead.

    Args:
        monkeypatch: Puts the stand-ins in place of the real calls.
        tmp_path: A folder for the file.
    """
    recorder = UrlRecorder()
    monkeypatch.setattr(QDesktopServices, "openUrl", recorder.open_url)
    monkeypatch.setattr(FileLocations, "_show_with_file_manager", no_file_manager)
    photo = tmp_path / "photos" / "P1000001.RW2"
    locations = FileLocations()
    shown = locations.show_in_folder(photo)
    assert shown
    assert recorder.paths == [photo.parent]
