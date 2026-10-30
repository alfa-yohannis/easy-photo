"""Step 6: every kept photo is developed, refined with its group's pick, and written as a JPEG file."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from easy_photo.gui.controller import ProjectController
from easy_photo.gui.file_locations import FileLocations
from easy_photo.gui.pages.base_page import WorkflowPage
from easy_photo.gui.style import AppStyle
from easy_photo.gui.widgets.card import Card
from easy_photo.services.exporter import ExportResult
from easy_photo.settings import ExportSettings
from easy_photo.wording import count_text


class ExportPage(WorkflowPage):
    """Step 6: the finished photos are written into a folder, never over an existing file."""

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
            "Export",
            "Each kept photo is developed, refined with the option picked for its group, and written as a JPEG "
            "file. A file that already exists is kept and skipped, unless you tick Overwrite.",
            parent,
        )
        self._written = 0
        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        options = self._make_options_card()
        self._summary = self.make_label("", "Muted")
        self._summary.setWordWrap(True)
        export_button = self.make_button("Export", self._export, primary=True)
        open_button = self.make_button("Open the folder", self._open_folder)
        buttons = QHBoxLayout()
        buttons.addWidget(export_button)
        buttons.addWidget(open_button)
        buttons.addStretch(1)
        results_title = self.make_label("Results", "SectionTitle")
        self._results = QListWidget(content)
        self._results.setToolTip("Double-click a photo to show it in its folder; right-click to open it.")
        self._results.itemDoubleClicked.connect(self._show_result_in_folder)
        self._results.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._results.customContextMenuRequested.connect(self._show_result_menu)
        self._locations = FileLocations()
        layout.addWidget(options)
        layout.addWidget(self._summary)
        layout.addLayout(buttons)
        layout.addWidget(results_title)
        layout.addWidget(self._results, 1)
        self.set_content(content)
        controller.project_opened.connect(self.on_shown)
        controller.choices_changed.connect(self._refresh_summary)
        controller.groups_changed.connect(self._refresh_summary)
        controller.export_finished.connect(self._show_results)

    def is_done(self) -> bool:
        """The step is finished once an export has written photos.

        Returns:
            True after an export that wrote at least one photo.
        """
        return self._written > 0

    def status_text(self) -> str:
        """How many photos the last export wrote.

        Returns:
            Text such as "268 written", or an empty text before the first export.
        """
        if self._written == 0:
            return ""
        return f"{self._written} written"

    def on_shown(self) -> None:
        """Show the project's export options and what an export would write."""
        project = self._controller.project
        if project is None:
            return
        options = project.export
        default_folder = str(project.default_export_folder)
        folder = options.output_folder or default_folder
        self._folder.setText(folder)
        self._long_side.setValue(options.long_side)
        self._quality.setValue(options.quality)
        self._copy_metadata.setChecked(options.copy_metadata)
        self._sharpen.setChecked(options.sharpen)
        self._overwrite.setChecked(options.overwrite)
        self._refresh_development_note()
        self._refresh_summary()

    def _make_options_card(self) -> Card:
        """The card with the folder, size, quality and metadata options.

        Returns:
            The card.
        """
        card = Card("Where and how", "The default size suits Instagram, Reels, TikTok and Shorts.")
        self._folder = QLineEdit()
        browse_button = self.make_button("Browse…", self._browse)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self._folder, 1)
        folder_row.addWidget(browse_button)
        self._long_side = QSpinBox()
        self._long_side.setRange(256, 8192)
        self._long_side.setSingleStep(64)
        self._long_side.setSuffix(" px")
        self._long_side.setMaximumWidth(160)
        self._quality = QSpinBox()
        self._quality.setRange(50, 100)
        self._quality.setMaximumWidth(160)
        self._copy_metadata = QCheckBox("Copy the date, camera and exposure details from the original")
        self._sharpen = QCheckBox("Sharpen a little after shrinking")
        self._overwrite = QCheckBox("Overwrite files that already exist in the folder")
        self._overwrite.setToolTip("Without this, a photo whose file already exists is skipped.")
        self._development_note = self.make_label("", "Muted")
        self._development_note.setWordWrap(True)
        form = QFormLayout()
        form.addRow("Folder", folder_row)
        form.addRow("Long side", self._long_side)
        form.addRow("JPEG quality", self._quality)
        form.addRow("", self._copy_metadata)
        form.addRow("", self._sharpen)
        form.addRow("", self._overwrite)
        card.body.addLayout(form)
        card.body.addWidget(self._development_note)
        return card

    def _refresh_development_note(self) -> None:
        """Say how raw files are developed: by darktable-cli, or from the camera's small preview."""
        if self._controller.darktable_available:
            text = (
                "Raw files are developed from their raw data by darktable-cli, at the size above, with the "
                "darktable edit of the picked option or else their own sidecar. That takes a few seconds per photo."
            )
        else:
            text = (
                "darktable-cli was not found, so raw files are exported from the small preview picture the camera "
                "stores inside them. Install darktable for full quality."
            )
        self._development_note.setText(text)

    def _settings(self) -> ExportSettings:
        """The export options set on the page.

        Returns:
            The options.
        """
        folder = self._folder.text()
        cleaned = folder.strip()
        long_side = self._long_side.value()
        quality = self._quality.value()
        copy_metadata = self._copy_metadata.isChecked()
        sharpen = self._sharpen.isChecked()
        overwrite = self._overwrite.isChecked()
        return ExportSettings(cleaned, long_side, quality, copy_metadata, sharpen, overwrite)

    def _refresh_summary(self) -> None:
        """Say how many photos an export would write, and which groups are left out."""
        plan = self._controller.export_plan()
        photo_count = len(plan.items)
        photos_text = count_text(photo_count, "photo")
        parts = [f"{photos_text} will be written."]
        if plan.skipped_groups:
            skipped_text = count_text(plan.skipped_groups, "skipped group")
            parts.append(f"Left out: {skipped_text}.")
        if plan.unpicked_groups:
            unpicked_text = count_text(plan.unpicked_groups, "group")
            parts.append(f"Left out until picked: {unpicked_text}.")
        text = " ".join(parts)
        self._summary.setText(text)

    def _browse(self) -> None:
        """Let the user pick the export folder."""
        start = self._folder.text()
        folder = QFileDialog.getExistingDirectory(self, "Choose the export folder", start)
        if folder:
            self._folder.setText(folder)

    def _export(self) -> None:
        """Start the export."""
        self._results.clear()
        settings = self._settings()
        self._controller.export(settings)

    def _open_folder(self) -> None:
        """Open the export folder in the file manager."""
        folder = self._folder.text()
        path = Path(folder)
        if not path.exists():
            return
        url = QUrl.fromLocalFile(folder)
        QDesktopServices.openUrl(url)

    def _show_results(self, results: list[ExportResult]) -> None:
        """List what happened to each photo.

        Args:
            results: The results of the export.
        """
        self._results.clear()
        written = 0
        for result in results:
            if result.status.is_written:
                written += 1
            text = f"{result.status.value}:  {result.target.name}"
            if result.message:
                text = f"{text}  ({result.message})"
            item = QListWidgetItem(text)
            target_text = str(result.target)
            item.setData(Qt.ItemDataRole.UserRole, target_text)
            self._results.addItem(item)
        self._written = written
        self._refresh_summary()
        self.readiness_changed.emit()

    def _show_result_in_folder(self, item: QListWidgetItem) -> None:
        """Show an exported file in its folder in the file manager.

        Args:
            item: The file's line in the results.
        """
        target_text = item.data(Qt.ItemDataRole.UserRole)
        target = Path(target_text)
        self._locations.show_in_folder(target)

    def _show_result_menu(self, position: QPoint) -> None:
        """Offer to open the exported file under the mouse, or to show it in its folder.

        Args:
            position: Where the user right-clicked, in the list's own coordinates.
        """
        item = self._results.itemAt(position)
        if item is None:
            return
        target_text = item.data(Qt.ItemDataRole.UserRole)
        target = Path(target_text)
        menu = QMenu(self)
        open_action = menu.addAction("Open the file")
        show_action = menu.addAction("Show in folder")
        viewport = self._results.viewport()
        screen_position = viewport.mapToGlobal(position)
        chosen = menu.exec(screen_position)
        if chosen is open_action:
            self._locations.open_file(target)
        elif chosen is show_action:
            self._locations.show_in_folder(target)
