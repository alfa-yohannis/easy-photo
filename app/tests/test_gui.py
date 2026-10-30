"""An end-to-end test of the window, run without a screen.

It makes a project, adds photos, filters, groups, adds an option from typed
words, picks options, exports, and opens the project again from its manifest.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from easy_photo.gui.application import EasyPhotoApp
from easy_photo.gui.controller import ProjectController
from easy_photo.model.quality import Decision
from easy_photo.services.ai_words import AiWordsReader
from easy_photo.services.manifest import ProjectManifest
from easy_photo.settings import AppFolders, ExportSettings, GroupSettings
from tests.conftest import PhotoMaker

START = datetime(2024, 12, 14, 10, 0, 0)


def wait_until(condition: Callable[[], bool], seconds: float = 60.0) -> bool:
    """Let Qt run until a condition holds or the time is up.

    Args:
        condition: Checked again and again.
        seconds: Longest time to wait.

    Returns:
        True when the condition held in time.
    """
    application = QApplication.instance()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        application.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return False


def write_test_photos(maker: PhotoMaker) -> None:
    """Write two scenes of three photos each, half an hour apart, the last one badly blurred.

    Args:
        maker: Writes the photos.
    """
    tints = [(1.0, 0.6, 0.3), (0.3, 0.5, 1.0)]
    for scene, tint in enumerate(tints):
        for shot in range(3):
            number = scene * 3 + shot
            pixels = maker.scene(tint, number)
            if number == 5:
                pixels = maker.blurred(pixels)
            offset = timedelta(minutes=30 * scene, seconds=10 * shot)
            taken_at = START + offset
            maker.write(f"P{number:07d}", pixels, taken_at)


@pytest.fixture(scope="module")
def app(tmp_path_factory: pytest.TempPathFactory) -> EasyPhotoApp:
    """The app with its own settings folder, so the user's real settings are never touched.

    Args:
        tmp_path_factory: Makes a temporary folder for the module.

    Returns:
        The app.
    """
    root = tmp_path_factory.mktemp("app")
    folders = AppFolders(root)
    return EasyPhotoApp(["easy-photo"], folders)


def test_whole_workflow(app: EasyPhotoApp, tmp_path: Path, photo_maker: PhotoMaker) -> None:
    """Go through every step, then open the project again and find the work still there."""
    controller = app.controller
    window = app.window
    window.show()
    # Claude stays out of this test, so it never starts Claude Code or uses the network.
    controller.update_ai_settings(False, AiWordsReader.DEFAULT_MODEL)
    write_test_photos(photo_maker)
    folder = tmp_path / "projects" / "Test"
    controller.create_project("Test", folder)
    project = controller.project
    assert project is not None

    photos_folder = tmp_path / "photos"
    controller.add_sources([photos_folder])
    finished = wait_until(lambda: project.analyzed_count == 6 and not controller.tasks.is_busy)
    assert finished
    counts = project.count_by_decision()
    assert counts[Decision.SET_ASIDE] == 1

    for index in range(6):
        window.go_to(index)
    grouping = GroupSettings(False, 10.0, 0.55)
    controller.make_groups(grouping)
    sizes = [group.size for group in project.groups]
    assert sizes == [3, 2]

    answers: list[tuple[str, bool, str]] = []

    def record_answer(target: str, worked: bool, message: str) -> None:
        """Keep each answer about typed words.

        Args:
            target: Where the words were typed.
            worked: Whether an option was made.
            message: Claude's explanation, or why it did not work.
        """
        answers.append((target, worked, message))

    controller.words_answered.connect(record_answer)
    controller.add_words("brighter, more contrast")
    controller.add_words("make it pop")
    assert answers[0] == (ProjectController.REFERENCES_TARGET, True, "")
    assert answers[1][1] is False
    assert "Not understood" in answers[1][2]
    first_group, second_group = project.groups
    controller.add_words("warmer", second_group.id)
    group_option = project.pipelines[-1]
    assert project.option_used_in(second_group.id, group_option.id)
    assert not project.option_used_in(first_group.id, group_option.id)
    controller.render_versions(first_group.id)
    options = controller.options_for(first_group.id)
    wanted = len(options)

    def versions_made() -> bool:
        """Tell whether every option's version of the first group is made.

        Returns:
            True when all versions are there.
        """
        versions = controller.versions(first_group.id)
        return len(versions) == wanted

    ready = wait_until(versions_made)
    assert ready
    words_option = options[1]
    controller.choose(first_group.id, words_option.id)
    controller.try_words(second_group.id, None, "slightly darker")
    assert answers[3] == (second_group.id, True, "")
    assert project.choice_of(second_group.id).pipeline_id.startswith("typed-")

    export_folder = tmp_path / "export"
    export_text = str(export_folder)
    results: list = []
    controller.export_finished.connect(results.extend)
    settings = ExportSettings(export_text, 320, 90, True)
    controller.export(settings)
    exported = wait_until(lambda: len(results) == 5)
    assert exported
    found = export_folder.glob("*.jpg")
    files = sorted(path.name for path in found)
    assert files == ["P0000000.jpg", "P0000001.jpg", "P0000002.jpg", "P0000003.jpg", "P0000004.jpg"]

    first_photo = first_group.photo_ids[0]
    controller.select_photos([first_photo], False)
    plan = controller.export_plan()
    assert project.decision_of(first_photo) is Decision.SET_ASIDE
    assert len(plan.items) == 4
    controller.select_photos([first_photo], True)
    controller.set_option_used(first_group.id, words_option.id, False)
    first_options = controller.options_for(first_group.id)
    first_option_ids = [option.id for option in first_options]
    assert words_option.id not in first_option_ids
    assert project.choice_of(first_group.id) is None

    controller.close_project()
    manifest = folder / ProjectManifest.FILE_NAME
    controller.open_project(manifest)
    reopened = controller.project
    group_ids = [group.id for group in reopened.groups]
    assert reopened.sources == (photos_folder,)
    assert group_ids == [first_group.id, second_group.id]
    assert reopened.choice_of(second_group.id).pipeline_id.startswith("typed-")
    assert not reopened.option_used_in(first_group.id, words_option.id)
    wait_until(lambda: not controller.tasks.is_busy)
    controller.close_project()
