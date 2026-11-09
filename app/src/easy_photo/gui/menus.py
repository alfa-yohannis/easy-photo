"""The right-click menus of photos and of groups."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import QFileDialog, QMenu, QMessageBox, QWidget

from easy_photo.gui.controller import ProjectController
from easy_photo.gui.file_locations import FileLocations
from easy_photo.model.photo import RAW_EXTENSIONS, Photo
from easy_photo.model.quality import Decision
from easy_photo.wording import count_text


@dataclass(frozen=True)
class DecisionWords:
    """What a page calls keeping and setting aside photos, for the photo menu.

    The Filter step keeps and sets aside photos; the Group step selects and
    unselects them. Both are the same decision.
    """

    keep: str
    set_aside: str
    undo: str = ""
    """Words for going back to the app's own decision; empty leaves that item out."""


class ContextMenu(QMenu):
    """A right-click menu whose items each call a function. The photo and group menus build on it.

    An item that cannot be used now is shown greyed out, with the reason in
    brackets, so the user sees why. The menu also builds the "Apply sidecar
    to" and "Apply sidecar from" submenus both menus have.
    """

    DARKTABLE_MISSING = "darktable not found"
    SKIPPED = "skipped in Refine"
    FOLDER_WIDTH = 420
    """Widest the export folder may be in the "Export" submenu, in pixels."""

    MAX_LISTED_NAMES = 5
    """How many photo names the question before replacing edits lists."""

    def __init__(self, controller: ProjectController, parent: QWidget | None = None) -> None:
        """Create an empty menu.

        Args:
            controller: Does what the items ask for.
            parent: Qt parent widget; dialogs the items open belong to it.
        """
        super().__init__(parent)
        self._controller = controller
        self._locations = FileLocations()
        self._handlers: list[Callable[[], None]] = []
        # Only the top menu is connected: Qt sends the items of its submenus here too.
        self.triggered.connect(self._on_triggered)

    def add_item(self, text: str, handler: Callable[[], None], reason: str = "", into: QMenu | None = None) -> QAction:
        """Add an item that calls a function when chosen.

        Args:
            text: The item's text. A tab and a key after it show the key on the right.
            handler: Called when the item is chosen.
            reason: Why the item cannot be used now, for items without a key; empty when it can be used.
            into: The submenu the item goes into; None for this menu.

        Returns:
            The item.
        """
        menu = self if into is None else into
        shown = f"{text}  ({reason})" if reason else text
        action = menu.addAction(shown)
        number = len(self._handlers)
        action.setData(number)
        action.setEnabled(not reason)
        self._handlers.append(handler)
        return action

    def add_submenu(self, title: str, reason: str = "", into: QMenu | None = None) -> QMenu:
        """Add a submenu.

        Args:
            title: The submenu's title.
            reason: Why the submenu cannot be used now; empty when it can be used.
            into: The menu the submenu goes into; None for this menu.

        Returns:
            The submenu.
        """
        menu = self if into is None else into
        shown = f"{title}  ({reason})" if reason else title
        submenu = menu.addMenu(shown)
        title_action = submenu.menuAction()
        title_action.setEnabled(not reason)
        return submenu

    def add_header(self, text: str, into: QMenu | None = None) -> None:
        """Add a greyed-out line that says what the items below it act on.

        Args:
            text: The line.
            into: The submenu the line goes into; None for this menu.
        """
        menu = self if into is None else into
        header = menu.addAction(text)
        header.setEnabled(False)

    def item_texts(self) -> list[str]:
        """The texts of the menu's items, in order, without separators.

        Returns:
            The texts, submenu titles and greyed-out lines included.
        """
        actions = self.actions()
        return [action.text() for action in actions if action.text()]

    def darktable_reason(self) -> str:
        """Why "Open in darktable" cannot be used now.

        Returns:
            A short reason, or an empty text when darktable was found.
        """
        if self._controller.can_open_in_darktable:
            return ""
        return self.DARKTABLE_MISSING

    def add_apply_to_menu(self, source: Photo, home_group_id: str, home_text: str, extra: Sequence[tuple[str, Callable[[], None]]]) -> None:
        """Add "Apply sidecar to": a photo's darktable edit, for groups or photos to choose.

        Args:
            source: The photo whose sidecar holds the edit.
            home_group_id: The group the menu is about, offered first.
            home_text: The first item's text, such as "This group (Group 1)".
            extra: More targets, as (text, function) pairs, shown after the first.
        """
        reason = self._controller.edit_problem(source.id)
        submenu = self.add_submenu("Apply sidecar to", reason)
        if reason:
            return
        self.add_header(f"The edit of {source.name}", submenu)
        home_handler = partial(self._apply_to_groups, [home_group_id], source.path)
        self.add_item(home_text, home_handler, into=submenu)
        for text, handler in extra:
            self.add_item(text, handler, into=submenu)
        project = self._controller.project
        others = [group for group in project.groups if group.id != home_group_id]
        if others:
            another_menu = self.add_submenu("Another group", into=submenu)
            for group in others:
                handler = partial(self._apply_to_groups, [group.id], source.path)
                self.add_item(group.title, handler, into=another_menu)
        all_ids = [group.id for group in project.groups]
        all_handler = partial(self._apply_to_groups, all_ids, source.path)
        self.add_item("All groups", all_handler, into=submenu)

    def add_apply_from_menu(
        self,
        target_text: str,
        apply: Callable[[Path], None],
        except_group_ids: Sequence[str],
        except_photo_ids: Sequence[str],
        start_folder: Path,
    ) -> None:
        """Add "Apply sidecar from": a darktable edit to choose, from a group, a photo or a file.

        Args:
            target_text: What the edit goes to, such as "To Group 1".
            apply: Applies the chosen edit; it gets the raw or XMP file that holds it.
            except_group_ids: Groups not to offer as sources.
            except_photo_ids: Photos not to offer as sources.
            start_folder: Where the file dialog starts.
        """
        controller = self._controller
        submenu = self.add_submenu("Apply sidecar from")
        self.add_header(target_text, submenu)
        group_sources = controller.group_edit_sources(except_group_ids)
        groups_reason = "" if group_sources else "no edited preview yet"
        groups_menu = self.add_submenu("A group", groups_reason, submenu)
        for source in group_sources:
            handler = partial(apply, source.path)
            self.add_item(source.label, handler, into=groups_menu)
        photo_sources = controller.photo_edit_sources(except_photo_ids)
        photos_reason = "" if photo_sources else "no edited photo yet"
        photos_menu = self.add_submenu("A photo", photos_reason, submenu)
        for source in photo_sources:
            handler = partial(apply, source.path)
            self.add_item(source.label, handler, into=photos_menu)
        file_handler = partial(self._choose_file_to_apply, apply, start_folder)
        self.add_item("A file…", file_handler, into=submenu)

    def add_export_menu(self, targets: Sequence[tuple[str, Callable[[], None], str]]) -> None:
        """Add "Export": photos or groups to write now, with the settings of the Export step.

        Args:
            targets: The first items, as (text, function, reason) triples; a
                reason greys its item out. "All groups" comes after them.
        """
        controller = self._controller
        submenu = self.add_submenu("Export")
        folder = controller.export_folder
        folder_text = str(folder)
        metrics = submenu.fontMetrics()
        # A long folder is shortened in the middle, so the menu stays narrow.
        shown_folder = metrics.elidedText(folder_text, Qt.TextElideMode.ElideMiddle, self.FOLDER_WIDTH)
        self.add_header(f"To {shown_folder}", submenu)
        for text, handler, reason in targets:
            self.add_item(text, handler, reason, submenu)
        project = controller.project
        group_ids = [group.id for group in project.groups]
        all_reason = "" if group_ids else "no groups yet"
        all_handler = partial(controller.export_groups, group_ids)
        self.add_item("All groups", all_handler, all_reason, submenu)

    def skipped_reason(self, group_id: str) -> str:
        """Why a group cannot be exported, if it cannot.

        Args:
            group_id: Id of the group.

        Returns:
            "skipped in Refine" for a group the user skipped; otherwise an empty text.
        """
        if self._controller.is_skipped(group_id):
            return self.SKIPPED
        return ""

    def confirm_replacing(self, source: Path, photo_ids: Sequence[str]) -> bool:
        """Ask before an edit replaces the darktable edits photos hold of their own.

        Args:
            source: The file the edit comes from.
            photo_ids: The photos the edit would be written into.

        Returns:
            True when nothing of the user's would be replaced, or the user agreed.
        """
        names = self._controller.own_edit_names(photo_ids, source)
        if not names:
            return True
        count = len(names)
        shown = names[: self.MAX_LISTED_NAMES]
        listed = ", ".join(shown)
        if count > self.MAX_LISTED_NAMES:
            rest = count - self.MAX_LISTED_NAMES
            listed = f"{listed} and {rest} more"
        photos_text = count_text(count, "photo")
        text = (
            f"{photos_text} already hold a darktable edit of their own: {listed}.\n\n"
            f"Replace it with the edit of {source.name}? Their old sidecars are copied to the "
            'project\'s "sidecar backups" folder first.'
        )
        parent = self.parentWidget()
        buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        answer = QMessageBox.question(parent, "Apply sidecar", text, buttons, QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    @staticmethod
    def edit_file_filter() -> str:
        """The file dialog filter for darktable sidecars and raw files, in lower and upper case.

        Returns:
            Text such as "darktable sidecars and raw files (*.xmp *.XMP *.rw2 ...);;All files (*)".
        """
        extensions = sorted(RAW_EXTENSIONS)
        patterns = ["*.xmp", "*.XMP"]
        for extension in extensions:
            upper = extension.upper()
            patterns.append(f"*{extension}")
            patterns.append(f"*{upper}")
        joined = " ".join(patterns)
        return f"darktable sidecars and raw files ({joined});;All files (*)"

    def _apply_to_groups(self, group_ids: list[str], source: Path) -> None:
        """Write an edit into the photos of some groups, after asking when it would replace the user's own edits.

        Args:
            group_ids: Ids of the groups.
            source: The raw or XMP file that holds the edit.
        """
        photo_ids = self._controller.photos_of_groups(group_ids)
        if not self.confirm_replacing(source, photo_ids):
            return
        self._controller.apply_edit_to_groups(source, group_ids)

    def _apply_to_photos(self, photo_ids: list[str], source: Path) -> None:
        """Write an edit into single photos, after asking when it would replace the user's own edits.

        Args:
            photo_ids: Ids of the photos.
            source: The raw or XMP file that holds the edit.
        """
        if not self.confirm_replacing(source, photo_ids):
            return
        self._controller.apply_edit_to_photos(source, photo_ids)

    def _choose_file_to_apply(self, apply: Callable[[Path], None], start_folder: Path) -> None:
        """Let the user choose an XMP file, or a raw file they edited, and apply its edit.

        Args:
            apply: Applies the chosen edit.
            start_folder: Where the file dialog starts.
        """
        parent = self.parentWidget()
        file_filter = self.edit_file_filter()
        start_text = str(start_folder)
        name, _chosen_filter = QFileDialog.getOpenFileName(parent, "Apply the sidecar of", start_text, file_filter)
        if not name:
            return
        path = Path(name)
        apply(path)

    def _on_triggered(self, action: QAction) -> None:
        """Call the function of the chosen item.

        Args:
            action: The chosen item.
        """
        number = action.data()
        if number is None:
            return
        handler = self._handlers[number]
        handler()


class PhotoMenu(ContextMenu):
    """The right-click menu of a photo in a photo grid.

    Opening the photo, in darktable or with the system's program, and
    showing it in its folder act on the photo under the mouse; refreshing
    previews, copying paths, keeping and setting aside act on every chosen
    photo, as the keys do. "Export" writes the photo, the chosen photos, the
    photo's group or all groups. On the Group page the photo can also become
    its group's preview, its sidecar can be applied to groups or the other
    chosen photos, and another sidecar can be applied to the chosen photos.
    """

    KEEP_KEY = "K"
    SET_ASIDE_KEY = "X"
    UNDO_KEY = "U"

    def __init__(
        self,
        controller: ProjectController,
        photo_id: str,
        chosen_ids: Sequence[str],
        words: DecisionWords | None,
        group_id: str | None,
        parent: QWidget | None = None,
    ) -> None:
        """Create the menu.

        Args:
            controller: Does what the items ask for.
            photo_id: Id of the photo under the mouse; a photo's id is its file path.
            chosen_ids: Ids of the chosen photos, which the photo under the mouse is one of.
            words: What the page calls keeping and setting aside; None leaves those items out.
            group_id: The group the photo is shown in; None leaves the group items out.
            parent: Qt parent widget.
        """
        super().__init__(controller, parent)
        self._photo_id = photo_id
        self._chosen_ids = list(chosen_ids)
        self._group_id = group_id
        self._path = Path(photo_id)
        self._add_file_items()
        self._add_export_items()
        if words is not None:
            self.addSeparator()
            self._add_decision_items(words)
        project = controller.project
        photo = project.photo(photo_id) if project is not None else None
        if group_id and photo is not None:
            self.addSeparator()
            self._add_group_items(photo)

    def _add_file_items(self) -> None:
        """The items that open the photo, refresh the chosen photos' previews, show the photo in its folder, and copy paths."""
        reason = self.darktable_reason()
        self.add_item("Open in darktable", self._open_in_darktable, reason)
        self._add_refresh_item()
        self.add_item("Open the file", self._open_file)
        self.add_item("Show in folder", self._show_in_folder)
        count = len(self._chosen_ids)
        copy_text = "Copy path" if count == 1 else f"Copy {count} paths"
        self.add_item(copy_text, self._copy_paths)

    def _add_refresh_item(self) -> None:
        """The item that develops the chosen raw photos' previews with darktable, so they show their sidecars."""
        controller = self._controller
        count = len(self._chosen_ids)
        raw_count = controller.raw_count(self._chosen_ids)
        if raw_count > 1:
            refresh_text = f"Refresh {raw_count} previews"
        elif raw_count == 0 and count > 1:
            refresh_text = "Refresh previews"
        else:
            refresh_text = "Refresh preview"
        reason = controller.refresh_problem(self._chosen_ids)
        self.add_item(refresh_text, self._refresh_previews, reason)

    def _add_export_items(self) -> None:
        """The "Export" submenu: the photo, the chosen photos, the photo's group, or all groups."""
        controller = self._controller
        name = self._path.name
        photo_handler = partial(controller.export_photos, [self._photo_id])
        targets: list[tuple[str, Callable[[], None], str]] = [(f"This photo ({name})", photo_handler, "")]
        count = len(self._chosen_ids)
        if count > 1:
            chosen_handler = partial(controller.export_photos, self._chosen_ids)
            targets.append((f"The {count} selected photos", chosen_handler, ""))
        group = controller.group_of_photo(self._photo_id)
        if group is not None:
            group_reason = self.skipped_reason(group.id)
            group_handler = partial(controller.export_groups, [group.id])
            targets.append((f"Its group ({group.title})", group_handler, group_reason))
        self.add_export_menu(targets)

    def _add_decision_items(self, words: DecisionWords) -> None:
        """The items that keep, set aside, or give back to the app the chosen photos.

        Args:
            words: What the page calls these decisions.
        """
        count = len(self._chosen_ids)
        photos_text = count_text(count, "photo")
        keep_text = words.keep if count == 1 else f"{words.keep} {photos_text}"
        set_aside_text = words.set_aside if count == 1 else f"{words.set_aside} {photos_text}"
        self.add_item(f"{keep_text}\t{self.KEEP_KEY}", self._keep)
        self.add_item(f"{set_aside_text}\t{self.SET_ASIDE_KEY}", self._set_aside)
        if words.undo:
            undo_text = words.undo if count == 1 else f"{words.undo} for {photos_text}"
            self.add_item(f"{undo_text}\t{self.UNDO_KEY}", self._undo)

    def _add_group_items(self, photo: Photo) -> None:
        """The items about the photo's group: the preview, and applying sidecars to and from the photo.

        Args:
            photo: The photo under the mouse.
        """
        controller = self._controller
        project = controller.project
        decision = project.decision_of(self._photo_id)
        selected = decision is not None and decision.is_kept
        preview_reason = "" if selected else "select it first"
        preview_action = self.add_item("Use as the group's preview", self._use_as_preview, preview_reason)
        sample = controller.sample_photo(self._group_id)
        if sample is not None and sample.id == self._photo_id:
            preview_action.setCheckable(True)
            preview_action.setChecked(True)
            preview_action.setEnabled(False)
        group = project.group(self._group_id)
        group_title = group.title if group is not None else "its group"
        others = [photo_id for photo_id in self._chosen_ids if photo_id != self._photo_id]
        extra: list[tuple[str, Callable[[], None]]] = []
        if others:
            other_count = len(others)
            others_text = "The other selected photo" if other_count == 1 else f"The {other_count} other selected photos"
            others_handler = partial(self._apply_to_photos, others, photo.path)
            extra.append((others_text, others_handler))
        self.add_apply_to_menu(photo, self._group_id, f"Its group ({group_title})", extra)
        count = len(self._chosen_ids)
        target_text = f"To {photo.name}" if count == 1 else f"To the {count} selected photos"
        apply = partial(self._apply_to_photos, self._chosen_ids)
        folder = self._path.parent
        self.add_apply_from_menu(target_text, apply, [], [self._photo_id], folder)
        applied = [photo_id for photo_id in self._chosen_ids if project.photo_edit_of(photo_id) is not None]
        if applied:
            self.add_item("Follow the group's pick again", self._follow_group_pick)

    def _open_in_darktable(self) -> None:
        """Open the photo in darktable."""
        self._controller.open_in_darktable(self._photo_id)

    def _refresh_previews(self) -> None:
        """Develop the chosen photos' previews with their sidecars."""
        self._controller.refresh_previews(self._chosen_ids)

    def _open_file(self) -> None:
        """Open the photo with the program the system uses for it."""
        self._locations.open_file(self._path)

    def _show_in_folder(self) -> None:
        """Show the photo in its folder in the file manager."""
        self._locations.show_in_folder(self._path)

    def _copy_paths(self) -> None:
        """Put the chosen photos' paths on the clipboard, one per line."""
        text = "\n".join(self._chosen_ids)
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(text)

    def _keep(self) -> None:
        """Keep (select) the chosen photos."""
        self._controller.decide(self._chosen_ids, Decision.KEEP)

    def _set_aside(self) -> None:
        """Set aside (unselect) the chosen photos."""
        self._controller.decide(self._chosen_ids, Decision.SET_ASIDE)

    def _undo(self) -> None:
        """Go back to the app's own decision for the chosen photos."""
        self._controller.decide(self._chosen_ids, None)

    def _use_as_preview(self) -> None:
        """Let the photo stand for its group."""
        self._controller.choose_sample(self._group_id, self._photo_id)

    def _follow_group_pick(self) -> None:
        """Let the chosen photos follow their group's pick again, after a sidecar was applied to them alone."""
        self._controller.remove_photo_edits(self._chosen_ids)


class GroupMenu(ContextMenu):
    """The right-click menu of a group in a group list.

    The group's preview, the photo that stands for the group, is the photo
    the menu opens and whose sidecar it applies. Selecting, unselecting,
    refreshing previews, merging and removing act on every chosen group, and
    so does "Apply sidecar from"; the other items act on the group under the
    mouse. Refreshing develops the pictures of all the groups' photos with
    their sidecars, the groups' previews first. "Export" writes the selected
    photos of this group, of the chosen groups, or of all groups. Renaming,
    merging and removing ask the user first, so the page does them when the
    menu sends ``rename_requested``, ``merge_requested`` or ``remove_requested``.
    """

    rename_requested = Signal(str)
    """The user wants to rename the group with this id."""

    remove_requested = Signal(list)
    """The user wants to remove the groups with these ids."""

    merge_requested = Signal(list)
    """The user wants to put the groups with these ids together into one."""

    def __init__(
        self,
        controller: ProjectController,
        group_id: str,
        chosen_ids: Sequence[str],
        parent: QWidget | None = None,
    ) -> None:
        """Create the menu.

        Args:
            controller: Does what the items ask for.
            group_id: Id of the group under the mouse.
            chosen_ids: Ids of the chosen groups, which the group under the mouse is one of.
            parent: Qt parent widget.
        """
        super().__init__(controller, parent)
        self._group_id = group_id
        self._chosen_ids = list(chosen_ids)
        self._preview = controller.sample_photo(group_id)
        if self._preview is not None:
            self._add_preview_items()
            self.addSeparator()
        self._add_selection_items()
        self.addSeparator()
        self._add_export_items()
        self.addSeparator()
        self._add_group_items()

    def _add_preview_items(self) -> None:
        """The items about the group's preview, and applying sidecars to and from the group."""
        preview = self._preview
        # A greyed-out item names the preview; the app's style sheet does not draw section titles.
        self.add_header(f"Preview: {preview.name}")
        reason = self.darktable_reason()
        self.add_item("Open in darktable", self._open_in_darktable, reason)
        self.add_item("Open the file", self._open_file)
        self.add_item("Show in folder", self._show_in_folder)
        project = self._controller.project
        group = project.group(self._group_id)
        extra: list[tuple[str, Callable[[], None]]] = []
        count = len(self._chosen_ids)
        if count > 1:
            chosen_handler = partial(self._apply_to_groups, self._chosen_ids, preview.path)
            extra.append((f"The {count} selected groups", chosen_handler))
        self.add_apply_to_menu(preview, self._group_id, f"This group ({group.title})", extra)
        target_text = f"To {group.title}" if count == 1 else f"To the {count} selected groups"
        apply = partial(self._apply_to_groups, self._chosen_ids)
        folder = preview.path.parent
        self.add_apply_from_menu(target_text, apply, self._chosen_ids, [], folder)
        self._add_refresh_item()
        if project.chosen_sample_of(self._group_id) is not None:
            self.add_item("Choose the preview automatically", self._choose_preview_automatically)

    def _add_refresh_item(self) -> None:
        """The item that develops the previews of the chosen groups' photos with darktable, so they show their sidecars."""
        count = len(self._chosen_ids)
        refresh_text = "Refresh previews" if count == 1 else f"Refresh previews of {count} groups"
        photo_ids = self._controller.photos_of_groups(self._chosen_ids)
        reason = self._controller.refresh_problem(photo_ids)
        self.add_item(refresh_text, self._refresh_previews, reason)

    def _add_selection_items(self) -> None:
        """The items that select or unselect every photo of the chosen groups."""
        count = len(self._chosen_ids)
        if count == 1:
            select_text = "Select all photos"
            unselect_text = "Unselect all photos"
        else:
            groups_text = count_text(count, "group")
            select_text = f"Select all photos of {groups_text}"
            unselect_text = f"Unselect all photos of {groups_text}"
        self.add_item(select_text, self._select_all)
        self.add_item(unselect_text, self._unselect_all)

    def _add_export_items(self) -> None:
        """The "Export" submenu: this group, the chosen groups, or all groups."""
        controller = self._controller
        project = controller.project
        group = project.group(self._group_id)
        title = group.title if group is not None else "this group"
        this_reason = self.skipped_reason(self._group_id)
        this_handler = partial(controller.export_groups, [self._group_id])
        targets: list[tuple[str, Callable[[], None], str]] = [(f"This group ({title})", this_handler, this_reason)]
        count = len(self._chosen_ids)
        if count > 1:
            exported = [group_id for group_id in self._chosen_ids if not controller.is_skipped(group_id)]
            chosen_reason = "" if exported else "all skipped in Refine"
            chosen_handler = partial(controller.export_groups, self._chosen_ids)
            targets.append((f"The {count} selected groups", chosen_handler, chosen_reason))
        self.add_export_menu(targets)

    def _add_group_items(self) -> None:
        """The items that rename the group, merge the chosen groups, and remove them."""
        self.add_item("Rename group…", self._rename)
        count = len(self._chosen_ids)
        if count > 1:
            self.add_item(f"Merge {count} groups…", self._merge)
        else:
            self.add_item("Merge groups…", self._merge, "select two or more")
        remove_text = "Remove group…" if count == 1 else f"Remove {count} groups…"
        self.add_item(remove_text, self._remove)

    def _open_in_darktable(self) -> None:
        """Open the group's preview in darktable."""
        self._controller.open_in_darktable(self._preview.id)

    def _open_file(self) -> None:
        """Open the group's preview with the program the system uses for it."""
        self._locations.open_file(self._preview.path)

    def _show_in_folder(self) -> None:
        """Show the group's preview in its folder in the file manager."""
        self._locations.show_in_folder(self._preview.path)

    def _refresh_previews(self) -> None:
        """Develop the previews of the chosen groups' photos with their sidecars."""
        self._controller.refresh_group_previews(self._chosen_ids)

    def _choose_preview_automatically(self) -> None:
        """Let the app choose the group's preview again: a photo the user edited, or the sharpest."""
        self._controller.choose_sample(self._group_id, None)

    def _select_all(self) -> None:
        """Select every photo of the chosen groups."""
        self._select_groups(True)

    def _unselect_all(self) -> None:
        """Unselect every photo of the chosen groups."""
        self._select_groups(False)

    def _select_groups(self, selected: bool) -> None:
        """Select or unselect every photo of the chosen groups.

        Args:
            selected: True to select, False to unselect.
        """
        photo_ids = self._controller.photos_of_groups(self._chosen_ids)
        if photo_ids:
            self._controller.select_photos(photo_ids, selected)

    def _rename(self) -> None:
        """Ask the page to rename the group."""
        self.rename_requested.emit(self._group_id)

    def _remove(self) -> None:
        """Ask the page to remove the chosen groups."""
        self.remove_requested.emit(self._chosen_ids)

    def _merge(self) -> None:
        """Ask the page to merge the chosen groups."""
        self.merge_requested.emit(self._chosen_ids)
