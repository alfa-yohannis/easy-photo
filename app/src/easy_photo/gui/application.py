"""Starting the app: the Qt application, the services, the controller and the window."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

import cv2
from PySide6.QtWidgets import QApplication

from easy_photo import APP_NAME, APP_VERSION
from easy_photo.gui.controller import ProjectController
from easy_photo.gui.main_window import MainWindow
from easy_photo.gui.style import AppStyle
from easy_photo.services.app_services import AppServices
from easy_photo.settings import AppFolders, SettingsStore


class EasyPhotoApp:
    """Makes the Qt application, the services, the controller and the main window, and runs them.

    This is the one place where the parts of the app are made and connected.
    """

    OPENCV_THREADS = 2
    """OpenCV may use two threads, which keeps the computer usable during long jobs."""

    def __init__(self, argv: Sequence[str], folders: AppFolders | None = None) -> None:
        """Make all parts of the app.

        Args:
            argv: The command line; a path after the program name opens that project.
            folders: Where settings and caches go; the user's standard folders when not given.
        """
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        cv2.setNumThreads(self.OPENCV_THREADS)
        arguments = list(argv)
        existing = QApplication.instance()
        self._qt_app = existing if existing is not None else QApplication(arguments)
        self._qt_app.setApplicationName(APP_NAME)
        self._qt_app.setApplicationDisplayName(APP_NAME)
        self._qt_app.setApplicationVersion(APP_VERSION)
        self._folders = folders if folders is not None else AppFolders()
        self._settings_store = SettingsStore(self._folders.config)
        self._settings = self._settings_store.load()
        self._style = AppStyle()
        self._style.apply_to(self._qt_app)
        self._services = AppServices.create(self._settings, self._folders)
        self._controller = ProjectController(self._services, self._settings, self._settings_store)
        self._window = MainWindow(self._controller, self._style)
        self._project_to_open = Path(arguments[1]) if len(arguments) > 1 else None

    @property
    def controller(self) -> ProjectController:
        """The controller, for tests."""
        return self._controller

    @property
    def window(self) -> MainWindow:
        """The main window, for tests."""
        return self._window

    def run(self) -> int:
        """Show the window and run until it is closed.

        Returns:
            The exit code of the Qt event loop.
        """
        self._window.show()
        if self._project_to_open is not None:
            self._controller.open_project(self._project_to_open)
        return self._qt_app.exec()
