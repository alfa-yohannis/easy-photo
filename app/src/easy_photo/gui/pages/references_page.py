"""Step 4: the user adds references; each one becomes a refinement option, used for the groups the user chooses."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from easy_photo.gui.controller import ProjectController
from easy_photo.gui.pages.base_page import WorkflowPage
from easy_photo.gui.style import AppStyle
from easy_photo.gui.widgets.card import Card
from easy_photo.gui.widgets.drop_zone import DropZone
from easy_photo.model.photo import IMAGE_EXTENSIONS, RAW_EXTENSIONS
from easy_photo.refinement.pipeline import RefinementPipeline
from easy_photo.wording import count_text


class ReferencesPage(WorkflowPage):
    """Step 4: references from the user's history, the internet, examples, or their own words.

    Each reference becomes a refinement option. An option is shown in the
    Refine step for every group, unless the user turns it off for some groups
    here. The unchanged photo is always an option.
    """

    ai_settings_requested = Signal()

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
            "References",
            "Show the app what you like. Each reference becomes a refinement option that you compare on your "
            "photos in the next step, for the groups you choose. The unchanged photo is always one of the "
            "options.",
            parent,
        )
        self._filling = False
        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        cards = QGridLayout()
        cards.setHorizontalSpacing(14)
        cards.setVerticalSpacing(14)
        history = self._make_history_card()
        internet = self._make_internet_card()
        examples = self._make_examples_card()
        words = self._make_words_card()
        cards.addWidget(history, 0, 0)
        cards.addWidget(internet, 0, 1)
        cards.addWidget(examples, 1, 0)
        cards.addWidget(words, 1, 1)
        options = self._make_options_section(content)
        layout.addLayout(cards)
        layout.addWidget(options, 1)
        self.set_content(content)
        controller.project_opened.connect(self.on_shown)
        controller.pipelines_changed.connect(self._refresh_options)
        controller.groups_changed.connect(self._refresh_option_groups)
        controller.words_answered.connect(self._on_words_answered)
        controller.ai_changed.connect(self._refresh_ai_note)

    def is_done(self) -> bool:
        """The step is finished once the user added at least one reference.

        Returns:
            True when there is an option besides the unchanged photo.
        """
        project = self._controller.project
        return project is not None and len(project.pipelines) > 1

    def status_text(self) -> str:
        """The number of refinement options.

        Returns:
            Text such as "3 options".
        """
        project = self._controller.project
        if project is None:
            return ""
        count = len(project.pipelines)
        if count == 1:
            return "Camera only"
        return count_text(count, "option")

    def on_shown(self) -> None:
        """Show the current options, whether darktable-cli is there, and whether Claude can read words."""
        self._refresh_options()
        self._refresh_darktable_note()
        self._refresh_ai_note()

    # ------------------------------------------------------------------ cards

    def _make_history_card(self) -> Card:
        """The card for photos the user picked before.

        Returns:
            The card.
        """
        card = Card(
            "Your history",
            "Photos you picked or kept before, such as a folder you shared. The app learns how bright you like "
            "photos, and how bright you like faces.",
        )
        folder_button = self.make_button("Add folder…", self._add_history_folder)
        files_button = self.make_button("Add photos…", self._add_history_files)
        row = QHBoxLayout()
        row.addWidget(folder_button)
        row.addWidget(files_button)
        row.addStretch(1)
        card.body.addLayout(row)
        return card

    def _make_internet_card(self) -> Card:
        """The card for searching photos on the internet.

        Returns:
            The card.
        """
        service = self._controller.search_service_name
        card = Card(
            "The internet",
            f"Search free photos on {service} with the look you want. They are only measured on this computer.",
        )
        self._query = QLineEdit()
        self._query.setPlaceholderText("for example: Mount Fuji autumn")
        self._query.returnPressed.connect(self._search)
        search_button = self.make_button("Search", self._search)
        row = QHBoxLayout()
        row.addWidget(self._query, 1)
        row.addWidget(search_button)
        card.body.addLayout(row)
        return card

    def _make_examples_card(self) -> Card:
        """The card for example files the user selects now.

        Returns:
            The card.
        """
        card = Card(
            "Examples",
            "Photos you edited or like right now; the app learns how bright they are. Add a darktable sidecar "
            "(.xmp file) to apply that edit itself: darktable-cli develops every raw photo with it.",
        )
        self._darktable_note = self.make_label("", "Muted")
        self._darktable_note.setWordWrap(True)
        files_button = self.make_button("Add example files…", self._add_examples)
        row = QHBoxLayout()
        row.addWidget(files_button)
        row.addStretch(1)
        card.body.addWidget(self._darktable_note)
        card.body.addLayout(row)
        return card

    def _make_words_card(self) -> Card:
        """The card for a refinement described in words.

        Returns:
            The card.
        """
        card = Card(
            "Your own words",
            "Describe the refinement, for example: brighter faces, less contrast, neutral colors.",
        )
        self._words = QLineEdit()
        self._words.setPlaceholderText("brighter faces, less contrast")
        self._words.returnPressed.connect(self._add_words)
        add_button = self.make_button("Add", self._add_words)
        help_button = self.make_button("What can I type?", self._show_words_help)
        self._words_note = self.make_label("", "Muted")
        self._words_note.setWordWrap(True)
        self._ai_note = self.make_label("", "Muted")
        self._ai_note.setWordWrap(True)
        ai_button = self.make_button("AI settings…", self.ai_settings_requested.emit)
        row = QHBoxLayout()
        row.addWidget(self._words, 1)
        row.addWidget(add_button)
        row.addWidget(help_button)
        ai_row = QHBoxLayout()
        ai_row.addWidget(self._ai_note, 1)
        ai_row.addWidget(ai_button)
        card.body.addLayout(row)
        card.body.addWidget(self._words_note)
        card.body.addLayout(ai_row)
        return card

    def _make_options_section(self, parent: QWidget) -> QWidget:
        """The options list, and next to it the groups the selected option is used for.

        Args:
            parent: The content widget.

        Returns:
            The section.
        """
        section = QWidget(parent)
        options_title = self.make_label("Refinement options", "SectionTitle")
        self._options_list = QListWidget(section)
        self._options_list.setWordWrap(True)
        self._options_list.currentItemChanged.connect(self._on_option_chosen)
        remove_button = self.make_button("Remove selected option", self._remove_option)
        remove_row = QHBoxLayout()
        remove_row.addStretch(1)
        remove_row.addWidget(remove_button)
        options_column = QVBoxLayout()
        options_column.addWidget(options_title)
        options_column.addWidget(self._options_list, 1)
        options_column.addLayout(remove_row)
        groups_title = self.make_label("Used for these groups", "SectionTitle")
        self._groups_note = self.make_label("", "Muted")
        self._groups_note.setWordWrap(True)
        self._groups_list = QListWidget(section)
        self._groups_list.itemChanged.connect(self._on_group_checked)
        all_button = self.make_button("All groups", self._use_for_all_groups)
        none_button = self.make_button("No groups", self._use_for_no_groups)
        group_buttons = QHBoxLayout()
        group_buttons.addWidget(all_button)
        group_buttons.addWidget(none_button)
        group_buttons.addStretch(1)
        groups_column = QVBoxLayout()
        groups_column.addWidget(groups_title)
        groups_column.addWidget(self._groups_note)
        groups_column.addWidget(self._groups_list, 1)
        groups_column.addLayout(group_buttons)
        layout = QHBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addLayout(options_column, 3)
        layout.addLayout(groups_column, 2)
        return section

    # -------------------------------------------------------------- refreshes

    def _refresh_options(self) -> None:
        """Show the project's refinement options, keeping the selected one."""
        chosen = self._chosen_option_id()
        self._options_list.blockSignals(True)
        self._options_list.clear()
        project = self._controller.project
        if project is not None:
            for option in project.pipelines:
                steps = option.describe_steps()
                text = f"{option.name}\n{steps}"
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, option.id)
                item.setToolTip(option.details)
                self._options_list.addItem(item)
        self._options_list.blockSignals(False)
        self._select_option(chosen)
        self._refresh_option_groups()
        self.readiness_changed.emit()

    def _refresh_option_groups(self) -> None:
        """Tick the groups the selected option is used for."""
        project = self._controller.project
        option_id = self._chosen_option_id()
        self._filling = True
        self._groups_list.clear()
        has_groups = project is not None and bool(project.groups)
        is_camera = option_id == RefinementPipeline.CAMERA_ID
        if not has_groups:
            self._groups_note.setText("Make groups first. Until then every option is used for every group.")
        elif is_camera:
            self._groups_note.setText("The unchanged photo is always an option.")
        elif not option_id:
            self._groups_note.setText("Select an option to choose its groups.")
        else:
            self._groups_note.setText("Untick a group to leave this option out of its comparison.")
        if has_groups and option_id:
            for group in project.groups:
                item = QListWidgetItem(group.title)
                item.setData(Qt.ItemDataRole.UserRole, group.id)
                used = project.option_used_in(group.id, option_id)
                state = Qt.CheckState.Checked if used else Qt.CheckState.Unchecked
                item.setCheckState(state)
                if is_camera:
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self._groups_list.addItem(item)
        self._filling = False

    def _refresh_darktable_note(self) -> None:
        """Say whether raw files are developed with darktable and .xmp files can be used."""
        if self._controller.darktable_available:
            self._darktable_note.setText("darktable-cli was found: raw files are developed with it.")
        else:
            self._darktable_note.setText(
                "darktable-cli was not found, so raw files are measured from the camera's preview picture "
                "and .xmp files cannot be used."
            )

    def _refresh_ai_note(self) -> None:
        """Say whether Claude reads the words the app's own phrases do not cover."""
        controller = self._controller
        if controller.ai_ready:
            text = "Words the app does not know are read by Claude. Only your words are sent, never your photos."
        elif controller.ai_enabled:
            text = "Add an Anthropic API key to let Claude read any words, not only the app's own phrases."
        else:
            text = "Claude is switched off; only the app's own phrases are understood."
        self._ai_note.setText(text)

    # ---------------------------------------------------------------- actions

    def _add_history_folder(self) -> None:
        """Pick a folder of photos the user picked before."""
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder of photos you picked before")
        if folder:
            path = Path(folder)
            self._controller.add_history([path])

    def _add_history_files(self) -> None:
        """Pick photos the user picked before."""
        paths = self._pick_photos("Choose photos you picked before")
        self._controller.add_history(paths)

    def _add_examples(self) -> None:
        """Pick example files."""
        paths = self._pick_photos("Choose example photos")
        self._controller.add_examples(paths)

    def _search(self) -> None:
        """Search the internet for the phrase in the search box."""
        query = self._query.text()
        self._controller.search_internet(query)

    def _add_words(self) -> None:
        """Make an option from the typed words; the answer arrives in :meth:`_on_words_answered`."""
        text = self._words.text()
        if not text.strip():
            return
        self._show_words_note("Reading your words…", False)
        self._controller.add_words(text)

    def _on_words_answered(self, target: str, worked: bool, message: str) -> None:
        """Show how typed words were read, when they were typed on this page.

        Args:
            target: Where the words were typed.
            worked: Whether an option was made.
            message: Claude's explanation, or why it did not work.
        """
        if target != ProjectController.REFERENCES_TARGET:
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

    def _show_words_help(self) -> None:
        """Show the phrases the app understands by itself."""
        examples = self._controller.services.parser.examples()
        lines = [f"• {example}" for example in examples]
        listing = "\n".join(lines)
        text = (
            "Type one or more changes, separated by commas or \"and\". Start a change with \"slightly\" or "
            "\"much\" to make it weaker or stronger, or give a number. The app understands these by itself:\n\n"
            f"{listing}\n\n"
            "With an Anthropic API key in the AI settings, Claude also reads anything else you type, in any "
            "language."
        )
        QMessageBox.information(self, "What can I type?", text)

    def _remove_option(self) -> None:
        """Remove the selected option."""
        option_id = self._chosen_option_id()
        if option_id:
            self._controller.remove_pipeline(option_id)

    def _on_option_chosen(self, _current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        """Show the groups of the newly selected option.

        Args:
            _current: The selected item (read again through :meth:`_chosen_option_id`).
            _previous: The item selected before (not used).
        """
        self._refresh_option_groups()

    def _on_group_checked(self, item: QListWidgetItem) -> None:
        """Turn the selected option on or off for the group the user ticked or unticked.

        Args:
            item: The group's list item.
        """
        if self._filling:
            return
        option_id = self._chosen_option_id()
        if not option_id:
            return
        group_id = item.data(Qt.ItemDataRole.UserRole)
        used = item.checkState() == Qt.CheckState.Checked
        self._controller.set_option_used(group_id, option_id, used)

    def _use_for_all_groups(self) -> None:
        """Use the selected option for every group."""
        self._set_all_groups(Qt.CheckState.Checked)

    def _use_for_no_groups(self) -> None:
        """Leave the selected option out of every group."""
        self._set_all_groups(Qt.CheckState.Unchecked)

    def _set_all_groups(self, state: Qt.CheckState) -> None:
        """Tick or untick every group of the selected option.

        Args:
            state: Checked or unchecked.
        """
        if self._chosen_option_id() == RefinementPipeline.CAMERA_ID:
            return
        count = self._groups_list.count()
        for row in range(count):
            item = self._groups_list.item(row)
            item.setCheckState(state)

    # ---------------------------------------------------------------- helpers

    def _chosen_option_id(self) -> str:
        """The id of the selected option.

        Returns:
            The id, or an empty text when no option is selected.
        """
        item = self._options_list.currentItem()
        if item is None:
            return ""
        return item.data(Qt.ItemDataRole.UserRole)

    def _select_option(self, option_id: str) -> None:
        """Select an option in the list, or the last one when it is gone.

        Args:
            option_id: Id of the option to select.
        """
        count = self._options_list.count()
        for row in range(count):
            item = self._options_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == option_id:
                self._options_list.setCurrentRow(row)
                return
        if count:
            self._options_list.setCurrentRow(count - 1)

    def _pick_photos(self, title: str) -> list[Path]:
        """Let the user pick photo files and darktable edits (.xmp files).

        Args:
            title: Title of the file dialog.

        Returns:
            The chosen files; empty when cancelled.
        """
        extensions = RAW_EXTENSIONS | IMAGE_EXTENSIONS | {".xmp"}
        file_filter = DropZone.file_filter("Photos and darktable edits", extensions)
        names, _chosen_filter = QFileDialog.getOpenFileNames(self, title, "", file_filter)
        return [Path(name) for name in names]
