"""Step 2: photos that are badly blurred, unclear, too dark or too bright are set aside."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QSplitter, QVBoxLayout, QWidget

from easy_photo.gui.controller import ProjectController
from easy_photo.gui.pages.base_page import WorkflowPage
from easy_photo.gui.photo_model import PhotoListModel
from easy_photo.gui.style import AppStyle
from easy_photo.gui.widgets.inspector import PhotoInspector
from easy_photo.gui.widgets.limits_panel import LimitsPanel
from easy_photo.gui.widgets.photo_grid import PhotoGrid
from easy_photo.model.quality import Decision


class FilterPage(WorkflowPage):
    """Step 2: the app sets aside photos that cannot be used; the user checks and corrects.

    Photos near a limit are marked unsure and stay in unless the user sets
    them aside. Nothing is deleted.
    """

    VIEWS = (("All", None), ("Keep", Decision.KEEP), ("Unsure", Decision.UNSURE), ("Set aside", Decision.SET_ASIDE))
    """The four views of the grid: a label and the decision it shows (None for all)."""

    LIMIT_DELAY_MS = 250

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
            "Filter",
            "The app sets aside photos that are badly blurred (with no sharp part a crop could keep), have no "
            "clear subject, or are too dark or too bright to recover. A soft face can be on purpose, so photos "
            "near a limit are marked unsure and kept until you decide. Nothing is deleted.",
            parent,
        )
        self._model = PhotoListModel(controller, self)
        self._view_decision: Decision | None = None
        self._shown_photo = ""
        self._limit_timer = QTimer(self)
        self._limit_timer.setSingleShot(True)
        self._limit_timer.setInterval(self.LIMIT_DELAY_MS)
        self._limit_timer.timeout.connect(self._apply_limits)
        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        top = self._make_top_bar()
        self._limits = LimitsPanel(content)
        self._limits.setVisible(False)
        self._limits.settings_changed.connect(self._limit_timer.start)
        splitter = self._make_main_area(content)
        layout.addLayout(top)
        layout.addWidget(self._limits)
        layout.addWidget(splitter, 1)
        self.set_content(content)
        self._add_shortcuts()
        controller.project_opened.connect(self.on_shown)
        controller.photos_changed.connect(self._refresh_list)
        controller.photo_updated.connect(self._on_photo_updated)
        controller.analysis_changed.connect(self._on_analysis_changed)

    def is_ready(self) -> bool:
        """The user can go on once at least one photo is kept.

        Returns:
            True when a photo is kept.
        """
        project = self._controller.project
        if project is None:
            return False
        counts = project.count_by_decision()
        return counts[Decision.KEEP] + counts[Decision.UNSURE] > 0

    def status_text(self) -> str:
        """How many photos are kept and set aside.

        Returns:
            Text such as "300 kept, 32 set aside".
        """
        project = self._controller.project
        if project is None or project.analyzed_count == 0:
            return ""
        counts = project.count_by_decision()
        kept = counts[Decision.KEEP] + counts[Decision.UNSURE]
        aside = counts[Decision.SET_ASIDE]
        return f"{kept} kept, {aside} set aside"

    def on_shown(self) -> None:
        """Show the project's limits and the photos of the chosen view."""
        project = self._controller.project
        if project is not None:
            self._limits.set_settings(project.checks)
        self._refresh_list()

    # ----------------------------------------------------------------- layout

    def _make_top_bar(self) -> QHBoxLayout:
        """The row with the four view buttons and the limits button.

        Returns:
            The row.
        """
        row = QHBoxLayout()
        row.setSpacing(6)
        self._view_group = QButtonGroup(self)
        self._view_group.setExclusive(True)
        self._view_buttons: list[QPushButton] = []
        for number, (label, _decision) in enumerate(self.VIEWS):
            button = QPushButton(label)
            button.setObjectName("Segment")
            button.setCheckable(True)
            self._view_group.addButton(button, number)
            self._view_buttons.append(button)
            row.addWidget(button)
        first = self._view_buttons[0]
        first.setChecked(True)
        self._view_group.idClicked.connect(self._on_view_chosen)
        row.addStretch(1)
        self._limits_button = QPushButton("Limits")
        self._limits_button.setCheckable(True)
        self._limits_button.toggled.connect(self._on_limits_toggled)
        row.addWidget(self._limits_button)
        return row

    def _make_main_area(self, parent: QWidget) -> QSplitter:
        """The photo grid on the left and the inspector on the right.

        Args:
            parent: The content widget.

        Returns:
            The splitter that holds both.
        """
        splitter = QSplitter(Qt.Orientation.Horizontal, parent)
        self._grid = PhotoGrid(self._model, self._style, splitter)
        self._grid.current_photo_changed.connect(self._on_current_changed)
        self._inspector = PhotoInspector(self._style, splitter)
        self._inspector.setMinimumWidth(360)
        self._inspector.keep_clicked.connect(self._keep_selected)
        self._inspector.set_aside_clicked.connect(self._set_aside_selected)
        self._inspector.reset_clicked.connect(self._reset_selected)
        splitter.addWidget(self._grid)
        splitter.addWidget(self._inspector)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        return splitter

    def _add_shortcuts(self) -> None:
        """K keeps, X sets aside and U undoes the user's choice, for the selected photos."""
        keys = (("K", self._keep_selected), ("X", self._set_aside_selected), ("U", self._reset_selected))
        for key, handler in keys:
            sequence = QKeySequence(key)
            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(handler)

    # ---------------------------------------------------------------- updates

    def _refresh_list(self) -> None:
        """Show the photos of the chosen view, keeping the place in the grid."""
        project = self._controller.project
        row = self._grid.current_row()
        if project is None:
            self._model.set_photo_ids([])
            return
        photo_ids: list[str] = []
        for photo in project.photos:
            decision = project.decision_of(photo.id)
            if self._view_decision is None or decision is self._view_decision:
                photo_ids.append(photo.id)
        self._model.set_photo_ids(photo_ids)
        self._refresh_counts()
        if photo_ids:
            start = max(row, 0)
            self._grid.select_row(start)
        else:
            self._show_inspector("")

    def _refresh_counts(self) -> None:
        """Write the number of photos on each view button."""
        project = self._controller.project
        if project is None:
            return
        counts = project.count_by_decision()
        total = project.photo_count
        for button, (label, decision) in zip(self._view_buttons, self.VIEWS):
            count = total if decision is None else counts[decision]
            button.setText(f"{label}  {count}")

    def _on_photo_updated(self, photo_id: str) -> None:
        """Redraw a photo, and the inspector when it shows that photo.

        Args:
            photo_id: Id of the photo.
        """
        self._model.refresh_photo(photo_id)
        if photo_id == self._shown_photo:
            self._show_inspector(photo_id)

    def _on_analysis_changed(self) -> None:
        """Show the new decisions after measuring, a change of limits or the user's choices."""
        self._refresh_list()
        self.readiness_changed.emit()

    def _on_view_chosen(self, number: int) -> None:
        """Show the photos of another view.

        Args:
            number: Index of the view in :attr:`VIEWS`.
        """
        _label, decision = self.VIEWS[number]
        self._view_decision = decision
        self._refresh_list()

    def _on_limits_toggled(self, shown: bool) -> None:
        """Show or hide the limit sliders.

        Args:
            shown: True to show them.
        """
        self._limits.setVisible(shown)

    def _apply_limits(self) -> None:
        """Judge all photos again with the limits on the sliders."""
        checks = self._limits.settings()
        self._controller.update_checks(checks)

    # -------------------------------------------------------------- inspector

    def _on_current_changed(self, photo_id: str) -> None:
        """Show the current photo in the inspector and load its large preview.

        Args:
            photo_id: Id of the current photo, or an empty text.
        """
        self._show_inspector(photo_id)
        if photo_id:
            self._controller.load_preview(photo_id, self._on_preview_loaded)

    def _show_inspector(self, photo_id: str) -> None:
        """Fill the inspector for a photo, starting with its thumbnail.

        Args:
            photo_id: Id of the photo, or an empty text for none.
        """
        project = self._controller.project
        photo = project.photo(photo_id) if project is not None and photo_id else None
        if photo is None:
            self._shown_photo = ""
            self._inspector.show_photo(None, None, None, False)
            return
        result = project.quality_of(photo_id)
        decision = project.decision_of(photo_id)
        user_decision = project.user_decision_of(photo_id)
        by_user = user_decision is not None
        self._inspector.show_photo(photo, result, decision, by_user)
        if photo_id != self._shown_photo:
            thumbnail = self._controller.thumbnail(photo_id)
            self._inspector.set_image(thumbnail)
        self._shown_photo = photo_id

    def _on_preview_loaded(self, photo_id: str, image: QImage) -> None:
        """Show a loaded large preview, if its photo is still the one shown.

        Args:
            photo_id: Id of the photo.
            image: The preview.
        """
        if photo_id == self._shown_photo:
            self._inspector.set_image(image)

    # -------------------------------------------------------------- decisions

    def _keep_selected(self) -> None:
        """Keep the selected photos."""
        self._decide(Decision.KEEP)

    def _set_aside_selected(self) -> None:
        """Set the selected photos aside."""
        self._decide(Decision.SET_ASIDE)

    def _reset_selected(self) -> None:
        """Go back to the app's decision for the selected photos."""
        self._decide(None)

    def _decide(self, decision: Decision | None) -> None:
        """Store a decision for the selected photos (or the current one).

        Args:
            decision: The decision, or None to go back to the app's decision.
        """
        photo_ids = self._grid.selected_photo_ids()
        if not photo_ids and self._shown_photo:
            photo_ids = [self._shown_photo]
        if not photo_ids:
            return
        self._controller.decide(photo_ids, decision)
