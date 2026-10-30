"""The first screen: make a new project or open one."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from easy_photo import APP_NAME
from easy_photo.services.manifest import ProjectManifest


class StartPage(QWidget):
    """The screen shown when no project is open: new project, open project, and the recent projects."""

    new_requested = Signal()
    open_requested = Signal()
    recent_chosen = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create the screen.

        Args:
            parent: Qt parent widget.
        """
        super().__init__(parent)
        self.setObjectName("StartPage")
        column = QWidget(self)
        column.setMaximumWidth(640)
        layout = QVBoxLayout(column)
        layout.setSpacing(12)
        title = QLabel(APP_NAME)
        title.setObjectName("StartTitle")
        subtitle = QLabel("Filter, group and refine your photos, guided by your own picks and examples.")
        subtitle.setObjectName("PageHint")
        subtitle.setWordWrap(True)
        new_button = QPushButton("New project…")
        new_button.setProperty("primary", True)
        new_button.clicked.connect(self.new_requested)
        open_button = QPushButton("Open project…")
        open_button.clicked.connect(self.open_requested)
        buttons = QHBoxLayout()
        buttons.addWidget(new_button)
        buttons.addWidget(open_button)
        buttons.addStretch(1)
        recent_title = QLabel("Recent projects")
        recent_title.setObjectName("SectionTitle")
        self._recent_list = QListWidget(column)
        self._recent_list.setMinimumHeight(220)
        self._recent_list.itemActivated.connect(self._on_recent_activated)
        self._empty_label = QLabel("No recent projects yet.")
        self._empty_label.setObjectName("Muted")
        note = QLabel(
            f"A project is a folder with a {ProjectManifest.FILE_NAME} file in it. "
            "It remembers your sources, choices and options. One project is open at a time."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(10)
        layout.addLayout(buttons)
        layout.addSpacing(18)
        layout.addWidget(recent_title)
        layout.addWidget(self._recent_list)
        layout.addWidget(self._empty_label)
        layout.addWidget(note)
        middle = QHBoxLayout()
        middle.addStretch(1)
        middle.addWidget(column, 3)
        middle.addStretch(1)
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        outer.addLayout(middle)
        outer.addStretch(2)

    def set_recent(self, manifests: Sequence[Path]) -> None:
        """Show the recent projects.

        Args:
            manifests: Their manifest files, the latest first.
        """
        self._recent_list.clear()
        for manifest in manifests:
            folder = manifest.parent
            text = f"{folder.name}\n{folder}"
            item = QListWidgetItem(text)
            manifest_text = str(manifest)
            item.setData(Qt.ItemDataRole.UserRole, manifest_text)
            self._recent_list.addItem(item)
        has_recent = bool(manifests)
        self._recent_list.setVisible(has_recent)
        self._empty_label.setVisible(not has_recent)

    def _on_recent_activated(self, item: QListWidgetItem) -> None:
        """Open a recent project on double click or Enter.

        Args:
            item: The chosen list item.
        """
        manifest_text = item.data(Qt.ItemDataRole.UserRole)
        manifest = Path(manifest_text)
        self.recent_chosen.emit(manifest)
