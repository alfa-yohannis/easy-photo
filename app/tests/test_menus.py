"""Tests of the right-click menus of photos and groups, and of what their items ask the controller to do.

darktable is replaced by stand-ins, so these tests run on computers without
darktable, and no darktable window opens.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

import pytest
from PySide6.QtGui import QAction, QGuiApplication, QImage
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox

from easy_photo.gui.controller import ProjectController
from easy_photo.gui.menus import DecisionWords, GroupMenu, PhotoMenu
from easy_photo.gui.pages.base_page import WorkflowPage
from easy_photo.gui.style import AppStyle
from easy_photo.model.group import PhotoGroup
from easy_photo.model.photo import FileKind, Photo
from easy_photo.model.project import Project
from easy_photo.model.quality import Decision
from easy_photo.refinement.pipeline import PipelineSource, RefinementPipeline
from easy_photo.services.app_services import AppServices
from easy_photo.services.darktable import DarktableLauncher, DarktableRenderer
from easy_photo.services.darktable_edit import DarktableEdit
from easy_photo.services.developer import PhotoDeveloper
from easy_photo.services.exporter import ExportResult, ExportStatus, Exporter
from easy_photo.services.thumbnails import DevelopedThumbnails
from easy_photo.settings import AppFolders, AppSettings, SettingsStore
from tests.conftest import wait_until
from tests.test_darktable import StandInRenderer, blend_text, write_sidecar

EDITED_HASHES = 'darktable:history_auto_hash="aaaa" darktable:history_current_hash="bbbb"'
"""Hashes that tell darktable's history apart from the user's: the user edited the photo."""

GROUP_WORDS = DecisionWords("Select", "Unselect")


class StandInLauncher(DarktableLauncher):
    """Stands in for darktable: remembers the photos it was asked to open, and opens no window."""

    def __init__(self) -> None:
        """Create a stand-in that counts as installed."""
        program = Path("darktable")
        super().__init__(program)
        self.opened: list[Path] = []

    def open(self, photo: Path) -> None:
        """Remember the photo instead of starting darktable.

        Args:
            photo: The photo file.
        """
        self.opened.append(photo)


@dataclass
class MenuSetup:
    """A controller with a project of two groups, made for one test."""

    controller: ProjectController
    project: Project
    photos: list[Photo]
    launcher: StandInLauncher
    renderer: StandInRenderer

    def developed_photos(self) -> list[str]:
        """The names of the photos darktable was asked to develop at thumbnail size, in order.

        Returns:
            The file names.
        """
        side = DevelopedThumbnails.SIDE
        return [source.name for source, _edit, max_side, _quality in self.renderer.requests if max_side == side]

    def exported_names(self) -> list[str]:
        """The names of the files in the project's export folder.

        Returns:
            The names, sorted; empty when nothing was exported.
        """
        folder = self.controller.export_folder
        found = folder.glob("*.jpg")
        names = [path.name for path in found]
        names.sort()
        return names

    def sidecar_of(self, number: int) -> Path:
        """The sidecar file of a photo, whether or not it exists.

        Args:
            number: Index of the photo in :attr:`photos`.

        Returns:
            The sidecar file.
        """
        photo = self.photos[number]
        name = f"{photo.name}.xmp"
        return photo.path.with_name(name)

    def write_edit(self, number: int) -> Path:
        """Give a photo a sidecar that holds the user's own darktable edit.

        Args:
            number: Index of the photo in :attr:`photos`.

        Returns:
            The sidecar file.
        """
        photo = self.photos[number]
        plain = blend_text(0, False)
        entries = [("exposure", plain), ("crop", plain)]
        name = f"{photo.name}.xmp"
        folder = photo.path.parent
        return write_sidecar(folder, entries, 2, name, EDITED_HASHES)


@pytest.fixture
def setup(tmp_path: Path, qt_application: QApplication) -> Iterator[MenuSetup]:
    """A controller with stand-ins for darktable, and a project with two groups.

    Group 1 holds two raw files; group 2 holds a raw file and a JPEG file. All
    four photos are selected. No photo is measured, so the first selected
    photo of a group stands for it until a photo is edited or chosen. After
    the test, the background work the test started is waited for.

    Args:
        tmp_path: pytest's temporary folder for the test.
        qt_application: The Qt application the controller runs in.

    Yields:
        The setup.
    """
    app_folder = tmp_path / "app"
    folders = AppFolders(app_folder)
    settings = AppSettings()
    settings.ai_enabled = False
    store = SettingsStore(folders.config)
    services = AppServices.create(settings, folders)
    renderer = StandInRenderer()
    launcher = StandInLauncher()
    services.darktable = renderer
    services.developer = PhotoDeveloper(services.reader, renderer)
    services.exporter = Exporter(services.reader, services.developer, services.refiner)
    services.darktable_launcher = launcher
    developed_folder = folders.cache / "developed"
    services.thumbnails = DevelopedThumbnails(renderer, developed_folder)
    controller = ProjectController(services, settings, store)
    project_folder = tmp_path / "project"
    controller.create_project("Menus", project_folder)
    wait_until(lambda: not controller.tasks.is_busy)
    project = controller.project
    photos_folder = tmp_path / "photos"
    photos_folder.mkdir()
    photos: list[Photo] = []
    for name in ["P1000001.RW2", "P1000002.RW2", "P1000003.RW2", "P1000004.jpg"]:
        path = photos_folder / name
        path.write_bytes(b"photo")
        kind = FileKind.of(path)
        photo = Photo(path, kind)
        photos.append(photo)
    project.set_photos(photos)
    for photo in photos:
        project.decide(photo.id, Decision.KEEP)
    first = PhotoGroup("group-1", "Group 1", [photos[0].id, photos[1].id], photos[0].id)
    second = PhotoGroup("group-2", "Group 2", [photos[2].id, photos[3].id], photos[2].id)
    project.set_groups([first, second])
    yield MenuSetup(controller, project, photos, launcher, renderer)
    wait_until(lambda: not controller.tasks.is_busy)
    controller.tasks.wait(5000)


def find_item(menu: QMenu, *texts: str) -> QAction:
    """Find a menu item by its text, inside submenus too.

    Args:
        menu: The menu.
        texts: The item's whole text, after the titles of the submenus it is in.

    Returns:
        The item.
    """
    current = menu
    found: QAction | None = None
    for text in texts:
        actions = current.actions()
        matches = [action for action in actions if action.text() == text]
        names = [action.text() for action in actions]
        assert matches, f"no item {text!r} in {names}"
        found = matches[0]
        submenu = found.menu()
        if submenu is not None:
            current = submenu
    return found


def history_of(sidecar: Path) -> list[str]:
    """The modules of a sidecar's history, in order.

    Args:
        sidecar: The sidecar file.

    Returns:
        darktable's names of the modules.
    """
    tree = ElementTree.parse(sidecar)
    root = tree.getroot()
    items = root.findall(".//darktable:history/rdf:Seq/rdf:li", DarktableEdit.NAMESPACES)
    operation_name = DarktableEdit.qualified("operation")
    return [item.get(operation_name) for item in items]


def test_photo_menu_offers_what_fits_the_photo(setup: MenuSetup) -> None:
    """A raw file the user edited can give its sidecar; any photo can take one; the other items are always there."""
    controller = setup.controller
    photos = setup.photos
    setup.write_edit(0)
    edited_menu = PhotoMenu(controller, photos[0].id, [photos[0].id], GROUP_WORDS, "group-1")
    plain_menu = PhotoMenu(controller, photos[1].id, [photos[1].id], GROUP_WORDS, "group-1")
    picture_menu = PhotoMenu(controller, photos[3].id, [photos[3].id], None, None)
    edited_texts = edited_menu.item_texts()
    plain_texts = plain_menu.item_texts()
    picture_texts = picture_menu.item_texts()
    preview_item = find_item(edited_menu, "Use as the group's preview")
    to_targets = find_item(edited_menu, "Apply sidecar to")
    to_menu = to_targets.menu()
    to_texts = [action.text() for action in to_menu.actions() if action.text()]
    assert edited_texts == [
        "Open in darktable",
        "Refresh preview",
        "Open the file",
        "Show in folder",
        "Copy path",
        "Export",
        "Select\tK",
        "Unselect\tX",
        "Use as the group's preview",
        "Apply sidecar to",
        "Apply sidecar from",
    ]
    assert to_texts == ["The edit of P1000001.RW2", "Its group (Group 1)", "Another group", "All groups"]
    assert preview_item.isChecked()
    assert not preview_item.isEnabled()
    assert "Apply sidecar to  (no darktable edit yet)" in plain_texts
    assert "Apply sidecar from" in plain_texts
    assert picture_texts == [
        "Open in darktable",
        "Refresh preview  (not a raw file)",
        "Open the file",
        "Show in folder",
        "Copy path",
        "Export",
    ]


def test_photo_menu_items_do_their_work(setup: MenuSetup) -> None:
    """The items open the photo in darktable, copy paths, unselect photos, and make a photo the preview."""
    controller = setup.controller
    project = setup.project
    photos = setup.photos
    chosen = [photos[0].id, photos[1].id]
    menu = PhotoMenu(controller, photos[1].id, chosen, GROUP_WORDS, "group-1")
    open_item = find_item(menu, "Open in darktable")
    copy_item = find_item(menu, "Copy 2 paths")
    unselect_item = find_item(menu, "Unselect 2 photos\tX")
    open_item.trigger()
    copy_item.trigger()
    clipboard = QGuiApplication.clipboard()
    copied = clipboard.text()
    unselect_item.trigger()
    assert setup.launcher.opened == [photos[1].path]
    assert copied == f"{photos[0].id}\n{photos[1].id}"
    assert project.decision_of(photos[0].id) is Decision.SET_ASIDE
    assert project.decision_of(photos[1].id) is Decision.SET_ASIDE
    project.decide(photos[0].id, Decision.KEEP)
    project.decide(photos[1].id, Decision.KEEP)
    preview_menu = PhotoMenu(controller, photos[1].id, [photos[1].id], GROUP_WORDS, "group-1")
    preview_item = find_item(preview_menu, "Use as the group's preview")
    preview_item.trigger()
    sample = controller.sample_photo("group-1")
    assert sample.id == photos[1].id


def test_image_to_group_writes_the_edit_into_the_other_photos(setup: MenuSetup) -> None:
    """The edit goes into the sidecars of the group's other raw photos, without the crop; the group exports them."""
    controller = setup.controller
    project = setup.project
    photos = setup.photos
    source = setup.write_edit(0)
    project.set_edited_at(photos[0].id, 100.0)
    menu = PhotoMenu(controller, photos[0].id, [photos[0].id], GROUP_WORDS, "group-1")
    item = find_item(menu, "Apply sidecar to", "Its group (Group 1)")
    item.trigger()
    target = setup.sidecar_of(1)
    choice = project.choice_of("group-1")
    preview = controller.sample_photo("group-1")
    sources = controller.photo_edit_sources()
    source_labels = [photo_source.label for photo_source in sources]
    assert history_of(target) == ["exposure"]
    assert history_of(source) == ["exposure", "crop"]
    assert choice.pipeline_id == RefinementPipeline.CAMERA_ID
    assert project.photo_edit_of(photos[1].id) is None
    assert project.edited_at(photos[1].id) is not None
    assert not project.edited_by_user(photos[1].id)
    assert preview.id == photos[0].id
    assert source_labels == ["P1000001.RW2  (Group 1)"]


def test_group_to_group_skips_files_that_are_not_raw(setup: MenuSetup) -> None:
    """A group's preview edit goes into another group's raw photos; its JPEG file is left alone."""
    controller = setup.controller
    project = setup.project
    setup.write_edit(0)
    menu = GroupMenu(controller, "group-1", ["group-1"])
    item = find_item(menu, "Apply sidecar to", "Another group", "Group 2")
    item.trigger()
    jpeg_sidecar = setup.sidecar_of(3)
    raw_sidecar = setup.sidecar_of(2)
    assert history_of(raw_sidecar) == ["exposure"]
    assert not jpeg_sidecar.exists()
    assert project.choice_of("group-2").pipeline_id == RefinementPipeline.CAMERA_ID


def test_image_to_image_keeps_the_photo_on_its_own_sidecar(setup: MenuSetup) -> None:
    """A sidecar applied to a single photo is written into it, and the photo keeps it even when its group picks another edit."""
    controller = setup.controller
    project = setup.project
    photos = setup.photos
    setup.write_edit(0)
    chosen = [photos[0].id, photos[1].id]
    menu = PhotoMenu(controller, photos[0].id, chosen, GROUP_WORDS, "group-1")
    item = find_item(menu, "Apply sidecar to", "The other selected photo")
    item.trigger()
    target = setup.sidecar_of(1)
    other_edit = setup.write_edit(2)
    group_option = RefinementPipeline("darktable-9", "darktable edit", PipelineSource.DARKTABLE, [], "", other_edit)
    project.add_pipeline(group_option)
    controller.choose("group-1", group_option.id)
    plan = controller.export_plan()
    developed_with = {photo.id: option.darktable_edit for photo, option in plan.items}
    assert history_of(target) == ["exposure"]
    assert project.photo_edit_of(photos[1].id) == target
    assert developed_with[photos[1].id] == target
    assert developed_with[photos[0].id] == other_edit
    follow_menu = PhotoMenu(controller, photos[1].id, [photos[1].id], GROUP_WORDS, "group-1")
    follow_item = find_item(follow_menu, "Follow the group's pick again")
    follow_item.trigger()
    assert project.photo_edit_of(photos[1].id) is None


def test_group_to_image_and_image_to_group_from_the_other_side(setup: MenuSetup) -> None:
    """"Apply sidecar from" takes a group's preview for a photo, and an edited photo for a group."""
    controller = setup.controller
    project = setup.project
    photos = setup.photos
    setup.write_edit(0)
    project.set_edited_at(photos[0].id, 100.0)
    photo_menu = PhotoMenu(controller, photos[2].id, [photos[2].id], GROUP_WORDS, "group-2")
    group_item = find_item(photo_menu, "Apply sidecar from", "A group", "Group 1  (P1000001.RW2)")
    group_item.trigger()
    group_menu = GroupMenu(controller, "group-2", ["group-2"])
    photo_item = find_item(group_menu, "Apply sidecar from", "A photo", "P1000001.RW2  (Group 1)")
    target = setup.sidecar_of(2)
    assert history_of(target) == ["exposure"]
    assert project.photo_edit_of(photos[2].id) == target
    assert photo_item.isEnabled()


def test_replacing_an_edit_of_your_own_asks_first_and_keeps_a_backup(setup: MenuSetup, monkeypatch: pytest.MonkeyPatch) -> None:
    """A photo's own edit is replaced only after a yes, and its old sidecar is kept in the project folder.

    Args:
        setup: The controller and its project.
        monkeypatch: Answers the question in place of the user.
    """
    controller = setup.controller
    project = setup.project
    photos = setup.photos
    setup.write_edit(0)
    plain = blend_text(0, False)
    own_entries = [("colorbalancergb", plain)]
    folder = photos[1].path.parent
    own = write_sidecar(folder, own_entries, 1, "P1000002.RW2.xmp", EDITED_HASHES)
    project.set_edited_at(photos[1].id, 50.0)
    answers = [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]
    monkeypatch.setattr(QMessageBox, "question", lambda *arguments: answers.pop(0))
    menu = PhotoMenu(controller, photos[0].id, [photos[0].id], GROUP_WORDS, "group-1")
    item = find_item(menu, "Apply sidecar to", "Its group (Group 1)")
    item.trigger()
    kept = history_of(own)
    item.trigger()
    replaced = history_of(own)
    found = project.folder.glob("sidecar backups/*/P1000002.RW2.xmp")
    backups = [backup for backup in found]
    assert kept == ["colorbalancergb"]
    assert replaced == ["exposure"]
    assert len(backups) == 1
    assert history_of(backups[0]) == ["colorbalancergb"]


def test_a_photo_without_an_edit_cannot_give_its_sidecar(setup: MenuSetup) -> None:
    """A raw file the user did not edit, and a JPEG file, say why, and nothing is picked."""
    controller = setup.controller
    project = setup.project
    photos = setup.photos
    problems: list[str] = []
    controller.problem.connect(problems.append)
    controller.apply_edit_to_groups(photos[1].path, ["group-1"])
    assert controller.edit_problem(photos[1].id) == "no darktable edit yet"
    assert controller.edit_problem(photos[3].id) == "not a raw file"
    assert problems == ["P1000002.RW2 holds no darktable edit of your own yet. Edit it in darktable first."]
    assert project.choice_of("group-1") is None


def test_group_menu_works_on_the_preview_and_the_chosen_groups(setup: MenuSetup) -> None:
    """The group menu names the preview, opens it, and renames, removes and unselects the chosen groups."""
    controller = setup.controller
    project = setup.project
    photos = setup.photos
    menu = GroupMenu(controller, "group-1", ["group-1"])
    both_menu = GroupMenu(controller, "group-1", ["group-1", "group-2"])
    texts = menu.item_texts()
    both_texts = both_menu.item_texts()
    renamed: list[str] = []
    removed: list[list[str]] = []
    menu.rename_requested.connect(renamed.append)
    both_menu.remove_requested.connect(removed.append)
    open_item = find_item(menu, "Open in darktable")
    rename_item = find_item(menu, "Rename group…")
    remove_item = find_item(both_menu, "Remove 2 groups…")
    unselect_item = find_item(both_menu, "Unselect all photos of 2 groups")
    open_item.trigger()
    rename_item.trigger()
    remove_item.trigger()
    unselect_item.trigger()
    decisions = [project.decision_of(photo.id) for photo in photos]
    assert texts[0] == "Preview: P1000001.RW2"
    assert "Apply sidecar to  (no darktable edit yet)" in texts
    assert "Apply sidecar from" in texts
    assert "Select all photos of 2 groups" in both_texts
    assert setup.launcher.opened == [photos[0].path]
    assert renamed == ["group-1"]
    assert removed == [["group-1", "group-2"]]
    assert decisions == [Decision.SET_ASIDE] * 4


def test_a_new_darktable_edit_makes_its_photo_the_preview(setup: MenuSetup) -> None:
    """After an edit in darktable, the edited photo stands for its group, until the user chooses another."""
    controller = setup.controller
    photos = setup.photos
    changes: list[bool] = []
    controller.edits_changed.connect(lambda: changes.append(True))
    before = controller.sample_photo("group-1")
    setup.write_edit(1)
    controller.check_edits()
    noticed = wait_until(lambda: bool(changes))
    refreshed = wait_until(lambda: "P1000002.RW2" in setup.developed_photos())
    after = controller.sample_photo("group-1")
    controller.choose_sample("group-1", photos[0].id)
    chosen = controller.sample_photo("group-1")
    menu = GroupMenu(controller, "group-1", ["group-1"])
    automatic_item = find_item(menu, "Choose the preview automatically")
    automatic_item.trigger()
    automatic = controller.sample_photo("group-1")
    assert noticed
    assert refreshed
    assert before.id == photos[0].id
    assert after.id == photos[1].id
    assert chosen.id == photos[0].id
    assert automatic.id == photos[1].id


def test_opening_in_darktable_without_darktable_says_so(setup: MenuSetup) -> None:
    """Without darktable the menu item is greyed out, and asking anyway shows a clear problem."""
    controller = setup.controller
    photos = setup.photos
    controller.services.darktable_launcher = DarktableLauncher(None)
    problems: list[str] = []
    controller.problem.connect(problems.append)
    menu = PhotoMenu(controller, photos[0].id, [photos[0].id], None, None)
    texts = menu.item_texts()
    controller.open_in_darktable(photos[0].id)
    assert texts[0] == "Open in darktable  (darktable not found)"
    assert problems == ["darktable was not found. Install darktable to open photos in it."]


def grey_level(image: QImage) -> int:
    """The red level of the pixel in the middle of a picture.

    Args:
        image: The picture.

    Returns:
        A level from 0 to 255.
    """
    middle_x = image.width() // 2
    middle_y = image.height() // 2
    color = image.pixelColor(middle_x, middle_y)
    return color.red()


def test_refreshing_a_group_develops_its_photos_with_their_sidecars(setup: MenuSetup) -> None:
    """"Refresh previews" develops each raw photo of the group, its preview first, and finds the pictures again later."""
    controller = setup.controller
    photos = setup.photos
    changed: list[str] = []
    controller.thumbnail_changed.connect(changed.append)
    controller.choose_sample("group-1", photos[1].id)
    menu = GroupMenu(controller, "group-1", ["group-1"])
    item = find_item(menu, "Refresh previews")
    item.trigger()
    refreshed = wait_until(lambda: len(changed) == 2 and not controller.tasks.is_busy)
    first_order = setup.developed_photos()
    thumbnail = controller.thumbnail(photos[0].id)
    level = grey_level(thumbnail)
    item.trigger()
    again = wait_until(lambda: len(changed) == 4 and not controller.tasks.is_busy)
    second_order = setup.developed_photos()
    other_menu = GroupMenu(controller, "group-2", ["group-2"])
    other_item = find_item(other_menu, "Refresh previews")
    other_item.trigger()
    other_done = wait_until(lambda: len(changed) == 5 and not controller.tasks.is_busy)
    third_order = setup.developed_photos()
    assert refreshed
    assert again
    assert other_done
    assert first_order == ["P1000002.RW2", "P1000001.RW2"]
    assert changed[:2] == [photos[1].id, photos[0].id]
    assert abs(level - 128) <= 2
    assert second_order == first_order
    assert third_order == ["P1000002.RW2", "P1000001.RW2", "P1000003.RW2"]
    assert controller.thumbnail(photos[3].id) is None


def test_refresh_items_count_raw_photos_and_groups(setup: MenuSetup) -> None:
    """The photo menu counts the chosen raw files, and the group menu the chosen groups."""
    controller = setup.controller
    photos = setup.photos
    chosen = [photos[0].id, photos[1].id, photos[3].id]
    photo_menu = PhotoMenu(controller, photos[3].id, chosen, None, None)
    group_menu = GroupMenu(controller, "group-1", ["group-1", "group-2"])
    photo_texts = photo_menu.item_texts()
    group_texts = group_menu.item_texts()
    assert "Refresh 2 previews" in photo_texts
    assert "Refresh previews of 2 groups" in group_texts


def test_applying_a_sidecar_refreshes_the_previews_it_changed(setup: MenuSetup) -> None:
    """After "Apply sidecar" the group's preview is developed by itself, and so is a photo that got the edit alone."""
    controller = setup.controller
    project = setup.project
    photos = setup.photos
    notices: list[str] = []
    controller.notice.connect(notices.append)
    setup.write_edit(0)
    project.set_edited_at(photos[0].id, 100.0)
    group_menu = PhotoMenu(controller, photos[0].id, [photos[0].id], GROUP_WORDS, "group-1")
    group_item = find_item(group_menu, "Apply sidecar to", "Its group (Group 1)")
    group_item.trigger()
    group_done = wait_until(lambda: not controller.tasks.is_busy)
    after_group = setup.developed_photos()
    photo_menu = PhotoMenu(controller, photos[2].id, [photos[2].id], GROUP_WORDS, "group-2")
    photo_item = find_item(photo_menu, "Apply sidecar from", "A photo", "P1000001.RW2  (Group 1)")
    photo_item.trigger()
    photo_done = wait_until(lambda: not controller.tasks.is_busy)
    after_photo = setup.developed_photos()
    refresh_notices = [text for text in notices if text.startswith("Refreshed")]
    assert group_done
    assert photo_done
    assert after_group == ["P1000001.RW2"]
    assert after_photo == ["P1000001.RW2", "P1000003.RW2"]
    assert refresh_notices == []
    assert notices[-1].startswith("Wrote the edit of P1000001.RW2.xmp into P1000003.RW2.")


def test_refreshing_without_darktable_cli_says_so(setup: MenuSetup) -> None:
    """Without darktable-cli the refresh items are greyed out, and asking anyway shows a clear problem."""
    controller = setup.controller
    photos = setup.photos
    missing = DarktableRenderer(None)
    unused_folder = setup.project.folder / "unused"
    controller.services.thumbnails = DevelopedThumbnails(missing, unused_folder)
    problems: list[str] = []
    controller.problem.connect(problems.append)
    photo_menu = PhotoMenu(controller, photos[0].id, [photos[0].id], None, None)
    group_menu = GroupMenu(controller, "group-1", ["group-1"])
    photo_texts = photo_menu.item_texts()
    group_texts = group_menu.item_texts()
    controller.refresh_previews([photos[0].id])
    assert photo_texts[1] == "Refresh preview  (darktable-cli not found)"
    assert "Refresh previews  (darktable-cli not found)" in group_texts
    assert problems == [
        "darktable-cli was not found, so the previews cannot show darktable edits. Install darktable to refresh them."
    ]


def submenu_texts(menu: QMenu, title: str) -> list[str]:
    """The texts of a submenu's items, greyed-out lines included.

    Args:
        menu: The menu that holds the submenu.
        title: The submenu's title.

    Returns:
        The texts, in order.
    """
    item = find_item(menu, title)
    submenu = item.menu()
    actions = submenu.actions()
    return [action.text() for action in actions if action.text()]


def statuses_of(results: list[ExportResult]) -> dict[str, ExportStatus]:
    """What happened to each exported file.

    Args:
        results: The results of one export.

    Returns:
        The status by file name.
    """
    return {result.target.name: result.status for result in results}


def test_exporting_groups_writes_their_selected_photos(setup: MenuSetup) -> None:
    """"Export" writes the selected photos of the group, leaves skipped groups out, and keeps existing files."""
    controller = setup.controller
    project = setup.project
    photos = setup.photos
    results: list[list[ExportResult]] = []
    notices: list[str] = []
    controller.export_finished.connect(results.append)
    controller.notice.connect(notices.append)
    project.decide(photos[1].id, Decision.SET_ASIDE)
    menu = GroupMenu(controller, "group-1", ["group-1", "group-2"])
    texts = submenu_texts(menu, "Export")
    item = find_item(menu, "Export", "This group (Group 1)")
    item.trigger()
    first_done = wait_until(lambda: len(results) == 1)
    first_names = setup.exported_names()
    controller.choose("group-2", None)
    skipped_menu = GroupMenu(controller, "group-2", ["group-2"])
    skipped_texts = submenu_texts(skipped_menu, "Export")
    all_item = find_item(skipped_menu, "Export", "All groups")
    all_item.trigger()
    second_done = wait_until(lambda: len(results) == 2)
    second = statuses_of(results[1])
    assert texts[0].startswith("To ")
    assert texts[1:] == ["This group (Group 1)", "The 2 selected groups", "All groups"]
    assert first_done
    assert first_names == ["P1000001.jpg"]
    assert skipped_texts[1] == "This group (Group 2)  (skipped in Refine)"
    assert second_done
    assert second == {"P1000001.jpg": ExportStatus.SKIPPED}
    assert "Left out of the export: 1 skipped group." in notices


def test_exporting_photos_writes_exactly_those_photos(setup: MenuSetup) -> None:
    """The chosen photos are written even when unselected or in a skipped group, unchanged when the group has no pick."""
    controller = setup.controller
    project = setup.project
    photos = setup.photos
    results: list[list[ExportResult]] = []
    controller.export_finished.connect(results.append)
    project.decide(photos[1].id, Decision.SET_ASIDE)
    controller.choose("group-2", None)
    chosen = [photos[1].id, photos[2].id]
    menu = PhotoMenu(controller, photos[1].id, chosen, GROUP_WORDS, "group-1")
    texts = submenu_texts(menu, "Export")
    item = find_item(menu, "Export", "The 2 selected photos")
    item.trigger()
    done = wait_until(lambda: len(results) == 1)
    statuses = statuses_of(results[0])
    export_requests = [request for request in setup.renderer.requests if request[2] == project.export.long_side]
    assert texts[1:] == ["This photo (P1000002.RW2)", "The 2 selected photos", "Its group (Group 1)", "All groups"]
    assert done
    assert statuses == {"P1000002.jpg": ExportStatus.WRITTEN, "P1000003.jpg": ExportStatus.WRITTEN}
    assert setup.exported_names() == ["P1000002.jpg", "P1000003.jpg"]
    assert [request[1] for request in export_requests] == [None, None]


def test_merging_groups_keeps_the_first_and_takes_what_the_others_had(setup: MenuSetup) -> None:
    """The merged group keeps the first group's id and name, holds every photo, and takes the other group's pick, preview and options."""
    controller = setup.controller
    project = setup.project
    photos = setup.photos
    notices: list[str] = []
    controller.notice.connect(notices.append)
    used_by_one = RefinementPipeline("examples-1", "Example A", PipelineSource.EXAMPLES)
    used_by_none = RefinementPipeline("examples-2", "Example B", PipelineSource.EXAMPLES)
    typed = RefinementPipeline("words-1", "brighter", PipelineSource.WORDS)
    project.add_pipeline(used_by_one)
    project.add_pipeline(used_by_none)
    project.set_option_used("group-2", used_by_one.id, False)
    project.set_option_used("group-1", used_by_none.id, False)
    project.set_option_used("group-2", used_by_none.id, False)
    project.add_group_pipeline("group-2", typed)
    controller.choose("group-2", RefinementPipeline.CAMERA_ID)
    controller.choose_sample("group-2", photos[2].id)
    single_menu = GroupMenu(controller, "group-1", ["group-1"])
    single_texts = single_menu.item_texts()
    menu = GroupMenu(controller, "group-2", ["group-2", "group-1"])
    menu.merge_requested.connect(controller.merge_groups)
    item = find_item(menu, "Merge 2 groups…")
    item.trigger()
    merged = project.group("group-1")
    group_ids = [group.id for group in project.groups]
    typed_ids = [option.id for option in project.group_pipelines("group-1")]
    expected_ids = tuple(photo.id for photo in photos)
    controller.save_now()
    reloaded = controller.services.manifest.load(project.folder)
    reloaded_group = reloaded.group("group-1")
    assert "Merge groups…  (select two or more)" in single_texts
    assert group_ids == ["group-1"]
    assert merged.title == "Group 1"
    assert merged.photo_ids == expected_ids
    assert project.choice_of("group-1").pipeline_id == RefinementPipeline.CAMERA_ID
    assert project.chosen_sample_of("group-1") == photos[2].id
    assert typed_ids == ["words-1"]
    assert project.option_used_in("group-1", used_by_one.id)
    assert not project.option_used_in("group-1", used_by_none.id)
    assert reloaded_group.photo_ids == expected_ids
    assert notices[-1] == "Merged 2 groups into Group 1, which now holds 4 photos."


def test_merging_asks_first(setup: MenuSetup, monkeypatch: pytest.MonkeyPatch) -> None:
    """The page asks before merging, and a no leaves the groups as they were.

    Args:
        setup: The controller and its project.
        monkeypatch: Answers the question in place of the user.
    """
    controller = setup.controller
    project = setup.project
    questions: list[str] = []
    answers = [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]

    def answer(*arguments: object) -> QMessageBox.StandardButton:
        """Note the question and give the next answer.

        Args:
            arguments: The question's parent, title, text, buttons and default button.

        Returns:
            The answer.
        """
        question = str(arguments[2])
        questions.append(question)
        return answers.pop(0)

    monkeypatch.setattr(QMessageBox, "question", answer)
    style = AppStyle()
    page = WorkflowPage(controller, style, "Group", "Groups")
    page.ask_to_merge_groups(["group-1", "group-2"])
    after_no = [group.id for group in project.groups]
    page.ask_to_merge_groups(["group-1", "group-2"])
    after_yes = [group.id for group in project.groups]
    page.deleteLater()
    assert after_no == ["group-1", "group-2"]
    assert after_yes == ["group-1"]
    assert questions[0].startswith('Merge these 2 groups into "Group 1"?')
    assert "holds all 4 photos" in questions[0]
