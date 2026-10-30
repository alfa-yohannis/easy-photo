"""Step 4: the user adds references for each group; each one becomes a refinement option."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
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

    Each group has its own references: the user chooses a group in the
    "References for" box, and what they add becomes a refinement option for
    that group only. Choosing "All groups" adds an option for every group.
    Removing an option while a group is chosen takes it out of that group
    only. The unchanged photo is always an option.
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
            "Show the app what you like, group by group. Each reference becomes a refinement option that you "
            "compare on the group's photos in the next step. The unchanged photo is always one of the options.",
            parent,
        )
        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        target_row = self._make_target_row()
        layout.addLayout(target_row)
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
        controller.groups_changed.connect(self._refresh_targets)
        controller.option_groups_changed.connect(self._on_option_groups_changed)
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
        """Show the groups, their options, whether darktable-cli is there, and whether Claude can read words."""
        self._refresh_targets()
        self._refresh_darktable_note()
        self._refresh_ai_note()

    # ------------------------------------------------------------------ cards

    def _make_target_row(self) -> QHBoxLayout:
        """The row that chooses the group whose references are shown and added.

        Returns:
            The row.
        """
        label = self.make_label("References for", "SectionTitle")
        self._target = QComboBox()
        self._target.setMinimumWidth(320)
        self._target.currentIndexChanged.connect(self._on_target_changed)
        self._rename_button = self.make_button("Rename group…", self._rename_target)
        self._remove_group_button = self.make_button("Remove group…", self._remove_target)
        self._target_note = self.make_label("", "Muted")
        self._target_note.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(label)
        row.addWidget(self._target)
        row.addWidget(self._rename_button)
        row.addWidget(self._remove_group_button)
        row.addWidget(self._target_note, 1)
        return row

    def _rename_target(self) -> None:
        """Ask for a new name of the group chosen in "References for"."""
        group_id = self._target_group_id()
        if group_id is not None:
            self.ask_group_name(group_id)

    def _remove_target(self) -> None:
        """Ask to remove the group chosen in "References for"."""
        group_id = self._target_group_id()
        if group_id is not None:
            self.ask_to_remove_groups([group_id])

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
            "Photos you edited or like right now. A raw file you edited in darktable, or its .xmp sidecar, "
            "becomes your darktable edit, applied to every raw photo of the group. Other photos teach the "
            "app how bright you like them.",
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
        self._remove_button = self.make_button("Remove option", self._remove_option)
        remove_row = QHBoxLayout()
        remove_row.addStretch(1)
        remove_row.addWidget(self._remove_button)
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(options_title)
        layout.addWidget(self._options_list, 1)
        layout.addLayout(remove_row)
        return section

    # -------------------------------------------------------------- refreshes

    def _refresh_targets(self) -> None:
        """List "All groups" and every group in the "References for" box, keeping the chosen one.

        Until the user chooses, the first group is chosen, since each group has its own references.
        """
        previous = self._target.currentData()
        self._target.blockSignals(True)
        self._target.clear()
        self._target.addItem("All groups", "")
        project = self._controller.project
        groups = project.groups if project is not None else []
        for group in groups:
            photos_text = count_text(group.size, "photo")
            text = f"{group.title} ({photos_text}, {group.details})"
            self._target.addItem(text, group.id)
        index = -1
        if previous is not None:
            index = self._target.findData(previous)
        if index < 0:
            index = 1 if groups else 0
        self._target.setCurrentIndex(index)
        self._target.blockSignals(False)
        self._refresh_target_note()
        self._refresh_options()

    def _refresh_target_note(self) -> None:
        """Say who new references are for; only a single group can be renamed or removed."""
        project = self._controller.project
        has_groups = project is not None and bool(project.groups)
        group_chosen = self._target_group_id() is not None
        self._rename_button.setEnabled(group_chosen)
        self._remove_group_button.setEnabled(group_chosen)
        if not has_groups:
            text = "Make groups first. Until then every reference is for every group."
        elif self._target_group_id() is None:
            text = "New references are for every group."
        else:
            text = "New references are for this group only."
        self._target_note.setText(text)

    def _refresh_options(self) -> None:
        """Show the refinement options of the chosen group (or all of them), keeping the selected one."""
        chosen = self._chosen_option_id()
        group_id = self._target_group_id()
        self._options_list.blockSignals(True)
        self._options_list.clear()
        project = self._controller.project
        if project is not None:
            for option in project.pipelines:
                if group_id is not None and not project.option_used_in(group_id, option.id):
                    continue
                steps = option.describe_steps()
                scope = self._scope_text(option.id)
                text = f"{option.name}\n{steps}\n{scope}"
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, option.id)
                item.setToolTip(option.details)
                self._options_list.addItem(item)
        self._options_list.blockSignals(False)
        self._select_option(chosen)
        self._refresh_remove_button()
        self.readiness_changed.emit()

    def _scope_text(self, option_id: str) -> str:
        """Say which groups an option is for.

        Args:
            option_id: Id of the option.

        Returns:
            Text such as "For every group" or "For Group 2, Group 3".
        """
        project = self._controller.project
        groups = project.groups
        titles = [group.title for group in groups if project.option_used_in(group.id, option_id)]
        if len(titles) == len(groups):
            return "For every group"
        if not titles:
            return "For no group"
        joined = ", ".join(titles)
        return f"For {joined}"

    def _refresh_remove_button(self) -> None:
        """Name the remove button after what it does, and switch it off for the unchanged photo."""
        option_id = self._chosen_option_id()
        removable = bool(option_id) and option_id != RefinementPipeline.CAMERA_ID
        self._remove_button.setEnabled(removable)
        if self._target_group_id() is None:
            self._remove_button.setText("Remove option")
            return
        self._remove_button.setText("Remove from this group")

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
            text = (
                "Words the app does not know are read by Claude, through Claude Code. Only your words are sent, "
                "never your photos."
            )
        elif controller.ai_enabled:
            text = "Install Claude Code and log in to let Claude read any words, not only the app's own phrases."
        else:
            text = "Claude is switched off; only the app's own phrases are understood."
        self._ai_note.setText(text)

    # ---------------------------------------------------------------- actions

    def _on_target_changed(self, _index: int) -> None:
        """Show the options of the newly chosen group.

        Args:
            _index: Row of the chosen entry (read again through :meth:`_target_group_id`).
        """
        self._refresh_target_note()
        self._refresh_options()

    def _on_option_groups_changed(self, _group_id: str) -> None:
        """Show the options again after an option was taken out of a group.

        The refresh waits until the click that caused it is handled, because
        it rebuilds the list the click came from.

        Args:
            _group_id: Id of the group (not used; every option's text is made again).
        """
        QTimer.singleShot(0, self._refresh_options)

    def _add_history_folder(self) -> None:
        """Pick a folder of photos the user picked before."""
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder of photos you picked before")
        if folder:
            path = Path(folder)
            group_id = self._target_group_id()
            self._controller.add_history([path], group_id)

    def _add_history_files(self) -> None:
        """Pick photos the user picked before."""
        paths = self._pick_photos("Choose photos you picked before")
        group_id = self._target_group_id()
        self._controller.add_history(paths, group_id)

    def _add_examples(self) -> None:
        """Pick example files."""
        paths = self._pick_photos("Choose example photos or darktable edits")
        group_id = self._target_group_id()
        self._controller.add_examples(paths, group_id)

    def _search(self) -> None:
        """Search the internet for the phrase in the search box."""
        query = self._query.text()
        group_id = self._target_group_id()
        self._controller.search_internet(query, group_id)

    def _add_words(self) -> None:
        """Make an option from the typed words; the answer arrives in :meth:`_on_words_answered`."""
        text = self._words.text()
        if not text.strip():
            return
        self._show_words_note("Reading your words…", False)
        group_id = self._target_group_id()
        self._controller.add_words(text, group_id)

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
            "With Claude Code installed and logged in, Claude also reads anything else you type, in any language."
        )
        QMessageBox.information(self, "What can I type?", text)

    def _remove_option(self) -> None:
        """Take the selected option out of the chosen group, or remove it from every group under "All groups"."""
        option_id = self._chosen_option_id()
        if not option_id:
            return
        group_id = self._target_group_id()
        if group_id is None:
            self._controller.remove_pipeline(option_id)
            return
        self._controller.remove_option_from_group(group_id, option_id)

    def _on_option_chosen(self, _current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        """Update the remove button for the newly selected option.

        Args:
            _current: The selected item (read again through :meth:`_chosen_option_id`).
            _previous: The item selected before (not used).
        """
        self._refresh_remove_button()

    # ---------------------------------------------------------------- helpers

    def _target_group_id(self) -> str | None:
        """The group chosen in the "References for" box.

        Returns:
            Its id, or None for "All groups".
        """
        group_id = self._target.currentData()
        return group_id or None

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
