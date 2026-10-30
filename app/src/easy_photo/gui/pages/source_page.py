"""Step 1: the user adds folders and photos, and the app reads and measures them."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QListWidget, QListWidgetItem, QSlider, QVBoxLayout, QWidget

from easy_photo.gui.controller import ProjectController
from easy_photo.gui.pages.base_page import WorkflowPage
from easy_photo.gui.photo_model import PhotoListModel
from easy_photo.gui.style import AppStyle
from easy_photo.gui.widgets.drop_zone import DropZone
from easy_photo.gui.widgets.photo_grid import PhotoGrid
from easy_photo.wording import count_text


class SourcePage(WorkflowPage):
    """Step 1: the user adds folders and photos; the app reads and measures every photo."""

    def __init__(self, controller: ProjectController, style: AppStyle, parent: QWidget | None = None) -> None:
        """Create the page.

        Args:
            controller: Runs the work and holds the project.
            style: Gives the theme colors.
            parent: Qt parent widget.
        """
        super().__init__(
            controller,
            style,
            "Source",
            "Add the folders or photos you want to go through. For raw files the app reads the picture the "
            "camera stored inside, so this is quick, and it measures every photo for the next steps.",
            parent,
        )
        self._model = PhotoListModel(controller, self)
        content = QWidget(self)
        layout = QHBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        left = self._make_sources_column(content)
        right = self._make_photos_column(content)
        layout.addWidget(left)
        layout.addWidget(right, 1)
        self.set_content(content)
        controller.project_opened.connect(self.on_shown)
        controller.sources_changed.connect(self._refresh_sources)
        controller.photos_changed.connect(self._refresh_photos)
        controller.photo_updated.connect(self._on_photo_updated)
        controller.analysis_changed.connect(self._on_analysis_changed)

    def is_ready(self) -> bool:
        """The user can go on once at least one photo is measured.

        Returns:
            True when a photo is measured.
        """
        project = self._controller.project
        return project is not None and project.analyzed_count > 0

    def status_text(self) -> str:
        """The number of photos.

        Returns:
            Text such as "332 photos".
        """
        project = self._controller.project
        if project is None or project.photo_count == 0:
            return "Add photos"
        return count_text(project.photo_count, "photo")

    def on_shown(self) -> None:
        """Show the current sources and photos."""
        self._refresh_sources()
        self._refresh_photos()

    def _make_sources_column(self, parent: QWidget) -> QWidget:
        """The left column: the drop zone and the list of sources.

        Args:
            parent: The content widget.

        Returns:
            The column.
        """
        column = QWidget(parent)
        column.setFixedWidth(340)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        drop_zone = DropZone(self._style, column)
        drop_zone.paths_chosen.connect(self._controller.add_sources)
        sources_title = self.make_label("Sources", "SectionTitle")
        self._sources_list = QListWidget(column)
        self._sources_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._sources_list.setWordWrap(True)
        remove_button = self.make_button("Remove selected", self._remove_selected)
        layout.addWidget(drop_zone)
        layout.addWidget(sources_title)
        layout.addWidget(self._sources_list, 1)
        layout.addWidget(remove_button)
        return column

    def _make_photos_column(self, parent: QWidget) -> QWidget:
        """The right column: a summary line, a tile size slider and the photo grid.

        Args:
            parent: The content widget.

        Returns:
            The column.
        """
        column = QWidget(parent)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._summary = self.make_label("", "Muted")
        self._grid = PhotoGrid(self._model, self._style, column)
        self._grid.set_show_badges(False)
        size_label = self.make_label("Tile size", "Muted")
        size_slider = QSlider(Qt.Orientation.Horizontal, column)
        size_slider.setRange(140, 380)
        size_slider.setValue(210)
        size_slider.setFixedWidth(160)
        size_slider.valueChanged.connect(self._grid.set_tile_width)
        top = QHBoxLayout()
        top.addWidget(self._summary, 1)
        top.addWidget(size_label)
        top.addWidget(size_slider)
        layout.addLayout(top)
        layout.addWidget(self._grid, 1)
        return column

    def _refresh_sources(self) -> None:
        """Show the project's sources."""
        self._sources_list.clear()
        project = self._controller.project
        if project is None:
            return
        for source in project.sources:
            text = str(source)
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, text)
            self._sources_list.addItem(item)
        self.readiness_changed.emit()

    def _refresh_photos(self) -> None:
        """Show all photos of the project."""
        project = self._controller.project
        photo_ids = [] if project is None else [photo.id for photo in project.photos]
        self._model.set_photo_ids(photo_ids)
        self._refresh_summary()

    def _on_photo_updated(self, photo_id: str) -> None:
        """Redraw a photo that was measured.

        Args:
            photo_id: Id of the photo.
        """
        self._model.refresh_photo(photo_id)
        self._refresh_summary()

    def _on_analysis_changed(self) -> None:
        """Update the summary and the sidebar after the measuring finished."""
        self._refresh_summary()
        self.readiness_changed.emit()

    def _refresh_summary(self) -> None:
        """Write how many photos were found and measured."""
        project = self._controller.project
        if project is None or project.photo_count == 0:
            self._summary.setText("No photos yet. Add a folder or drop photos on the left.")
            return
        found = project.photo_count
        measured = project.analyzed_count
        found_text = count_text(found, "photo")
        if measured < found:
            self._summary.setText(f"{found_text} found, {measured} measured so far.")
        else:
            self._summary.setText(f"{found_text} found and measured.")

    def _remove_selected(self) -> None:
        """Remove the selected sources from the project."""
        items = self._sources_list.selectedItems()
        for item in items:
            text = item.data(Qt.ItemDataRole.UserRole)
            path = Path(text)
            self._controller.remove_source(path)
