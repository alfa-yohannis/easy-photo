"""Step 6: every kept photo is developed, refined with its group's pick, and written as a JPEG file."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from easy_photo.gui.controller import ProjectController
from easy_photo.gui.pages.base_page import WorkflowPage
from easy_photo.gui.style import AppStyle
from easy_photo.gui.widgets.card import Card
from easy_photo.services.exporter import ExportResult, ExportStatus
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
            "file. A file that already exists is never overwritten.",
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
        self._development_note = self.make_label("", "Muted")
        self._development_note.setWordWrap(True)
        form = QFormLayout()
        form.addRow("Folder", folder_row)
        form.addRow("Long side", self._long_side)
        form.addRow("JPEG quality", self._quality)
        form.addRow("", self._copy_metadata)
        form.addRow("", self._sharpen)
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
        return ExportSettings(cleaned, long_side, quality, copy_metadata, sharpen)

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
            if result.status is ExportStatus.WRITTEN:
                written += 1
            text = f"{result.status.value}:  {result.target.name}"
            if result.message:
                text = f"{text}  ({result.message})"
            self._results.addItem(text)
        self._written = written
        self._refresh_summary()
        self.readiness_changed.emit()
