"""Step 5: for each group the user picks a version, or types the change they want."""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from easy_photo.gui.controller import ProjectController
from easy_photo.gui.file_locations import FileLocations
from easy_photo.gui.pages.base_page import WorkflowPage
from easy_photo.gui.style import AppStyle
from easy_photo.gui.widgets.version_card import VersionCard
from easy_photo.refinement.pipeline import RefinementPipeline
from easy_photo.wording import count_text


class RefinePage(WorkflowPage):
    """Step 5: the options are shown on each group's sharpest photo, and the user picks one.

    When no option fits, the user types the change they want; the app makes
    that version at once and picks it.
    """

    COLUMNS = 3
    MAX_NUMBER_KEYS = 9

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
            "Refine",
            "Compare the options on the sharpest photo of each group and pick the one you like; it is used for "
            "every photo of the group. If none fits, describe the change you want below.",
            parent,
        )
        self._group_id = ""
        self._cards: list[VersionCard] = []
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._groups_list = QListWidget(splitter)
        self._groups_list.setMinimumWidth(250)
        self._groups_list.setWordWrap(True)
        self._groups_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._groups_list.currentItemChanged.connect(self._on_group_chosen)
        right = self._make_versions_column(splitter)
        splitter.addWidget(self._groups_list)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        self.set_content(splitter)
        self._add_shortcuts()
        controller.project_opened.connect(self.on_shown)
        controller.groups_changed.connect(self._refresh_groups)
        controller.choices_changed.connect(self._on_choices_changed)
        controller.versions_changed.connect(self._on_versions_changed)
        controller.pipelines_changed.connect(self._on_options_changed)
        controller.option_groups_changed.connect(self._on_option_groups_changed)
        controller.words_answered.connect(self._on_words_answered)

    def is_ready(self) -> bool:
        """The user can go on to the export once one group has a pick; the others can wait.

        Returns:
            True when at least one group is decided.
        """
        project = self._controller.project
        return project is not None and project.chosen_count > 0

    def is_done(self) -> bool:
        """The step is finished when every group has a pick or is skipped.

        Returns:
            True when all groups are decided.
        """
        project = self._controller.project
        if project is None or not project.groups:
            return False
        count = len(project.groups)
        return project.chosen_count >= count

    def status_text(self) -> str:
        """How many groups have a pick.

        Returns:
            Text such as "12 of 31 groups".
        """
        project = self._controller.project
        if project is None or not project.groups:
            return ""
        count = len(project.groups)
        return f"{project.chosen_count} of {count} groups"

    def on_shown(self) -> None:
        """Show the groups and the versions of the chosen group."""
        self._refresh_groups()

    # ----------------------------------------------------------------- layout

    def _make_versions_column(self, parent: QWidget) -> QWidget:
        """The right side: the group's title, the version cards and the "describe it" row.

        Args:
            parent: The splitter.

        Returns:
            The column.
        """
        column = QWidget(parent)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(8)
        self._title = self.make_label("", "SectionTitle")
        self._info = self.make_label("", "Muted")
        self._info.setWordWrap(True)
        self._recalculate_button = self.make_button("Recalculate   (F5)", self._recalculate)
        self._recalculate_button.setToolTip(
            "Make the versions again, for example after you changed a darktable edit in darktable."
        )
        self._locations = FileLocations()
        self._show_sample_button = self.make_button("Show photo in folder", self._show_sample_in_folder)
        self._show_sample_button.setToolTip("Show the photo the versions are made on in the file manager.")
        title_row = QHBoxLayout()
        title_row.addWidget(self._title, 1)
        title_row.addWidget(self._show_sample_button)
        title_row.addWidget(self._recalculate_button)
        self._cards_area = QScrollArea(column)
        self._cards_area.setWidgetResizable(True)
        self._cards_holder = QWidget()
        self._cards_grid = QGridLayout(self._cards_holder)
        self._cards_grid.setSpacing(12)
        self._cards_grid.setContentsMargins(0, 0, 0, 0)
        for column_index in range(self.COLUMNS):
            self._cards_grid.setColumnStretch(column_index, 1)
        self._cards_area.setWidget(self._cards_holder)
        self._waiting = self.make_label("", "Muted")
        self._waiting.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bottom = self._make_words_panel(column)
        layout.addLayout(title_row)
        layout.addWidget(self._info)
        layout.addWidget(self._waiting)
        layout.addWidget(self._cards_area, 1)
        layout.addWidget(bottom)
        return column

    def _make_words_panel(self, parent: QWidget) -> QFrame:
        """The panel under the cards: describe a change, skip the group, or go to the next one.

        Args:
            parent: The column.

        Returns:
            The panel.
        """
        panel = QFrame(parent)
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)
        label = self.make_label("None of these fits? Describe the change you want:")
        self._words = QLineEdit()
        self._words.setPlaceholderText("for example: brighter faces, less contrast")
        self._words.returnPressed.connect(self._try_words)
        try_button = self.make_button("Try it", self._try_words)
        skip_button = self.make_button("Skip this group", self._skip_group)
        next_button = self.make_button("Next group", self._next_group, primary=True)
        self._words_note = self.make_label("", "Muted")
        self._words_note.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(self._words, 1)
        row.addWidget(try_button)
        row.addSpacing(16)
        row.addWidget(skip_button)
        row.addWidget(next_button)
        hint = self.make_label(
            "Your words are added on top of the version you picked; with no pick, on top of the unchanged photo. "
            "Words the app does not know are read by Claude, through Claude Code. Keys 1 to 9 pick a version.",
            "Muted",
        )
        hint.setWordWrap(True)
        layout.addWidget(label)
        layout.addLayout(row)
        layout.addWidget(self._words_note)
        layout.addWidget(hint)
        return panel

    def _add_shortcuts(self) -> None:
        """Keys 1 to 9 pick the version with that number; F5 makes the versions again."""
        for number in range(1, self.MAX_NUMBER_KEYS + 1):
            sequence = QKeySequence(f"{number}")
            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            handler = partial(self._pick_number, number)
            shortcut.activated.connect(handler)
        refresh_key = QKeySequence("F5")
        refresh_shortcut = QShortcut(refresh_key, self)
        refresh_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        refresh_shortcut.activated.connect(self._recalculate)

    def _show_sample_in_folder(self) -> None:
        """Show the photo the chosen group's versions are made on, in its folder in the file manager."""
        sample = self._controller.sample_photo(self._group_id)
        if sample is not None:
            self._locations.show_in_folder(sample.path)

    def _recalculate(self) -> None:
        """Make the chosen group's versions again; the cards show "Making the versions…" meanwhile."""
        group_id = self._group_id
        if not group_id:
            return
        self._controller.recalculate_versions(group_id)
        self._show_group(group_id)

    # ----------------------------------------------------------------- groups

    def _refresh_groups(self) -> None:
        """Show the groups with their picks, keeping the chosen group."""
        project = self._controller.project
        chosen = self._group_id
        self._groups_list.blockSignals(True)
        self._groups_list.clear()
        if project is not None:
            for group in project.groups:
                text = self._group_text(group.id)
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, group.id)
                self._groups_list.addItem(item)
        self._groups_list.blockSignals(False)
        row = self._row_of(chosen)
        if row < 0:
            row = self._first_unpicked_row()
        if row >= 0:
            self._groups_list.setCurrentRow(row)
        else:
            self._show_group("")
        self.readiness_changed.emit()

    def _group_text(self, group_id: str) -> str:
        """The list text of a group: a mark, the title, and the pick.

        Args:
            group_id: Id of the group.

        Returns:
            Two lines of text.
        """
        project = self._controller.project
        group = project.group(group_id)
        choice = project.choice_of(group_id)
        if choice is None:
            mark = "•"
            picked = "Not picked yet"
        elif choice.pipeline_id is None:
            mark = "–"
            picked = "Skipped"
        else:
            mark = "✓"
            option = project.pipeline(choice.pipeline_id)
            picked = option.name if option is not None else "Picked"
        return f"{mark}  {group.title}  ({group.size})\n     {picked}"

    def _row_of(self, group_id: str) -> int:
        """The list row of a group.

        Args:
            group_id: Id of the group.

        Returns:
            The row, or -1 when the group is not in the list.
        """
        count = self._groups_list.count()
        for row in range(count):
            item = self._groups_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == group_id:
                return row
        return -1

    def _first_unpicked_row(self) -> int:
        """The first group without a pick, or the first group.

        Returns:
            Its row, or -1 when there are no groups.
        """
        project = self._controller.project
        count = self._groups_list.count()
        for row in range(count):
            item = self._groups_list.item(row)
            group_id = item.data(Qt.ItemDataRole.UserRole)
            if project.choice_of(group_id) is None:
                return row
        return 0 if count else -1

    def _on_group_chosen(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        """Show the versions of the chosen group.

        Args:
            current: The chosen item.
            _previous: The item chosen before (not used).
        """
        group_id = current.data(Qt.ItemDataRole.UserRole) if current is not None else ""
        self._show_group(group_id)

    def _show_group(self, group_id: str) -> None:
        """Show a group's title and versions; ask for the versions when they are not made yet.

        The versions are only asked for while the page is shown, since each one
        is a darktable development; :meth:`on_shown` asks when the page opens.

        Args:
            group_id: Id of the group, or an empty text for none.
        """
        self._group_id = group_id
        self._show_words_note("", False)
        project = self._controller.project
        group = project.group(group_id) if project is not None and group_id else None
        self._recalculate_button.setEnabled(group is not None)
        self._show_sample_button.setEnabled(group is not None)
        if group is None:
            self._title.setText("No groups yet")
            self._info.setText("Make groups in the Group step first.")
            self._show_cards([])
            return
        self._title.setText(group.title)
        info = self._sample_text(group_id)
        self._info.setText(info)
        versions = self._controller.versions(group_id)
        if versions:
            self._show_cards(versions)
            return
        self._show_cards([])
        self._waiting.setText("Making the versions…")
        self._waiting.setVisible(True)
        if self.isVisible():
            self._controller.render_versions(group_id)

    def _sample_text(self, group_id: str) -> str:
        """Say which photo the versions are shown on, and why that one.

        Args:
            group_id: Id of the group.

        Returns:
            Text such as "Shown on P1209977.RW2, the sharpest of its 12 selected photos."
        """
        project = self._controller.project
        group = project.group(group_id)
        sample = self._controller.sample_photo(group_id)
        if sample is None:
            return "None of this group's photos is in the project any more."
        selected = project.selected_photos_of(group)
        if not selected:
            return (
                f"Shown on {sample.name}. None of the group's {group.size} photos is selected, "
                "so the group is not exported."
            )
        selected_count = len(selected)
        selected_text = count_text(selected_count, "selected photo")
        return f"Shown on {sample.name}, the sharpest of its {selected_text}."

    # ------------------------------------------------------------------ cards

    def _show_cards(self, versions: list) -> None:
        """Replace the version cards.

        Args:
            versions: The versions to show.
        """
        self._clear_cards()
        self._waiting.setVisible(not versions)
        if not versions:
            self._waiting.setText("")
        for index, preview in enumerate(versions):
            number = index + 1
            card = VersionCard(preview, number, self._style, self._cards_holder)
            card.picked.connect(self._on_card_picked)
            row, column = divmod(index, self.COLUMNS)
            self._cards_grid.addWidget(card, row, column)
            self._cards.append(card)
        self._mark_choice()

    def _clear_cards(self) -> None:
        """Remove all version cards."""
        for card in self._cards:
            self._cards_grid.removeWidget(card)
            # Hidden at once: Qt deletes the card only when it is back in its event loop.
            card.hide()
            card.deleteLater()
        self._cards = []

    def _mark_choice(self) -> None:
        """Highlight the card of the group's pick."""
        project = self._controller.project
        choice = project.choice_of(self._group_id) if project is not None and self._group_id else None
        chosen_id = choice.pipeline_id if choice is not None else None
        for card in self._cards:
            selected = card.pipeline_id == chosen_id
            card.set_selected(selected)

    # ---------------------------------------------------------------- signals

    def _on_versions_changed(self, group_id: str) -> None:
        """Show newly made versions when they belong to the chosen group.

        Args:
            group_id: Id of the group.
        """
        if group_id != self._group_id:
            return
        versions = self._controller.versions(group_id)
        self._show_cards(versions)

    def _on_choices_changed(self) -> None:
        """Update the group list and the highlighted card."""
        project = self._controller.project
        if project is None:
            return
        count = self._groups_list.count()
        for row in range(count):
            item = self._groups_list.item(row)
            group_id = item.data(Qt.ItemDataRole.UserRole)
            text = self._group_text(group_id)
            item.setText(text)
        self._mark_choice()
        self.readiness_changed.emit()

    def _on_options_changed(self) -> None:
        """The options changed in the References step: make the chosen group's versions again."""
        if self._group_id and self.isVisible():
            self._show_group(self._group_id)

    def _on_option_groups_changed(self, group_id: str) -> None:
        """An option was turned on or off for a group: make that group's versions again when it is shown.

        Args:
            group_id: Id of the group.
        """
        if group_id == self._group_id and self.isVisible():
            self._show_group(group_id)

    def _on_words_answered(self, target: str, worked: bool, message: str) -> None:
        """Show how typed words were read, when they were typed for the chosen group.

        Args:
            target: The group the words were typed for.
            worked: Whether a version was made.
            message: Claude's explanation, or why it did not work.
        """
        if target != self._group_id:
            return
        if worked:
            self._words.clear()
            note = f"Claude: {message}" if message else ""
            self._show_words_note(note, False)
            return
        self._show_words_note(message, True)

    def _show_words_note(self, text: str, is_error: bool) -> None:
        """Write a note under the words box, in red for errors.

        Args:
            text: The note.
            is_error: True for an error.
        """
        name = "ErrorText" if is_error else "Muted"
        self._words_note.setObjectName(name)
        self._style.refresh(self._words_note)
        self._words_note.setText(text)

    # ---------------------------------------------------------------- actions

    def _on_card_picked(self, pipeline_id: str) -> None:
        """Store the version the user picked.

        Args:
            pipeline_id: Id of its option.
        """
        if self._group_id:
            self._controller.choose(self._group_id, pipeline_id)

    def _pick_number(self, number: int) -> None:
        """Pick the version with the given number.

        Args:
            number: The number shown on its card, from 1.
        """
        if number > len(self._cards):
            return
        card = self._cards[number - 1]
        self._on_card_picked(card.pipeline_id)

    def _try_words(self) -> None:
        """Make a version from the typed words, on top of the current pick; the answer arrives later."""
        if not self._group_id:
            return
        text = self._words.text()
        if not text.strip():
            return
        base_id = self._current_pick_id()
        self._show_words_note("Reading your words…", False)
        self._controller.try_words(self._group_id, base_id, text)

    def _current_pick_id(self) -> str | None:
        """The option the typed words are added to: the chosen group's pick.

        Returns:
            Its id, or the camera option's id when nothing is picked or the group is skipped.
        """
        project = self._controller.project
        choice = project.choice_of(self._group_id)
        if choice is None or choice.pipeline_id is None:
            return RefinementPipeline.CAMERA_ID
        return choice.pipeline_id

    def _skip_group(self) -> None:
        """Leave the chosen group out of the export."""
        if self._group_id:
            self._controller.choose(self._group_id, None)

    def _next_group(self) -> None:
        """Go to the next group without a pick, or simply the next group."""
        project = self._controller.project
        count = self._groups_list.count()
        current = self._groups_list.currentRow()
        for row in range(current + 1, count):
            item = self._groups_list.item(row)
            group_id = item.data(Qt.ItemDataRole.UserRole)
            if project.choice_of(group_id) is None:
                self._groups_list.setCurrentRow(row)
                return
        if current + 1 < count:
            self._groups_list.setCurrentRow(current + 1)
