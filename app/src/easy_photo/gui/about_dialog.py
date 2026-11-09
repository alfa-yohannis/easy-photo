"""The About box: what easy-photo is, its version and license, what it works with, and where it keeps its files."""

from __future__ import annotations

import html
import platform
from importlib import metadata
from pathlib import Path

from PySide6.QtCore import QSize, Qt, qVersion
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from easy_photo import APP_NAME, APP_VERSION
from easy_photo.gui.app_icon import AppIcon
from easy_photo.gui.controller import ProjectController
from easy_photo.settings import AppFolders


class AboutDialog(QDialog):
    """Shows what easy-photo is, its version and license, the programs it works with, and its folders.

    The programs are the ones the app found on this computer, so the box
    also tells whether darktable and Claude Code are there. All text can be
    selected and copied, for example into a bug report.
    """

    REPOSITORY_URL = "https://github.com/alfa-yohannis/easy-photo"
    REPOSITORY_TEXT = "github.com/alfa-yohannis/easy-photo"
    ICON_SIDE = 96

    LIBRARIES = (
        ("PySide6", "PySide6"),
        ("OpenCV", "opencv-python-headless"),
        ("rawpy", "rawpy"),
        ("NumPy", "numpy"),
        ("Pillow", "Pillow"),
    )
    """The libraries whose versions are shown, as (name shown, package name) pairs."""

    DESCRIPTION = (
        "Sets aside blurred, unclear, too dark and too bright photos, groups the rest, and refines each "
        "group the way you choose: from your earlier picks, examples from the internet, your own examples, "
        "darktable edits or words you type. Raw files are developed with darktable."
    )

    def __init__(self, controller: ProjectController, folders: AppFolders, parent: QWidget | None = None) -> None:
        """Create the box.

        Args:
            controller: Knows which programs the app found.
            folders: Where the app keeps its settings, caches and lasting files.
            parent: Qt parent widget.
        """
        super().__init__(parent)
        self._controller = controller
        self._folders = folders
        self.setWindowTitle(f"About {APP_NAME}")
        self.setMinimumWidth(640)
        icon_label = self._make_icon()
        text_column = self._make_text_column()
        top = QHBoxLayout()
        top.setSpacing(20)
        top.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)
        top.addLayout(text_column, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 16)
        layout.setSpacing(16)
        layout.addLayout(top)
        layout.addWidget(buttons)
        self._fit_to_content()

    def label_texts(self) -> list[str]:
        """The texts of the box's labels, in order, for tests.

        Returns:
            The texts; rich text keeps its tags.
        """
        labels = self.findChildren(QLabel)
        return [label.text() for label in labels]

    def _fit_to_content(self) -> None:
        """Make the box wide enough for its longest line, and tall enough for the wrapped description at that width.

        Qt's own fitting keeps a window within two thirds of the screen,
        which cuts lines off on small screens such as 1366 by 768.
        """
        layout = self.layout()
        layout.activate()
        hint = layout.totalSizeHint()
        hint_width = hint.width()
        minimum_width = self.minimumWidth()
        width = max(hint_width, minimum_width)
        height = layout.totalHeightForWidth(width)
        if height < 0:
            height = hint.height()
        self.resize(width, height)

    def _make_icon(self) -> QLabel:
        """The app's icon, large.

        Returns:
            A label that shows the icon.
        """
        icon = AppIcon.icon()
        size = QSize(self.ICON_SIDE, self.ICON_SIDE)
        pixmap = icon.pixmap(size)
        label = QLabel(self)
        label.setPixmap(pixmap)
        return label

    def _make_text_column(self) -> QVBoxLayout:
        """The name, version, description, programs, folders and license, one below the other.

        Returns:
            The column.
        """
        title = QLabel(APP_NAME, self)
        title.setObjectName("AppTitle")
        version = QLabel(f"Version {APP_VERSION}", self)
        version.setObjectName("Muted")
        description = self._text_label(self.DESCRIPTION, True)
        steps = self._text_label("Source → Filter → Group → References → Refine → Export", False)
        steps.setObjectName("Muted")
        programs_title = self._section_label("Works with")
        programs_text = self._programs_html()
        programs = self._text_label(programs_text, False)
        folders_title = self._section_label("Folders")
        folders_text = self._folders_html()
        folders = self._text_label(folders_text, False)
        license_text = f'MIT License<br>Source code and documentation: <a href="{self.REPOSITORY_URL}">{self.REPOSITORY_TEXT}</a>'
        license_label = self._text_label(license_text, False)
        column = QVBoxLayout()
        column.setSpacing(6)
        column.addWidget(title)
        column.addWidget(version)
        column.addSpacing(8)
        column.addWidget(description)
        column.addWidget(steps)
        column.addSpacing(8)
        column.addWidget(programs_title)
        column.addWidget(programs)
        column.addSpacing(8)
        column.addWidget(folders_title)
        column.addWidget(folders)
        column.addSpacing(8)
        column.addWidget(license_label)
        column.addStretch(1)
        return column

    def _text_label(self, text: str, wrap: bool) -> QLabel:
        """A label whose text can be selected, and whose links open in the browser.

        Args:
            text: Plain or rich text.
            wrap: Wrap long lines; lines of paths and versions do not wrap, so the box gets as wide as they are.

        Returns:
            The label.
        """
        label = QLabel(text, self)
        label.setWordWrap(wrap)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        label.setOpenExternalLinks(True)
        return label

    def _section_label(self, text: str) -> QLabel:
        """A small heading.

        Args:
            text: The heading.

        Returns:
            The label.
        """
        label = QLabel(text, self)
        label.setObjectName("SectionTitle")
        return label

    def _programs_html(self) -> str:
        """The programs the app found, and the versions of its libraries.

        Returns:
            One line per program, then one line with the libraries, as rich text.
        """
        services = self._controller.services
        darktable_cli = services.darktable.executable
        darktable = services.darktable_launcher.executable
        claude = self._controller.claude_program
        lines = [
            self._program_line("darktable-cli", darktable_cli, "raw files are exported from the camera's small preview"),
            self._program_line("darktable", darktable, "photos cannot be opened in darktable from the app"),
            self._program_line("Claude Code", claude, "only the app's own phrases are read"),
        ]
        python_version = platform.python_version()
        qt_version = qVersion()
        lines.append(f"Python {python_version}, Qt {qt_version}")
        library_parts = [f"{name} {self._version_of(package)}" for name, package in self.LIBRARIES]
        libraries = ", ".join(library_parts)
        lines.append(libraries)
        return "<br>".join(lines)

    def _program_line(self, name: str, path: Path | None, missing: str) -> str:
        """Say where a program is, or what its absence means.

        Args:
            name: The program's name.
            path: Where the app found it, or None.
            missing: What the app does without it.

        Returns:
            One line of rich text.
        """
        if path is None:
            return f"{name}: not found, so {missing}"
        path_text = str(path)
        escaped = html.escape(path_text)
        return f"{name}: {escaped}"

    def _folders_html(self) -> str:
        """Where the app keeps its settings, its caches and its lasting files.

        Returns:
            One line per folder, as rich text.
        """
        folders = (
            ("Settings", self._folders.config, "the app's own settings and recent projects"),
            ("Cache", self._folders.cache, "raw previews and developed pictures; safe to delete"),
            ("Data", self._folders.data, "the history of your picks and the face models"),
        )
        lines: list[str] = []
        for name, path, note in folders:
            path_text = str(path)
            escaped = html.escape(path_text)
            lines.append(f"{name}: {escaped} ({note})")
        return "<br>".join(lines)

    def _version_of(self, package: str) -> str:
        """The installed version of a Python package.

        Args:
            package: The package's name, such as "rawpy".

        Returns:
            The version, or "not installed".
        """
        try:
            return metadata.version(package)
        except metadata.PackageNotFoundError:
            return "not installed"
