"""An area that takes folders and photos dragged from the file manager."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from easy_photo.gui.style import AppStyle
from easy_photo.model.photo import IMAGE_EXTENSIONS, RAW_EXTENSIONS


class DropZone(QFrame):
    """An area for folders and photos dragged from the file manager, with buttons to browse for them."""

    paths_chosen = Signal(list)

    def __init__(self, style: AppStyle, parent: QWidget | None = None) -> None:
        """Create the area.

        Args:
            style: Applies the hover look.
            parent: Qt parent widget.
        """
        super().__init__(parent)
        self._style = style
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(160)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)
        title = QLabel("Drop folders or photos here")
        title.setObjectName("SectionTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("Raw files (RW2, CR3, NEF, ARW, DNG and more) and JPEG, PNG or TIFF images")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        folder_button = QPushButton("Add folder…")
        folder_button.clicked.connect(self._browse_folder)
        files_button = QPushButton("Add photos…")
        files_button.clicked.connect(self._browse_files)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(folder_button)
        buttons.addWidget(files_button)
        buttons.addStretch(1)
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addLayout(buttons)
        layout.addStretch(1)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept a drag that carries files or folders.

        Args:
            event: The drag event.
        """
        mime = event.mimeData()
        if mime.hasUrls():
            event.acceptProposedAction()
            self._set_hover(True)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        """Remove the hover look when the drag leaves.

        Args:
            event: The drag event.
        """
        self._set_hover(False)

    def dropEvent(self, event: QDropEvent) -> None:
        """Take the dropped files and folders.

        Args:
            event: The drop event.
        """
        self._set_hover(False)
        mime = event.mimeData()
        urls = mime.urls()
        paths: list[Path] = []
        for url in urls:
            if not url.isLocalFile():
                continue
            local = url.toLocalFile()
            path = Path(local)
            paths.append(path)
        if paths:
            event.acceptProposedAction()
            self.paths_chosen.emit(paths)

    def _browse_folder(self) -> None:
        """Let the user pick a folder."""
        folder = QFileDialog.getExistingDirectory(self, "Add a folder of photos")
        if folder:
            path = Path(folder)
            self.paths_chosen.emit([path])

    def _browse_files(self) -> None:
        """Let the user pick photo files."""
        file_filter = self.photo_filter()
        names, _chosen_filter = QFileDialog.getOpenFileNames(self, "Add photos", "", file_filter)
        paths = [Path(name) for name in names]
        if paths:
            self.paths_chosen.emit(paths)

    @staticmethod
    def photo_filter() -> str:
        """The file dialog filter for photo files.

        Returns:
            Text such as "Photos (*.jpg *.JPG ...);;All files (*)".
        """
        extensions = RAW_EXTENSIONS | IMAGE_EXTENSIONS
        return DropZone.file_filter("Photos", extensions)

    @staticmethod
    def file_filter(label: str, extensions: frozenset[str]) -> str:
        """A file dialog filter, in lower and upper case for case-sensitive systems.

        Args:
            label: What the files are, such as "Photos".
            extensions: The extensions, such as ".jpg".

        Returns:
            Text such as "Photos (*.jpg *.JPG ...);;All files (*)".
        """
        patterns: list[str] = []
        for extension in sorted(extensions):
            upper = extension.upper()
            patterns.append(f"*{extension}")
            patterns.append(f"*{upper}")
        joined = " ".join(patterns)
        return f"{label} ({joined});;All files (*)"

    def _set_hover(self, hover: bool) -> None:
        """Switch the hover look on or off.

        Args:
            hover: True while a drag is over the area.
        """
        self.setProperty("hover", hover)
        self._style.refresh(self)
