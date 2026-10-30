"""Step 3: the kept photos are put into groups that get the same refinement."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QRadioButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from easy_photo.gui.controller import ProjectController
from easy_photo.gui.pages.base_page import WorkflowPage
from easy_photo.gui.photo_model import PhotoListModel
from easy_photo.gui.style import AppStyle
from easy_photo.gui.widgets.photo_grid import PhotoGrid
from easy_photo.settings import GroupSettings
from easy_photo.wording import count_text


class GroupPage(WorkflowPage):
    """Step 3: the kept photos are grouped by how alike they look, or by the people in them."""

    GROUP_ICON = QSize(96, 72)
    FACE_ICON = QSize(56, 56)

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
            "Group",
            "Photos that belong together get the same refinement. Group them by how alike they look and when "
            "they were taken, or by the people in them (the app finds and recognizes the faces).",
            parent,
        )
        self._model = PhotoListModel(controller, self)
        self._filling = False
        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        options = self._make_options_row()
        self._faces_row = self._make_faces_row(content)
        splitter = self._make_main_area(content)
        layout.addLayout(options)
        layout.addWidget(self._faces_row)
        layout.addWidget(splitter, 1)
        self.set_content(content)
        self._add_shortcuts()
        controller.project_opened.connect(self.on_shown)
        controller.groups_changed.connect(self._refresh_groups)
        controller.faces_changed.connect(self._on_faces_changed)
        controller.photo_updated.connect(self._model.refresh_photo)
        controller.analysis_changed.connect(self._on_selection_changed)

    def is_ready(self) -> bool:
        """The user can go on once there are groups.

        Returns:
            True when the photos are grouped.
        """
        project = self._controller.project
        return project is not None and bool(project.groups)

    def status_text(self) -> str:
        """The number of groups.

        Returns:
            Text such as "31 groups".
        """
        project = self._controller.project
        if project is None or not project.groups:
            return "Not grouped yet"
        group_count = len(project.groups)
        return count_text(group_count, "group")

    def on_shown(self) -> None:
        """Show the project's options and groups; make groups when there are none yet."""
        project = self._controller.project
        if project is None:
            return
        self._show_options(project.grouping)
        self._refresh_groups()
        self._on_faces_changed()
        kept = project.kept_photos()
        if not project.groups and kept and not project.grouping.by_people:
            self._make_groups()

    # ----------------------------------------------------------------- layout

    def _make_options_row(self) -> QHBoxLayout:
        """The row with the grouping mode, its options and the Make groups button.

        Returns:
            The row.
        """
        self._by_similarity = QRadioButton("Similar photos")
        self._by_people = QRadioButton("Same people")
        mode_group = QButtonGroup(self)
        mode_group.addButton(self._by_similarity)
        mode_group.addButton(self._by_people)
        self._by_similarity.setChecked(True)
        self._by_people.toggled.connect(self._on_mode_changed)
        self._gap = QSpinBox()
        self._gap.setRange(1, 600)
        self._gap.setSuffix(" min")
        self._gap.setToolTip("Longest pause between two photos of the same group")
        self._similarity = QSlider(Qt.Orientation.Horizontal)
        self._similarity.setRange(0, 100)
        self._similarity.setFixedWidth(150)
        self._similarity.setToolTip("How alike two neighbouring photos must look to share a group")
        self._similarity_value = self.make_label("", "Muted")
        self._similarity.valueChanged.connect(self._show_similarity)
        self._gap_label = self.make_label("Longest pause")
        self._similarity_label = self.make_label("Alike at least")
        make_button = self.make_button("Make groups", self._make_groups, primary=True)
        mode_label = self.make_label("Group by:")
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(mode_label)
        row.addWidget(self._by_similarity)
        row.addWidget(self._by_people)
        row.addSpacing(18)
        row.addWidget(self._gap_label)
        row.addWidget(self._gap)
        row.addSpacing(10)
        row.addWidget(self._similarity_label)
        row.addWidget(self._similarity)
        row.addWidget(self._similarity_value)
        row.addStretch(1)
        row.addWidget(make_button)
        return row

    def _make_faces_row(self, parent: QWidget) -> QWidget:
        """The row about faces: what was found, and buttons to find faces or get the models.

        Args:
            parent: The content widget.

        Returns:
            The row, shown only when grouping by people.
        """
        row_widget = QWidget(parent)
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)
        self._faces_status = self.make_label("", "Muted")
        self._find_button = self.make_button("Find faces", self._find_faces)
        self._download_button = self.make_button("Download face models (40 MB)", self._controller.download_face_models)
        self._folder_button = self.make_button("Choose models folder…", self._choose_models_folder)
        row.addWidget(self._faces_status, 1)
        row.addWidget(self._find_button)
        row.addWidget(self._download_button)
        row.addWidget(self._folder_button)
        row_widget.setVisible(False)
        return row_widget

    def _make_main_area(self, parent: QWidget) -> QSplitter:
        """The group list, the photos of the chosen group, and the people list.

        Args:
            parent: The content widget.

        Returns:
            The splitter that holds the three parts.
        """
        splitter = QSplitter(Qt.Orientation.Horizontal, parent)
        groups_column = self._make_groups_column(splitter)
        photos_column = self._make_photos_column(splitter)
        self._people_panel = self._make_people_panel(splitter)
        splitter.addWidget(groups_column)
        splitter.addWidget(photos_column)
        splitter.addWidget(self._people_panel)
        splitter.setStretchFactor(1, 1)
        return splitter

    def _make_groups_column(self, parent: QWidget) -> QWidget:
        """The group list, with buttons to rename the chosen group and to remove the selected groups.

        A group is renamed with F2 or a double click too, and removed with the Delete key.
        Ctrl and Shift select several groups to remove at once.

        Args:
            parent: The splitter.

        Returns:
            The column.
        """
        column = QWidget(parent)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._groups_list = QListWidget(column)
        self._groups_list.setIconSize(self.GROUP_ICON)
        self._groups_list.setMinimumWidth(280)
        self._groups_list.setWordWrap(True)
        self._groups_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._groups_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._groups_list.currentItemChanged.connect(self._on_group_chosen)
        self._groups_list.itemDoubleClicked.connect(self._rename_chosen_group)
        delete_key = QKeySequence(QKeySequence.StandardKey.Delete)
        delete_shortcut = QShortcut(delete_key, self._groups_list)
        delete_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete_shortcut.activated.connect(self._remove_selected_groups)
        rename_button = self.make_button("Rename group…   (F2)", self._rename_chosen_group)
        remove_button = self.make_button("Remove…", self._remove_selected_groups)
        remove_button.setToolTip("Remove the selected groups. Their photos stay in the project but are not exported.")
        buttons = QHBoxLayout()
        buttons.addWidget(rename_button, 1)
        buttons.addWidget(remove_button)
        layout.addWidget(self._groups_list, 1)
        layout.addLayout(buttons)
        return column

    def _rename_chosen_group(self) -> None:
        """Ask for a new name of the chosen group."""
        group_id = self._chosen_group_id()
        self.ask_group_name(group_id)

    def _remove_selected_groups(self) -> None:
        """Ask to remove the selected groups, or the chosen group when none is selected."""
        items = self._groups_list.selectedItems()
        group_ids = [item.data(Qt.ItemDataRole.UserRole) for item in items]
        if not group_ids:
            chosen = self._chosen_group_id()
            group_ids = [chosen] if chosen else []
        self.ask_to_remove_groups(group_ids)

    def _make_photos_column(self, parent: QWidget) -> QWidget:
        """The photos of the chosen group, with buttons to select and unselect them.

        Unselected photos are set aside: they stay in the group but are not exported.

        Args:
            parent: The splitter.

        Returns:
            The column.
        """
        column = QWidget(parent)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._selection_note = self.make_label("", "Muted")
        select_button = self.make_button("Select   (K)", self._select_chosen)
        unselect_button = self.make_button("Unselect   (X)", self._unselect_chosen)
        select_all_button = self.make_button("Select all", self._select_whole_group)
        unselect_all_button = self.make_button("Unselect all", self._unselect_whole_group)
        unselect_button.setToolTip("Unselected photos stay in the group but are not exported.")
        row = QHBoxLayout()
        row.addWidget(self._selection_note, 1)
        row.addWidget(select_button)
        row.addWidget(unselect_button)
        row.addSpacing(10)
        row.addWidget(select_all_button)
        row.addWidget(unselect_all_button)
        self._grid = PhotoGrid(self._model, self._style, column)
        layout.addLayout(row)
        layout.addWidget(self._grid, 1)
        return column

    def _add_shortcuts(self) -> None:
        """K selects and X unselects the chosen photos, as in the Filter step; F2 renames the chosen group."""
        keys = (("K", self._select_chosen), ("X", self._unselect_chosen), ("F2", self._rename_chosen_group))
        for key, handler in keys:
            sequence = QKeySequence(key)
            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(handler)

    def _make_people_panel(self, parent: QWidget) -> QWidget:
        """The list of people found, with renaming and merging.

        Args:
            parent: The splitter.

        Returns:
            The panel, shown only when grouping by people.
        """
        panel = QWidget(parent)
        panel.setMinimumWidth(240)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        title = self.make_label("People", "SectionTitle")
        hint = self.make_label(
            "Double-click a name to change it. If one person appears twice, select both and merge them.",
            "Muted",
        )
        hint.setWordWrap(True)
        self._people_list = QListWidget(panel)
        self._people_list.setIconSize(self.FACE_ICON)
        self._people_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._people_list.itemChanged.connect(self._on_person_renamed)
        merge_button = self.make_button("Merge selected", self._merge_selected)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self._people_list, 1)
        layout.addWidget(merge_button)
        panel.setVisible(False)
        return panel

    # ---------------------------------------------------------------- options

    def _show_options(self, grouping: GroupSettings) -> None:
        """Show a project's grouping options.

        Args:
            grouping: The options.
        """
        self._by_people.setChecked(grouping.by_people)
        self._by_similarity.setChecked(not grouping.by_people)
        gap = round(grouping.max_gap_minutes)
        self._gap.setValue(gap)
        similarity = round(grouping.min_similarity * 100)
        self._similarity.setValue(similarity)
        self._show_similarity(similarity)
        self._on_mode_changed(grouping.by_people)

    def _options(self) -> GroupSettings:
        """The options set in the row.

        Returns:
            The grouping options.
        """
        by_people = self._by_people.isChecked()
        gap_minutes = self._gap.value() * 1.0
        similarity = self._similarity.value() / 100.0
        return GroupSettings(by_people, gap_minutes, similarity)

    def _show_similarity(self, value: int) -> None:
        """Write the similarity next to its slider.

        Args:
            value: The similarity in percent.
        """
        self._similarity_value.setText(f"{value} %")

    def _on_mode_changed(self, by_people: bool) -> None:
        """Show the options that belong to the chosen mode.

        Args:
            by_people: True when grouping by people.
        """
        for widget in (self._gap_label, self._gap, self._similarity_label, self._similarity, self._similarity_value):
            widget.setVisible(not by_people)
        self._faces_row.setVisible(by_people)
        self._people_panel.setVisible(by_people)

    def _make_groups(self) -> None:
        """Group the kept photos with the options in the row."""
        options = self._options()
        self._controller.make_groups(options)

    # ----------------------------------------------------------------- groups

    def _refresh_groups(self) -> None:
        """Show the project's groups, keeping the chosen group when it still exists."""
        project = self._controller.project
        chosen = self._chosen_group_id()
        self._groups_list.clear()
        if project is None:
            self._model.set_photo_ids([])
            return
        for group in project.groups:
            text = self._group_text(group.id)
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, group.id)
            icon = self._group_icon(group.id)
            item.setIcon(icon)
            self._groups_list.addItem(item)
        self._choose_row_of(chosen)
        self.readiness_changed.emit()

    def _choose_row_of(self, group_id: str) -> None:
        """Select a group in the list, or the first group.

        Args:
            group_id: Id of the group to select; empty for the first.
        """
        count = self._groups_list.count()
        if count == 0:
            self._model.set_photo_ids([])
            return
        for row in range(count):
            item = self._groups_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == group_id:
                self._groups_list.setCurrentRow(row)
                return
        self._groups_list.setCurrentRow(0)

    def _chosen_group_id(self) -> str:
        """The id of the selected group.

        Returns:
            The id, or an empty text.
        """
        item = self._groups_list.currentItem()
        if item is None:
            return ""
        return item.data(Qt.ItemDataRole.UserRole)

    def _on_group_chosen(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        """Show the photos of the chosen group.

        Args:
            current: The chosen item.
            _previous: The item chosen before (not used).
        """
        project = self._controller.project
        if project is None or current is None:
            self._model.set_photo_ids([])
            return
        group_id = current.data(Qt.ItemDataRole.UserRole)
        group = project.group(group_id)
        photo_ids = [] if group is None else list(group.photo_ids)
        self._model.set_photo_ids(photo_ids)
        self._refresh_selection_note()

    def _group_text(self, group_id: str) -> str:
        """The list text of a group: its title, how many of its photos are selected, and when.

        Args:
            group_id: Id of the group.

        Returns:
            Two or three lines of text.
        """
        project = self._controller.project
        group = project.group(group_id)
        selection = self._selection_text(group_id)
        lines = [group.title, selection]
        if group.details:
            lines.append(group.details)
        return "\n".join(lines)

    def _selection_text(self, group_id: str) -> str:
        """Say how many photos of a group are selected.

        Args:
            group_id: Id of the group.

        Returns:
            Text such as "15 photos" when all are selected, or "12 of 15 selected".
        """
        project = self._controller.project
        group = project.group(group_id)
        selected = 0
        for photo_id in group.photo_ids:
            decision = project.decision_of(photo_id)
            if decision is not None and decision.is_kept:
                selected += 1
        if selected == group.size:
            return count_text(group.size, "photo")
        return f"{selected} of {group.size} selected"

    def _refresh_selection_note(self) -> None:
        """Write how many photos of the chosen group are selected, above its photos."""
        group_id = self._chosen_group_id()
        project = self._controller.project
        if project is None or not group_id or project.group(group_id) is None:
            self._selection_note.setText("")
            return
        selection = self._selection_text(group_id)
        self._selection_note.setText(f"{selection}. Unselected photos are not exported.")

    def _on_selection_changed(self) -> None:
        """Update the group texts and pictures after photos were selected or unselected."""
        project = self._controller.project
        if project is None:
            return
        count = self._groups_list.count()
        for row in range(count):
            item = self._groups_list.item(row)
            group_id = item.data(Qt.ItemDataRole.UserRole)
            if project.group(group_id) is None:
                continue
            text = self._group_text(group_id)
            item.setText(text)
            icon = self._group_icon(group_id)
            item.setIcon(icon)
        self._refresh_selection_note()

    def _group_icon(self, group_id: str) -> QIcon:
        """The picture of a group in the list: the sharpest of its selected photos, as in the Refine step.

        Args:
            group_id: Id of the group.

        Returns:
            The icon; empty while the photo's thumbnail is not read yet.
        """
        sample = self._controller.sample_photo(group_id)
        image = self._controller.thumbnail(sample.id) if sample is not None else None
        return self._icon(image, self.GROUP_ICON)

    def _select_chosen(self) -> None:
        """Select the chosen photos."""
        self._select_photos(True)

    def _unselect_chosen(self) -> None:
        """Unselect the chosen photos."""
        self._select_photos(False)

    def _select_photos(self, selected: bool) -> None:
        """Select or unselect the photos chosen in the grid (or the current one).

        Args:
            selected: True to select, False to unselect.
        """
        photo_ids = self._grid.selected_photo_ids()
        if not photo_ids:
            current = self._grid.current_photo_id()
            photo_ids = [current] if current else []
        if photo_ids:
            self._controller.select_photos(photo_ids, selected)

    def _select_whole_group(self) -> None:
        """Select every photo of the chosen group."""
        self._select_group(True)

    def _unselect_whole_group(self) -> None:
        """Unselect every photo of the chosen group."""
        self._select_group(False)

    def _select_group(self, selected: bool) -> None:
        """Select or unselect every photo of the chosen group.

        Args:
            selected: True to select, False to unselect.
        """
        project = self._controller.project
        group_id = self._chosen_group_id()
        group = project.group(group_id) if project is not None and group_id else None
        if group is not None:
            self._controller.select_photos(group.photo_ids, selected)

    # ------------------------------------------------------------------ faces

    def _on_faces_changed(self) -> None:
        """Update the faces row and the people list."""
        self._refresh_faces_row()
        self._refresh_people()

    def _refresh_faces_row(self) -> None:
        """Say how many photos were searched for faces, and show the buttons that make sense."""
        project = self._controller.project
        available = self._controller.faces_available
        self._download_button.setVisible(not available)
        self._folder_button.setVisible(not available)
        self._find_button.setEnabled(available)
        if not available:
            folder = self._controller.models_folder
            self._faces_status.setText(f"The face models are not in {folder}. Download them once, or choose their folder.")
            return
        if project is None:
            return
        kept = project.kept_photos()
        searched = 0
        for photo in kept:
            if project.faces_searched(photo.id):
                searched += 1
        people_count = len(project.people)
        kept_count = len(kept)
        people_text = count_text(people_count, "person", "people")
        kept_text = count_text(kept_count, "kept photo")
        self._faces_status.setText(f"Faces searched in {searched} of {kept_text}; {people_text} found.")

    def _refresh_people(self) -> None:
        """Show the people found, each with a face picture."""
        project = self._controller.project
        self._filling = True
        self._people_list.clear()
        if project is not None:
            for person in project.people:
                item = QListWidgetItem(person.name)
                item.setData(Qt.ItemDataRole.UserRole, person.id)
                flags = item.flags()
                item.setFlags(flags | Qt.ItemFlag.ItemIsEditable)
                item.setToolTip(f"{person.face_count} faces")
                face = person.sample_face
                if face is not None:
                    image = self._controller.face_image(face)
                    icon = self._icon(image, self.FACE_ICON)
                    item.setIcon(icon)
                self._people_list.addItem(item)
        self._filling = False

    def _on_person_renamed(self, item: QListWidgetItem) -> None:
        """Give a person the name the user typed.

        Args:
            item: The edited list item.
        """
        if self._filling:
            return
        person_id = item.data(Qt.ItemDataRole.UserRole)
        name = item.text()
        self._controller.rename_person(person_id, name)

    def _merge_selected(self) -> None:
        """Merge the selected people into the first of them."""
        items = self._people_list.selectedItems()
        person_ids = [item.data(Qt.ItemDataRole.UserRole) for item in items]
        self._controller.merge_people(person_ids)

    def _find_faces(self) -> None:
        """Look for faces, then group by people."""
        self._by_people.setChecked(True)
        options = self._options()
        self._controller.make_groups(options)

    def _choose_models_folder(self) -> None:
        """Let the user pick the folder that holds the face model files."""
        folder = QFileDialog.getExistingDirectory(self, "Choose the folder with the face models")
        if folder:
            path = Path(folder)
            self._controller.set_models_folder(path)

    # ---------------------------------------------------------------- helpers

    def _icon(self, image: QImage | None, size: QSize) -> QIcon:
        """Make a list icon from a picture.

        Args:
            image: The picture, or None for an empty icon.
            size: The icon size.

        Returns:
            The icon.
        """
        if image is None or image.isNull():
            return QIcon()
        pixmap = QPixmap.fromImage(image)
        scaled = pixmap.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        return QIcon(scaled)
