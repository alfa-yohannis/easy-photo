"""Opening photo files, and showing them in the system's file manager."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


class FileLocations:
    """Opens files with their usual program, and shows them selected in the file manager.

    On Windows, Explorer opens with the file selected. On Linux, the file
    manager is asked over the session bus to show the file selected, through
    the freedesktop FileManager1 interface that Files, Dolphin, Nemo and
    Thunar offer; when no file manager answers, the folder opens instead.
    """

    FILE_MANAGER_SERVICE = "org.freedesktop.FileManager1"
    FILE_MANAGER_PATH = "/org/freedesktop/FileManager1"
    BUS_TIMEOUT_MS = 5000

    def open_file(self, path: Path) -> bool:
        """Open a file with the program the system uses for it.

        Args:
            path: The file.

        Returns:
            True when the system accepted the request.
        """
        path_text = str(path)
        url = QUrl.fromLocalFile(path_text)
        return QDesktopServices.openUrl(url)

    def show_in_folder(self, path: Path) -> bool:
        """Open the file's folder in the file manager, with the file selected where the system allows.

        Args:
            path: The file.

        Returns:
            True when the file manager was asked successfully.
        """
        if sys.platform == "win32":
            return self._show_in_explorer(path)
        if sys.platform == "darwin":
            return self._show_in_finder(path)
        if self._show_with_file_manager(path):
            return True
        return self._open_folder(path.parent)

    def _show_in_explorer(self, path: Path) -> bool:
        """Open Explorer with the file selected (Windows).

        Args:
            path: The file.

        Returns:
            True when Explorer was started.
        """
        # Explorer reads "/select," and the path as one argument, with the path in quotes.
        command = f'explorer /select,"{path}"'
        try:
            subprocess.Popen(command)
        except OSError:
            return self._open_folder(path.parent)
        return True

    def _show_in_finder(self, path: Path) -> bool:
        """Open Finder with the file selected (macOS).

        Args:
            path: The file.

        Returns:
            True when Finder was started.
        """
        path_text = str(path)
        try:
            subprocess.Popen(["open", "-R", path_text])
        except OSError:
            return self._open_folder(path.parent)
        return True

    def _show_with_file_manager(self, path: Path) -> bool:
        """Ask the file manager over the session bus to show the file selected (Linux).

        Args:
            path: The file.

        Returns:
            True when a file manager answered without an error.
        """
        try:
            # Imported here because PySide6 has no QtDBus module on Windows.
            from PySide6.QtDBus import QDBus, QDBusConnection, QDBusMessage
        except ImportError:
            return False
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            return False
        path_text = str(path)
        url = QUrl.fromLocalFile(path_text)
        uri = url.toString()
        message = QDBusMessage.createMethodCall(
            self.FILE_MANAGER_SERVICE, self.FILE_MANAGER_PATH, self.FILE_MANAGER_SERVICE, "ShowItems"
        )
        message.setArguments([[uri], ""])
        reply = bus.call(message, QDBus.CallMode.Block, self.BUS_TIMEOUT_MS)
        return reply.type() != QDBusMessage.MessageType.ErrorMessage

    def _open_folder(self, folder: Path) -> bool:
        """Open a folder in the file manager, without selecting anything.

        Args:
            folder: The folder.

        Returns:
            True when the system accepted the request.
        """
        folder_text = str(folder)
        url = QUrl.fromLocalFile(folder_text)
        return QDesktopServices.openUrl(url)
