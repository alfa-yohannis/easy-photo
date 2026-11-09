"""The link between the window and the open project.

The controller runs the services, keeps the project up to date, and tells
the pages through Qt signals when something changed.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage

from easy_photo.gui.background import BackgroundTask, TaskContext, TaskRunner
from easy_photo.gui.images import ImageConverter
from easy_photo.model.face import Face
from easy_photo.model.group import PhotoGroup
from easy_photo.model.photo import Photo, PhotoInfo
from easy_photo.model.project import Project
from easy_photo.model.quality import Decision
from easy_photo.refinement.pipeline import PipelineSource, RefinementPipeline
from easy_photo.refinement.steps import ExposureStep, RefinementStep, StepCatalog
from easy_photo.services.ai_words import AiLoginNeeded, AiReading, AiWordsError, AiWordsReader, LoginStatus
from easy_photo.services.app_services import AppServices
from easy_photo.services.darktable import DarktableError
from easy_photo.services.darktable_edit import DarktableEdit, DarktableEditError
from easy_photo.services.exporter import ExportResult, ExportStatus
from easy_photo.services.faces import FaceFinder, FaceModels
from easy_photo.services.grouping import FaceGrouper, Grouper, SimilarityGrouper
from easy_photo.services.manifest import ManifestError
from easy_photo.services.photo_analyzer import PhotoAnalysis, PhotoAnalyzer
from easy_photo.services.photo_reader import PhotoReadError
from easy_photo.services.quality_checks import QualityChecker
from easy_photo.services.references import (
    DarktableEditPipelineBuilder,
    ExamplePipelineBuilder,
    HistoryPipelineBuilder,
    InternetPipelineBuilder,
    PipelineBuilder,
)
from easy_photo.services.sharpener import Sharpener
from easy_photo.settings import AppSettings, CheckSettings, ExportSettings, GroupSettings, SettingsStore
from easy_photo.wording import count_text


@dataclass(frozen=True)
class FoundPhotos:
    """Sent by the scan task once it has listed the photos of the sources."""

    scan_number: int
    photos: list[Photo]


@dataclass(frozen=True)
class ScannedPhoto:
    """Sent by the scan task for every photo it has read and measured."""

    scan_number: int
    photo_id: str
    info: PhotoInfo
    analysis: PhotoAnalysis

    thumbnail: QImage
    """Made from the camera's preview, or the picture darktable developed, when one is kept for the photo's sidecar."""

    edited_at: float | None
    """When the user last edited the photo in darktable, or None when they have not."""


@dataclass(frozen=True)
class UnreadablePhoto:
    """Sent by the scan task for a photo it could not read."""

    scan_number: int
    photo_id: str
    message: str


@dataclass(frozen=True)
class DevelopedPicture:
    """Sent by the refresh task for every photo darktable developed: the photo's new thumbnail."""

    photo_id: str
    thumbnail: QImage


@dataclass(frozen=True)
class RefreshResult:
    """What one refresh of previews did."""

    developed: int
    """Photos that got their picture."""

    total: int
    """Photos the refresh was for."""

    problems: list[str]
    """Why photos could not be developed, one message per photo."""

    stopped: bool
    """True when the user stopped the refresh before the end."""


@dataclass(frozen=True)
class VersionPreview:
    """One refinement option applied to a group's sample photo, ready to show."""

    pipeline_id: str
    name: str
    description: str
    image: QImage

    sample_id: str
    """Id of the photo the version was made on."""


@dataclass(frozen=True)
class EditSource:
    """A darktable edit the user can apply: a group's preview, or a photo they edited in darktable."""

    label: str
    """Text for the menu, such as "Group 2  (P1209499.RW2)"."""

    path: Path
    """The raw file whose sidecar holds the edit."""


@dataclass(frozen=True)
class ExportPlan:
    """What an export would write: each photo with its refinement, and the groups left out."""

    items: list[tuple[Photo, RefinementPipeline]]
    skipped_groups: int
    unpicked_groups: int


class ProjectController(QObject):
    """Connects the window with the open project and the services.

    Pages call the controller's methods. Slow work runs in the background; its
    results are stored in the project on the window thread, and a signal
    tells the pages to update. Every change is saved to the project's manifest
    a moment later, so the user never has to remember to save.
    """

    FACE_SIDE = 1600
    PREVIEW_SIDE = 1600
    VERSION_SIDE = 1280
    SAVE_DELAY_MS = 1500
    VARIANT_STOPS = 0.3
    """How much brighter or darker the extra options of the Refine step are, in stops."""

    BACKUP_FOLDER_NAME = "sidecar backups"
    """Folder in the project folder where "Apply sidecar" keeps the old sidecars it replaced."""

    REFERENCES_TARGET = "references"
    """Where typed words came from when they were typed in the References step (otherwise a group id)."""

    LOGIN_CHECK_MS = 3000
    LOGIN_CHECKS = 200
    """After the login window opens, the login is checked every 3 seconds, for at most 10 minutes."""

    words_answered = Signal(str, bool, str)
    """Typed words were read: (where they were typed, whether it worked, a message or Claude's explanation)."""

    claude_login_needed = Signal()
    """Claude Code is installed but not logged in; the window offers to open the login."""

    ai_changed = Signal()
    option_groups_changed = Signal(str)
    """An option was turned on or off for the group with this id."""

    sample_changed = Signal(str)
    """The user chose another photo to stand for the group with this id (its preview), or went back to the sharpest."""

    edits_changed = Signal()
    """Photos were edited in darktable since the last look; previews may change, and versions are made again."""

    thumbnail_changed = Signal(str)
    """The photo with this id got a new thumbnail, developed by darktable with its sidecar."""

    project_opened = Signal()
    project_closed = Signal()
    sources_changed = Signal()
    photos_changed = Signal()
    photo_updated = Signal(str)
    analysis_changed = Signal()
    faces_changed = Signal()
    groups_changed = Signal()
    pipelines_changed = Signal()
    versions_changed = Signal(str)
    choices_changed = Signal()
    export_finished = Signal(object)
    notice = Signal(str)
    problem = Signal(str)

    def __init__(
        self,
        services: AppServices,
        settings: AppSettings,
        settings_store: SettingsStore,
        parent: QObject | None = None,
    ) -> None:
        """Create the controller without an open project.

        Args:
            services: The app's services.
            settings: The app's own settings (recent projects, face models, darktable-cli).
            settings_store: Saves the app's settings.
            parent: Qt parent object.
        """
        super().__init__(parent)
        self._services = services
        self._settings = settings
        self._settings_store = settings_store
        self._project: Project | None = None
        self._tasks = TaskRunner(2, self)
        self._converter = ImageConverter()
        self._sharpener = Sharpener()
        default_checks = CheckSettings()
        self._checker = QualityChecker.from_settings(default_checks)
        self._thumbnails: dict[str, QImage] = {}
        self._face_images: dict[str, QImage] = {}
        self._versions: dict[str, list[VersionPreview]] = {}
        self._rendering: set[str] = set()
        self._outdated_renders: set[str] = set()
        """Groups whose versions are being made but were asked for again; the result is not kept."""
        self._reserved_ids: set[str] = set()
        self._scan_number = 0
        self._scan_task: BackgroundTask | None = None
        self._checking_edits = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(self.SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.save_now)
        self._login_timer = QTimer(self)
        self._login_timer.setInterval(self.LOGIN_CHECK_MS)
        self._login_timer.timeout.connect(self._check_claude_login)
        self._login_checks_left = 0
        self._checking_login = False
        self._retry_after_login: Callable[[], None] | None = None

    # ------------------------------------------------------------- properties

    @property
    def project(self) -> Project | None:
        """The open project, or None."""
        return self._project

    @property
    def tasks(self) -> TaskRunner:
        """The runner of background tasks, for the status bar."""
        return self._tasks

    @property
    def services(self) -> AppServices:
        """The app's services."""
        return self._services

    @property
    def recent_projects(self) -> list[Path]:
        """Manifest files of recently opened projects that still exist, the latest first."""
        paths = [Path(text) for text in self._settings.recent_projects]
        return [path for path in paths if path.exists()]

    @property
    def faces_available(self) -> bool:
        """True when the face model files are there."""
        return self._services.face_finder.available

    @property
    def models_folder(self) -> Path:
        """Folder where the face model files are looked for."""
        return self._services.face_models.folder

    @property
    def darktable_available(self) -> bool:
        """True when darktable-cli was found."""
        return self._services.darktable.available

    @property
    def can_open_in_darktable(self) -> bool:
        """True when darktable itself, the program with the window, was found."""
        return self._services.darktable_launcher.available

    @property
    def can_refresh_previews(self) -> bool:
        """True when darktable-cli was found, so the previews of raw photos can show their darktable edits."""
        return self._services.thumbnails.available

    @property
    def search_service_name(self) -> str:
        """Name of the internet search service."""
        return self._services.web_search.name

    @property
    def app_settings(self) -> AppSettings:
        """The app's own settings, for the settings dialogs."""
        return self._settings

    @property
    def ai_enabled(self) -> bool:
        """True when the user lets Claude read words the app's own phrases do not cover."""
        return self._settings.ai_enabled

    @property
    def ai_ready(self) -> bool:
        """True when Claude may be asked and Claude Code's claude program was found."""
        return self._settings.ai_enabled and self._services.ai_reader.available

    @property
    def claude_program(self) -> Path | None:
        """Claude Code's claude program, or None when it was not found."""
        return self._services.ai_reader.program

    def claude_login_status(self) -> LoginStatus:
        """Ask Claude Code whether it is logged in. Takes a fraction of a second.

        Returns:
            The status.
        """
        return self._services.ai_reader.login.status()

    def start_claude_login(self) -> None:
        """Open a terminal window where the user logs in to Claude Code, and watch for the login to finish.

        When it finishes, words that waited for the login are read again.
        """
        try:
            self._services.ai_reader.login.open_login_window()
        except AiWordsError as error:
            message = str(error)
            self.problem.emit(message)
            return
        self._login_checks_left = self.LOGIN_CHECKS
        self._login_timer.start()
        self.notice.emit("Log in to Claude Code in the window that opened. The app notices when you are done.")

    def update_ai_settings(self, enabled: bool, model: str) -> None:
        """Change whether and how Claude reads the user's words.

        Args:
            enabled: Let Claude read words the app's own phrases do not cover.
            model: The Claude model to ask.
        """
        self._settings.ai_enabled = enabled
        self._settings.ai_model = model
        self._save_settings()
        catalog = StepCatalog()
        self._services.ai_reader = AiWordsReader.locate(catalog, self._settings.claude_cli, model)
        self.ai_changed.emit()

    # ------------------------------------------------------ project lifecycle

    def create_project(self, name: str, folder: Path) -> None:
        """Make a new project in a folder and open it.

        Args:
            name: Name of the project.
            folder: The project folder.
        """
        try:
            project = self._services.manifest.create(name, folder)
        except (ManifestError, OSError) as error:
            message = str(error)
            self.problem.emit(message)
            return
        self._open(project)

    def open_project(self, path: Path) -> None:
        """Open a project from its manifest file or its folder.

        Args:
            path: The manifest file or the project folder.
        """
        try:
            project = self._services.manifest.load(path)
        except ManifestError as error:
            self._settings.forget_project(path)
            self._save_settings()
            message = str(error)
            self.problem.emit(message)
            return
        self._open(project)

    def close_project(self) -> None:
        """Save and close the open project."""
        if self._project is None:
            return
        self._tasks.stop_all()
        self.save_now()
        self._project = None
        self._clear_images()
        self.project_closed.emit()

    def save_now(self) -> None:
        """Write the open project's manifest now."""
        self._save_timer.stop()
        if self._project is None:
            return
        try:
            self._services.manifest.save(self._project)
        except OSError as error:
            self.problem.emit(f"The project could not be saved: {error}")

    def shutdown(self) -> None:
        """Stop the background work and save, before the app closes."""
        self._login_timer.stop()
        self._tasks.stop_all()
        self.save_now()
        self._tasks.wait(5000)

    # -------------------------------------------------------- sources, scan

    def add_sources(self, paths: Sequence[Path]) -> None:
        """Add folders or photos to the project and measure the new photos.

        Args:
            paths: The folders and files.
        """
        project = self._project
        if project is None:
            return
        added = False
        for path in paths:
            if project.add_source(path):
                added = True
        if not added:
            return
        self._sources_changed()

    def remove_source(self, path: Path) -> None:
        """Remove a folder or file from the project.

        Args:
            path: The folder or file.
        """
        project = self._project
        if project is None:
            return
        project.remove_source(path)
        self._sources_changed()

    def scan(self) -> None:
        """Find the photos of the sources, then read and measure the ones not measured yet."""
        project = self._project
        if project is None:
            return
        if self._scan_task is not None:
            self._scan_task.request_stop()
        self._scan_number += 1
        sources = project.sources
        measured = {photo.id for photo in project.photos if project.is_analyzed(photo.id)}
        job = partial(self._scan_job, self._scan_number, sources, measured)
        self._scan_task = self._tasks.start(
            "Reading and measuring photos",
            job,
            self._on_scan_finished,
            self._on_task_failed,
            self._on_scan_item,
        )

    # ------------------------------------------------------- filter decisions

    def update_checks(self, checks: CheckSettings) -> None:
        """Use new limits for the quality checks and judge every measured photo again.

        Args:
            checks: The new limits.
        """
        project = self._project
        if project is None:
            return
        project.checks = checks
        self._checker = QualityChecker.from_settings(checks)
        for photo in project.photos:
            old = project.quality_of(photo.id)
            if old is None:
                continue
            new = self._checker.evaluate(old.scores)
            project.set_quality(photo.id, new)
        self.analysis_changed.emit()
        self._changed()

    def decide(self, photo_ids: Sequence[str], decision: Decision | None) -> None:
        """Store the user's own decision for some photos.

        Args:
            photo_ids: Ids of the photos.
            decision: Keep or set aside; None goes back to the app's decision.
        """
        project = self._project
        if project is None:
            return
        for photo_id in photo_ids:
            result = project.quality_of(photo_id)
            project.decide(photo_id, decision)
            self._record_decision(photo_id, decision, result)
            self.photo_updated.emit(photo_id)
        self.analysis_changed.emit()
        self._changed()

    # ------------------------------------------------------- faces and people

    def find_faces(self, then_group: bool = False) -> None:
        """Look for faces in the kept photos that have not been searched yet.

        Args:
            then_group: Make the groups again when the faces are found.
        """
        project = self._project
        if project is None:
            return
        if not self.faces_available:
            folder = self.models_folder
            self.problem.emit(
                f"The face models are missing (looked in {folder}). Download them, or choose a folder that has them."
            )
            return
        kept = project.kept_photos()
        photos = [photo for photo in kept if not project.faces_searched(photo.id)]
        job = partial(self._faces_job, photos)
        handler = partial(self._on_faces_found, then_group)
        self._tasks.start("Finding faces", job, handler, self._on_task_failed)

    def download_face_models(self) -> None:
        """Download the two face model files (about 40 MB) in the background."""
        models = self._services.face_models
        job = partial(self._download_job, models)
        self._tasks.start("Downloading the face models", job, self._on_models_downloaded, self._on_task_failed)

    def set_models_folder(self, folder: Path) -> None:
        """Use the face model files in another folder.

        Args:
            folder: Folder that holds the two model files.
        """
        self._settings.models_folder = str(folder)
        self._save_settings()
        models = FaceModels(folder)
        finder = FaceFinder(models)
        self._services.face_models = models
        self._services.face_finder = finder
        self._services.measurer.set_face_finder(finder)
        self.faces_changed.emit()

    def rename_person(self, person_id: str, name: str) -> None:
        """Give a person a name; groups made by people get the new name too.

        Args:
            person_id: Id of the person.
            name: The new name.
        """
        project = self._project
        if project is None:
            return
        person = project.person(person_id)
        cleaned = name.strip()
        if person is None or not cleaned or cleaned == person.name:
            return
        person.name = cleaned
        self._retitle_people_groups()
        self.faces_changed.emit()
        self.groups_changed.emit()
        self._changed()

    def remove_groups(self, group_ids: Sequence[str]) -> None:
        """Remove groups. Their photos stay in the project but are not exported.

        A removed group's pick and typed options go with it, and so do the
        references made for the removed groups only. Making the groups again
        brings the photos back into groups.

        Args:
            group_ids: Ids of the groups.
        """
        project = self._project
        if project is None:
            return
        removed = [group_id for group_id in group_ids if project.group(group_id) is not None]
        if not removed:
            return
        own_options = self._options_only_for(removed)
        for group_id in removed:
            project.remove_group(group_id)
            self._versions.pop(group_id, None)
        for option_id in own_options:
            project.remove_pipeline(option_id)
        details = {"groups": removed, "options": own_options}
        self._services.history_log.record("remove groups", details)
        self.groups_changed.emit()
        self.pipelines_changed.emit()
        self.choices_changed.emit()
        self._changed()
        count = len(removed)
        groups_text = count_text(count, "group")
        self.notice.emit(f"Removed {groups_text}. Their photos are not exported until you make groups again.")

    def merge_groups(self, group_ids: Sequence[str]) -> None:
        """Put several groups together into one, which keeps the place, the id and the name of the first.

        The first is the group that comes first in the group list. The merged
        group holds the photos of all the groups, in time order. It keeps the
        first group's pick and chosen preview; when that group has none, the
        next group that has one gives its own. The references any of the
        groups used, and the versions typed for any of them, stay with it.

        Args:
            group_ids: Ids of the groups; nothing happens with fewer than two known groups.
        """
        project = self._project
        if project is None:
            return
        chosen = set(group_ids)
        groups = [group for group in project.groups if group.id in chosen]
        if len(groups) < 2:
            return
        first = groups[0]
        others = groups[1:]
        merged = self._merged_group(groups)
        other_ids = [group.id for group in others]
        project.merge_groups(merged, other_ids)
        for group in groups:
            self._versions.pop(group.id, None)
        # Versions being made for these groups show the groups as they were.
        outdated = self._rendering & chosen
        self._outdated_renders.update(outdated)
        details = {"into": first.id, "groups": other_ids}
        self._services.history_log.record("merge groups", details)
        self.groups_changed.emit()
        self.choices_changed.emit()
        self.option_groups_changed.emit(first.id)
        self._changed()
        group_count = len(groups)
        groups_text = count_text(group_count, "group")
        photos_text = count_text(merged.size, "photo")
        self.notice.emit(f"Merged {groups_text} into {first.title}, which now holds {photos_text}.")

    def rename_group(self, group_id: str, title: str) -> None:
        """Give a group a name of the user's own. Its picks and references stay.

        The name stays when people are renamed later; it is lost only when
        the groups are made again.

        Args:
            group_id: Id of the group.
            title: The new name.
        """
        project = self._project
        if project is None:
            return
        cleaned = title.strip()
        group = project.group(group_id)
        if group is None or not cleaned or cleaned == group.title:
            return
        groups = []
        for current in project.groups:
            if current.id == group_id:
                current = current.renamed_to(cleaned)
            groups.append(current)
        project.replace_groups(groups)
        details = {"group": group_id, "title": cleaned}
        self._services.history_log.record("rename group", details)
        self.groups_changed.emit()
        self._changed()

    def merge_people(self, person_ids: Sequence[str]) -> None:
        """Treat several people as one, when the face finder split one person in two.

        Args:
            person_ids: Ids of the people; the first one keeps its name.
        """
        project = self._project
        if project is None or len(person_ids) < 2:
            return
        keep_id = person_ids[0]
        for other_id in person_ids[1:]:
            project.merge_people(keep_id, other_id)
        self.faces_changed.emit()
        if project.grouping.by_people:
            self.make_groups()
        self._changed()

    def face_image(self, face: Face) -> QImage:
        """The small picture of a face, for the people list.

        Args:
            face: The face.

        Returns:
            Its picture.
        """
        image = self._face_images.get(face.face_id)
        if image is None:
            image = self._converter.to_qimage(face.thumbnail)
            self._face_images[face.face_id] = image
        return image

    # ----------------------------------------------------------------- groups

    def make_groups(self, grouping: GroupSettings | None = None) -> None:
        """Put the kept photos into groups.

        Grouping by people first looks for faces in the photos that have not
        been searched yet, then groups.

        Args:
            grouping: New grouping options, or None to use the project's.
        """
        project = self._project
        if project is None:
            return
        if grouping is not None:
            project.grouping = grouping
        options = project.grouping
        kept = project.kept_photos()
        if options.by_people:
            missing = [photo for photo in kept if not project.faces_searched(photo.id)]
            if missing:
                self.find_faces(then_group=True)
                return
            grouper = FaceGrouper()
        else:
            grouper = SimilarityGrouper(options.max_gap_minutes, options.min_similarity)
        groups = grouper.make_groups(kept, project)
        project.set_groups(groups)
        self._versions.clear()
        self.groups_changed.emit()
        self.choices_changed.emit()
        self._changed()

    # ------------------------------------------------- references and options

    def add_history(self, paths: Sequence[Path], group_id: str | None = None) -> None:
        """Make an option from photos the user picked before.

        Each darktable edit (.xmp file) among the paths becomes an option of its own.

        Args:
            paths: Folders and files of those photos.
            group_id: The group the option is for; None makes it an option for every group.
        """
        if self._project is None or not paths:
            return
        photo_paths = self._add_darktable_edits(paths, group_id, False)
        if not photo_paths:
            return
        services = self._services
        builder = HistoryPipelineBuilder(photo_paths, services.finder, services.measurer)
        self._build_pipeline("Learning from your history", builder, "history", group_id)

    def add_examples(self, paths: Sequence[Path], group_id: str | None = None) -> None:
        """Make options from example files the user selects now.

        Each darktable edit among the files becomes an option of its own,
        which applies that edit to every photo of the group: an .xmp file, or
        a raw file whose sidecar holds the user's own darktable edit. The
        other files make one option, which matches their brightness.

        Args:
            paths: The example files.
            group_id: The group the options are for; None makes them options for every group.
        """
        if self._project is None or not paths:
            return
        photo_paths = self._add_darktable_edits(paths, group_id, True)
        if not photo_paths:
            return
        services = self._services
        builder = ExamplePipelineBuilder(
            photo_paths, services.finder, services.reader, services.measurer, services.darktable
        )
        self._build_pipeline("Learning from your examples", builder, "examples", group_id)

    def search_internet(self, query: str, group_id: str | None = None) -> None:
        """Make an option from photos found on the internet.

        Args:
            query: What to search for.
            group_id: The group the option is for; None makes it an option for every group.
        """
        project = self._project
        cleaned = query.strip()
        if project is None or not cleaned:
            return
        folder = project.folder / "references" / "internet"
        services = self._services
        builder = InternetPipelineBuilder(cleaned, services.web_search, services.measurer, folder)
        self._build_pipeline(f'Searching for "{cleaned}"', builder, "internet", group_id)

    def add_words(self, text: str, group_id: str | None = None) -> None:
        """Make an option from words the user typed in the References step.

        The app's own phrases are tried first; when they do not cover the
        words and Claude may be asked, Claude reads them in the background.
        The outcome arrives through ``words_answered``.

        Args:
            text: What the user typed, such as "brighter, more contrast".
            group_id: The group the option is for; None makes it an option for every group.
        """
        if self._project is None:
            return
        parsed = self._services.parser.parse(text)
        if parsed.is_complete:
            self._add_words_option(text, parsed.steps, "", group_id)
            return
        handler = partial(self._on_claude_read_for_references, group_id)
        retry = partial(self.add_words, text, group_id)
        self._ask_claude_or_explain(self.REFERENCES_TARGET, text, parsed.unknown, handler, retry)

    def remove_option_from_group(self, group_id: str, pipeline_id: str) -> None:
        """Take an option out of one group, and out of the project once no group uses it.

        Args:
            group_id: Id of the group.
            pipeline_id: Id of the option.
        """
        project = self._project
        if project is None or pipeline_id == RefinementPipeline.CAMERA_ID:
            return
        self.set_option_used(group_id, pipeline_id, False)
        users = [group.id for group in project.groups if project.option_used_in(group.id, pipeline_id)]
        if not users:
            self.remove_pipeline(pipeline_id)

    def remove_pipeline(self, pipeline_id: str) -> None:
        """Remove a shared option. The camera option stays.

        Args:
            pipeline_id: Id of the option.
        """
        project = self._project
        if project is None:
            return
        project.remove_pipeline(pipeline_id)
        self._versions.clear()
        self.pipelines_changed.emit()
        self.choices_changed.emit()
        self._changed()

    # ----------------------------------------------------------------- refine

    def options_for(self, group_id: str) -> list[RefinementPipeline]:
        """The options shown for a group in the Refine step.

        They are the shared options, a slightly brighter and a slightly
        darker copy of the newest reference option (or of the unchanged photo),
        and the options typed for this group.

        Args:
            group_id: Id of the group.

        Returns:
            The options, each id once.
        """
        project = self._project
        if project is None:
            return []
        shared = [option for option in project.pipelines if project.option_used_in(group_id, option.id)]
        base = self._variant_base(shared)
        brighter_step = ExposureStep(self.VARIANT_STOPS)
        darker_step = ExposureStep(-self.VARIANT_STOPS)
        brighter = base.extended(f"{base.id}~brighter", f"{base.name}, a little brighter", [brighter_step])
        darker = base.extended(f"{base.id}~darker", f"{base.name}, a little darker", [darker_step])
        own = project.group_pipelines(group_id)
        candidates = [*shared, brighter, darker, *own]
        options: list[RefinementPipeline] = []
        seen: set[str] = set()
        for option in candidates:
            if option.id not in seen:
                seen.add(option.id)
                options.append(option)
        return options

    def versions(self, group_id: str) -> list[VersionPreview]:
        """The versions of a group's sample photo made so far.

        Args:
            group_id: Id of the group.

        Returns:
            The versions; empty when they have not been made yet, or were made
            on a photo that no longer stands for the group, because the
            selection of its photos changed.
        """
        versions = self._versions.get(group_id, [])
        if not self._made_on_sample(group_id, versions):
            return []
        return list(versions)

    def sample_photo(self, group_id: str) -> Photo | None:
        """The photo the versions of a group are made on: the sharpest of its selected photos.

        Args:
            group_id: Id of the group.

        Returns:
            The photo, or None when the group is unknown or has no photos left.
        """
        project = self._project
        group = project.group(group_id) if project is not None else None
        if group is None:
            return None
        return project.sample_of(group)

    def render_versions(self, group_id: str) -> None:
        """Make every option's version of a group's sample photo, in the background.

        Args:
            group_id: Id of the group.
        """
        project = self._project
        if project is None or group_id in self._rendering:
            return
        group = project.group(group_id)
        if group is None:
            return
        sample = project.sample_of(group)
        if sample is None:
            return
        group_options = self.options_for(group_id)
        options = [self._option_for_photo(sample, option) for option in group_options]
        faces = project.faces_of(sample.id)
        self._rendering.add(group_id)
        sharpen = project.export.sharpen
        job = partial(self._versions_job, group_id, sample, options, faces, sharpen)
        failed = partial(self._on_versions_failed, group_id)
        self._tasks.start("Making the versions to compare", job, self._on_versions_ready, failed)

    def recalculate_versions(self, group_id: str) -> None:
        """Forget every version made so far and make the versions of one group again.

        Useful after a darktable edit changed in darktable: the options point at
        its file, so new versions show the new edit. The other groups' versions
        are made again when they are shown next.

        Args:
            group_id: Id of the group shown now.
        """
        self._versions.clear()
        if group_id in self._rendering:
            self._outdated_renders.add(group_id)
            return
        self.render_versions(group_id)

    def try_words(self, group_id: str, base_id: str | None, text: str) -> None:
        """Make a new option for one group from typed words, on top of another option.

        The new option is picked for the group at once, since the user typed
        it because nothing else fitted. As with :meth:`add_words`, Claude
        reads words the app's own phrases do not cover, and the outcome
        arrives through ``words_answered``.

        Args:
            group_id: Id of the group.
            base_id: Id of the option to start from; None starts from the unchanged photo.
            text: What the user typed, such as "brighter faces, less contrast".
        """
        if self._project is None:
            return
        parsed = self._services.parser.parse(text)
        if parsed.is_complete:
            self._add_typed_option(group_id, base_id, text, parsed.steps, "")
            return
        handler = partial(self._on_claude_read_for_group, group_id, base_id)
        retry = partial(self.try_words, group_id, base_id, text)
        self._ask_claude_or_explain(group_id, text, parsed.unknown, handler, retry)

    def set_option_used(self, group_id: str, pipeline_id: str, used: bool) -> None:
        """Turn a shared option on or off for one group.

        Args:
            group_id: Id of the group.
            pipeline_id: Id of the option.
            used: True to show the option in the group's Refine step.
        """
        project = self._project
        if project is None:
            return
        project.set_option_used(group_id, pipeline_id, used)
        self._versions.pop(group_id, None)
        self.option_groups_changed.emit(group_id)
        self.choices_changed.emit()
        self._changed()

    def select_photos(self, photo_ids: Sequence[str], selected: bool) -> None:
        """Select photos (keep them) or unselect them (set them aside), for example within a group.

        Args:
            photo_ids: Ids of the photos.
            selected: True to keep them, False to set them aside.
        """
        decision = Decision.KEEP if selected else Decision.SET_ASIDE
        self.decide(photo_ids, decision)

    def choose(self, group_id: str, pipeline_id: str | None) -> None:
        """Store the option the user picked for a group.

        Args:
            group_id: Id of the group.
            pipeline_id: Id of the option, or None to skip the group.
        """
        project = self._project
        if project is None:
            return
        name = "skipped"
        if pipeline_id is not None:
            option = project.pipeline(pipeline_id)
            if option is None:
                option = self._find_option(group_id, pipeline_id)
                if option is None:
                    return
                # Brighter and darker copies are made on the fly; keep the one that was picked.
                project.add_group_pipeline(group_id, option)
            name = option.name
        project.choose(group_id, pipeline_id)
        details = {"group": group_id, "option": name}
        self._services.history_log.record("pick", details)
        self.choices_changed.emit()
        self._changed()

    # ------------------------------------------------- darktable and previews

    def open_in_darktable(self, photo_id: str) -> None:
        """Open a photo in darktable, where the user can edit it.

        darktable writes the edit into the photo's sidecar file. The app reads
        it from there: the photo is developed with it, and "Apply sidecar to
        the group" gives it to the other photos of its group.

        Args:
            photo_id: Id of the photo.
        """
        project = self._project
        photo = project.photo(photo_id) if project is not None else None
        if photo is None:
            return
        try:
            self._services.darktable_launcher.open(photo.path)
        except DarktableError as error:
            message = str(error)
            self.problem.emit(message)
            return
        self.notice.emit(f"Opening {photo.name} in darktable.")

    def choose_sample(self, group_id: str, photo_id: str | None) -> None:
        """Let a photo stand for its group (the group's preview), or go back to the sharpest selected photo.

        The preview is the photo the Refine step shows the options on, the
        picture of the group in the group lists, and the photo the group's
        right-click menu opens and takes the sidecar from.

        Args:
            group_id: Id of the group.
            photo_id: Id of a photo of the group, or None for the sharpest selected photo.
        """
        project = self._project
        group = project.group(group_id) if project is not None else None
        if group is None:
            return
        if photo_id is not None and not group.contains(photo_id):
            return
        project.choose_sample(group_id, photo_id)
        details = {"group": group_id, "photo": photo_id}
        self._services.history_log.record("preview", details)
        self.sample_changed.emit(group_id)
        self._changed()

    def refresh_problem(self, photo_ids: Sequence[str]) -> str:
        """Say why the previews of some photos cannot be refreshed, if they cannot.

        Args:
            photo_ids: Ids of the photos.

        Returns:
            A short reason, such as "not a raw file"; empty when at least one
            of the photos can be refreshed.
        """
        if not self.can_refresh_previews:
            return "darktable-cli not found"
        raws = self._raw_photos(photo_ids)
        if raws:
            return ""
        if len(photo_ids) == 1:
            return "not a raw file"
        return "no raw files"

    def raw_count(self, photo_ids: Sequence[str]) -> int:
        """How many of some photos are raw files, the photos whose previews a refresh develops.

        Args:
            photo_ids: Ids of the photos.

        Returns:
            The number of raw files among them.
        """
        raws = self._raw_photos(photo_ids)
        return len(raws)

    def refresh_previews(self, photo_ids: Sequence[str]) -> None:
        """Develop the previews of some photos again with darktable, so they show their sidecars' edits.

        A raw photo's thumbnail is first made from the preview the camera
        stores in the file, which knows nothing of darktable. A refresh
        develops each raw photo with its own sidecar, in the background, and
        shows the picture in the photo grids and the group lists. The
        pictures are kept in the cache folder: a photo whose sidecar did not
        change since its last refresh gets its picture at once, also when the
        project opens again. Other image files already show what they hold,
        so they are left out.

        Args:
            photo_ids: Ids of the photos, in the order to develop them.
        """
        self._start_refresh(photo_ids, True)

    def refresh_group_previews(self, group_ids: Sequence[str]) -> None:
        """Refresh the previews of every photo of some groups, the photos that stand for the groups first.

        Args:
            group_ids: Ids of the groups.
        """
        photo_ids = self._preview_ids(group_ids)
        others = self.photos_of_groups(group_ids)
        photo_ids.extend(others)
        self._start_refresh(photo_ids, True)

    def check_edits(self) -> None:
        """Look again, in the background, for photos the user edited in darktable since the last look.

        The window asks for this when it becomes active again, for example
        after the user edited a photo in darktable, and the Group and Refine
        steps ask when they open. Only the sidecars' file times are checked;
        a sidecar is read again only when it changed. A photo the user edited
        stands for its group, unless the user chose another photo, and its
        preview is developed again so it shows the new edit.
        """
        project = self._project
        if project is None or self._checking_edits or self._scan_task is not None:
            return
        photos = [photo for photo in project.photos if photo.is_raw]
        if not photos:
            return
        self._checking_edits = True
        job = partial(self._edits_job, photos)
        self._tasks.start("Looking for darktable edits", job, self._on_edits_checked, self._on_edits_check_failed, quiet=True)

    def edit_problem(self, photo_id: str) -> str:
        """Say why a photo's sidecar cannot be applied to other photos or groups, if it cannot.

        Args:
            photo_id: Id of the photo.

        Returns:
            A short reason, such as "no darktable edit yet"; empty when the sidecar can be applied.
        """
        project = self._project
        photo = project.photo(photo_id) if project is not None else None
        if photo is None:
            return "photo not found"
        if not photo.is_raw:
            return "not a raw file"
        edit_file = DarktableEdit.edit_file_for(photo.path)
        if edit_file is None:
            return "no darktable edit yet"
        return ""

    def apply_edit_to_groups(self, source: Path, group_ids: Sequence[str]) -> None:
        """Apply a darktable edit to every photo of some groups (group to group, image to group).

        The edit is written into the sidecar of each raw photo of the groups,
        as darktable's paste of a history does, so darktable opens the photos
        with the edit as a starting point. Each old sidecar is copied to the
        project's backup folder first. A group whose pick carries another
        darktable edit, or that has no pick yet, gets the unchanged option, so
        its photos are exported with their sidecars. The photo the edit comes
        from keeps its sidecar as it is. Afterwards the groups' previews are
        developed with their new sidecars, so the group lists show the edit.

        Args:
            source: An XMP sidecar file, or a raw file whose sidecar holds the user's own edit.
            group_ids: Ids of the groups.
        """
        project = self._project
        if project is None:
            return
        groups = [project.group(group_id) for group_id in group_ids]
        targets = [group for group in groups if group is not None]
        edit = self._read_edit(source)
        if edit is None or not targets:
            return
        photo_ids: list[str] = []
        for group in targets:
            photo_ids.extend(group.photo_ids)
        written, backup_folder = self._write_sidecars(edit, photo_ids)
        if not written:
            return
        for group in targets:
            self._use_sidecars(group.id)
        group_ids_done = [group.id for group in targets]
        edit_text = str(edit.path)
        details = {"groups": group_ids_done, "photos": written, "sidecar": edit_text}
        self._services.history_log.record("apply sidecar to groups", details)
        self._sidecars_written(written)
        # The pictures of the groups show the edit at once; "Refresh previews" does all their photos.
        preview_ids = self._preview_ids(group_ids_done)
        self._start_refresh(preview_ids, False)
        if len(targets) == 1:
            target_text = targets[0].title
        else:
            group_count = len(targets)
            target_text = count_text(group_count, "group")
        written_count = len(written)
        photos_text = count_text(written_count, "photo")
        backup = self._backup_text(backup_folder)
        self.notice.emit(f"Wrote the edit of {edit.path.name} into {photos_text} of {target_text}.{backup}")

    def apply_edit_to_photos(self, source: Path, photo_ids: Sequence[str]) -> None:
        """Apply a darktable edit to single photos (group to image, image to image).

        The edit is written into each photo's sidecar, as darktable's paste of
        a history does, so darktable opens the photo with the edit as a
        starting point; the old sidecar is copied to the project's backup
        folder first. The photo then keeps its own sidecar in the app too,
        even when its group picks another darktable edit; the pick's other
        steps still apply. Only raw files take a darktable edit. Afterwards
        the photos' previews are developed with their new sidecars.

        Args:
            source: An XMP sidecar file, or a raw file whose sidecar holds the user's own edit.
            photo_ids: Ids of the photos.
        """
        project = self._project
        if project is None:
            return
        edit = self._read_edit(source)
        if edit is None:
            return
        written, backup_folder = self._write_sidecars(edit, photo_ids)
        if not written:
            return
        writer = self._services.sidecars
        for photo_id in written:
            photo = project.photo(photo_id)
            sidecar = writer.sidecar_of(photo.path)
            project.set_photo_edit(photo_id, sidecar)
        edit_text = str(edit.path)
        details = {"photos": written, "sidecar": edit_text}
        self._services.history_log.record("apply sidecar to photos", details)
        self._sidecars_written(written)
        self._start_refresh(written, False)
        if len(written) == 1:
            first = project.photo(written[0])
            target_text = first.name
        else:
            written_count = len(written)
            target_text = count_text(written_count, "photo")
        backup = self._backup_text(backup_folder)
        self.notice.emit(f"Wrote the edit of {edit.path.name} into {target_text}.{backup}")

    def remove_photo_edits(self, photo_ids: Sequence[str]) -> None:
        """Let photos follow their group's pick again, after a sidecar was applied to them alone.

        Their sidecar files stay as they are; they count whenever the group's
        pick carries no darktable edit of its own.

        Args:
            photo_ids: Ids of the photos.
        """
        project = self._project
        if project is None:
            return
        removed = [photo_id for photo_id in photo_ids if project.photo_edit_of(photo_id) is not None]
        for photo_id in removed:
            project.set_photo_edit(photo_id, None)
        if not removed:
            return
        details = {"photos": removed}
        self._services.history_log.record("follow the group's pick", details)
        self._sidecars_written(removed, False)
        removed_count = len(removed)
        photos_text = count_text(removed_count, "photo")
        self.notice.emit(f"{photos_text} follow their group's pick again.")

    def photos_of_groups(self, group_ids: Sequence[str]) -> list[str]:
        """The photos of some groups.

        Args:
            group_ids: Ids of the groups.

        Returns:
            Ids of their photos, group by group.
        """
        project = self._project
        photo_ids: list[str] = []
        if project is None:
            return photo_ids
        for group_id in group_ids:
            group = project.group(group_id)
            if group is not None:
                photo_ids.extend(group.photo_ids)
        return photo_ids

    def own_edit_names(self, photo_ids: Sequence[str], source: Path) -> list[str]:
        """The photos among some that hold a darktable edit the user made, which applying an edit would replace.

        Args:
            photo_ids: Ids of the photos.
            source: The file the edit comes from; its own photo is left out.

        Returns:
            The names of those photos.
        """
        project = self._project
        names: list[str] = []
        if project is None:
            return names
        source_sidecar = self._sidecar_of_source(source)
        for photo_id in photo_ids:
            photo = project.photo(photo_id)
            if photo is None or not project.edited_by_user(photo_id):
                continue
            sidecar = self._services.sidecars.sidecar_of(photo.path)
            if self._same_file(sidecar, source_sidecar):
                continue
            names.append(photo.name)
        return names

    def group_edit_sources(self, except_ids: Sequence[str] = ()) -> list[EditSource]:
        """The groups whose preview holds the user's own darktable edit, as sources to apply.

        Args:
            except_ids: Ids of groups to leave out, such as the group the edit would go to.

        Returns:
            One source per group, in the order of the groups; its file is the preview's raw file.
        """
        project = self._project
        if project is None:
            return []
        sources: list[EditSource] = []
        for group in project.groups:
            if group.id in except_ids:
                continue
            sample = project.sample_of(group)
            if sample is None or project.edited_at(sample.id) is None:
                continue
            label = f"{group.title}  ({sample.name})"
            source = EditSource(label, sample.path)
            sources.append(source)
        return sources

    def photo_edit_sources(self, except_ids: Sequence[str] = (), limit: int = 20) -> list[EditSource]:
        """The photos the user edited in darktable themselves, as sources to apply, the latest edit first.

        Args:
            except_ids: Ids of photos to leave out, such as the photo the edit would go to.
            limit: Most sources to give; older edits can be chosen as files.

        Returns:
            One source per photo; its label names the photo's group.
        """
        project = self._project
        if project is None:
            return []
        edited = [photo for photo in project.photos if project.edited_by_user(photo.id)]
        edited.sort(key=self._edit_time_of, reverse=True)
        sources: list[EditSource] = []
        for photo in edited:
            if photo.id in except_ids:
                continue
            group_title = self._group_title_of(photo.id)
            label = f"{photo.name}  ({group_title})"
            source = EditSource(label, photo.path)
            sources.append(source)
            if len(sources) >= limit:
                break
        return sources

    # ----------------------------------------------------------------- export

    def export_plan(self) -> ExportPlan:
        """Work out what an export would write.

        Returns:
            Every kept photo of the groups with a pick, and the number of
            skipped and not yet picked groups.
        """
        project = self._project
        items: list[tuple[Photo, RefinementPipeline]] = []
        skipped = 0
        unpicked = 0
        if project is None:
            return ExportPlan(items, skipped, unpicked)
        for group in project.groups:
            choice = project.choice_of(group.id)
            if choice is None:
                unpicked += 1
                continue
            if choice.pipeline_id is None:
                skipped += 1
                continue
            pipeline = project.pipeline(choice.pipeline_id)
            if pipeline is None:
                unpicked += 1
                continue
            for photo_id in group.photo_ids:
                photo = project.photo(photo_id)
                decision = project.decision_of(photo_id)
                if photo is None or decision is None or not decision.is_kept:
                    continue
                photo_option = self._option_for_photo(photo, pipeline)
                items.append((photo, photo_option))
        return ExportPlan(items, skipped, unpicked)

    def export(self, settings: ExportSettings) -> None:
        """Refine and write every photo of the groups that have a pick.

        Args:
            settings: Folder, size, quality and metadata options.
        """
        project = self._project
        if project is None:
            return
        project.export = settings
        self._changed()
        plan = self.export_plan()
        if not plan.items:
            self.problem.emit("There is nothing to export yet. Pick an option for at least one group in the Refine step.")
            return
        self._start_export(plan.items)

    @property
    def export_folder(self) -> Path:
        """The folder exports go to: the one set in the Export step, or the project's own export folder."""
        project = self._project
        if project is None:
            return Path()
        folder_text = project.export.output_folder
        if folder_text:
            return Path(folder_text)
        return project.default_export_folder

    def is_skipped(self, group_id: str) -> bool:
        """Tell whether the user skipped a group in the Refine step, which leaves it out of exports.

        Args:
            group_id: Id of the group.

        Returns:
            True when the group is skipped.
        """
        project = self._project
        choice = project.choice_of(group_id) if project is not None else None
        return choice is not None and choice.pipeline_id is None

    def group_of_photo(self, photo_id: str) -> PhotoGroup | None:
        """The group a photo is in.

        Args:
            photo_id: Id of the photo.

        Returns:
            The group, or None when the photo is in no group.
        """
        project = self._project
        if project is None:
            return None
        for group in project.groups:
            if group.contains(photo_id):
                return group
        return None

    def export_groups(self, group_ids: Sequence[str]) -> None:
        """Export the selected photos of some groups, with the settings of the Export step.

        Each photo gets its group's pick, as in the Export step. A group
        without a pick yet is exported unchanged: raw files as darktable
        develops them with their own sidecars, other files as they are. A
        skipped group is left out.

        Args:
            group_ids: Ids of the groups.
        """
        project = self._project
        if project is None:
            return
        items: list[tuple[Photo, RefinementPipeline]] = []
        skipped = 0
        for group_id in group_ids:
            group = project.group(group_id)
            if group is None:
                continue
            if self.is_skipped(group_id):
                skipped += 1
                continue
            option = self._export_option_of(group_id)
            photos = project.selected_photos_of(group)
            for photo in photos:
                photo_option = self._option_for_photo(photo, option)
                items.append((photo, photo_option))
        skipped_text = count_text(skipped, "skipped group")
        if not items:
            if skipped:
                self.problem.emit(
                    f"Nothing was exported: {skipped_text} left out. Pick an option for a group in the Refine step to export it."
                )
            else:
                self.problem.emit("Nothing was exported: no photo of these groups is selected.")
            return
        self._start_export(items)
        if skipped:
            self.notice.emit(f"Left out of the export: {skipped_text}.")

    def export_photos(self, photo_ids: Sequence[str]) -> None:
        """Export single photos, with the settings of the Export step, whether or not they are selected.

        Each photo gets its group's pick. A photo whose group has no pick, or
        is skipped, and a photo in no group, are exported unchanged.

        Args:
            photo_ids: Ids of the photos.
        """
        project = self._project
        if project is None:
            return
        items: list[tuple[Photo, RefinementPipeline]] = []
        for photo_id in photo_ids:
            photo = project.photo(photo_id)
            if photo is None:
                continue
            group = self.group_of_photo(photo_id)
            option = RefinementPipeline.camera() if group is None else self._export_option_of(group.id)
            photo_option = self._option_for_photo(photo, option)
            items.append((photo, photo_option))
        if items:
            self._start_export(items)

    # ----------------------------------------------------------------- images

    def thumbnail(self, photo_id: str) -> QImage | None:
        """The thumbnail of a photo: made from the camera's preview, or developed by darktable after a refresh.

        Args:
            photo_id: Id of the photo.

        Returns:
            The thumbnail, or None when the photo has not been read yet.
        """
        return self._thumbnails.get(photo_id)

    def load_preview(self, photo_id: str, receiver: Callable[[str, QImage], None]) -> None:
        """Load a large preview of a photo in the background.

        Args:
            photo_id: Id of the photo.
            receiver: Gets the photo id and the picture, on the window thread.
        """
        project = self._project
        if project is None:
            return
        photo = project.photo(photo_id)
        if photo is None:
            return
        job = partial(self._preview_job, photo)
        handler = partial(self._deliver_preview, receiver)
        self._tasks.start("Loading the photo", job, handler, quiet=True)

    # ------------------------------------------------------- private: project

    def _open(self, project: Project) -> None:
        """Make a project the open one and start measuring its photos.

        Args:
            project: The project.
        """
        if self._project is not None:
            self.close_project()
        self._project = project
        self._clear_images()
        self._checker = QualityChecker.from_settings(project.checks)
        manifest = self._services.manifest.path_in(project.folder)
        self._settings.remember_project(manifest)
        self._save_settings()
        self.project_opened.emit()
        self.scan()

    def _changed(self) -> None:
        """Note that the project changed; it is saved a moment later."""
        self._save_timer.start()

    def _save_settings(self) -> None:
        """Write the app's own settings, ignoring a failure (they are not essential)."""
        try:
            self._settings_store.save(self._settings)
        except OSError:
            self.notice.emit("The app settings could not be saved.")

    def _sources_changed(self) -> None:
        """React to a changed list of sources: groups are made again later, photos are measured now."""
        project = self._project
        project.clear_groups()
        self._versions.clear()
        self.sources_changed.emit()
        self.groups_changed.emit()
        self._changed()
        self.scan()

    def _clear_images(self) -> None:
        """Forget the pictures of the previous project."""
        self._thumbnails.clear()
        self._face_images.clear()
        self._versions.clear()
        self._rendering.clear()

    def _on_task_failed(self, message: str) -> None:
        """Show the error of a background task.

        Args:
            message: The error message.
        """
        self.problem.emit(message)

    # ---------------------------------------------------------- private: scan

    def _scan_job(self, scan_number: int, sources: Sequence[Path], measured: set[str], context: TaskContext) -> int:
        """Find the photos and measure each one. Runs on a worker thread.

        Args:
            scan_number: Number of this scan; results of older scans are ignored.
            sources: The project's folders and files.
            measured: Ids of photos that are already measured.
            context: For progress, partial results and stop requests.

        Returns:
            The scan number.
        """
        photos = self._services.finder.find(sources)
        found = FoundPhotos(scan_number, photos)
        context.send(found)
        total = len(photos)
        for done, photo in enumerate(photos):
            if context.stop_requested:
                break
            context.report_item(done, total, photo.name)
            if photo.id not in measured:
                item = self._scan_one(scan_number, photo)
                context.send(item)
        context.report(total, total)
        return scan_number

    def _scan_one(self, scan_number: int, photo: Photo) -> ScannedPhoto | UnreadablePhoto:
        """Read and measure one photo. Runs on a worker thread.

        Args:
            scan_number: Number of the scan.
            photo: The photo.

        Returns:
            The measured photo, or a note that it could not be read.
        """
        try:
            data = self._services.reader.read(photo, PhotoAnalyzer.ANALYSIS_SIDE)
        except PhotoReadError as error:
            message = str(error)
            return UnreadablePhoto(scan_number, photo.id, message)
        analysis = self._services.analyzer.analyze(data.pixels)
        picture = self._services.thumbnails.kept(photo)
        if picture is None:
            picture = analysis.thumbnail
        thumbnail = self._converter.to_qimage(picture)
        edited_at = self._services.edits.edited_at(photo)
        return ScannedPhoto(scan_number, photo.id, data.info, analysis, thumbnail, edited_at)

    def _on_scan_item(self, item: object) -> None:
        """Store one partial result of the scan in the project.

        Args:
            item: A :class:`FoundPhotos`, :class:`ScannedPhoto` or :class:`UnreadablePhoto`.
        """
        project = self._project
        if project is None or item.scan_number != self._scan_number:
            return
        if isinstance(item, FoundPhotos):
            project.set_photos(item.photos)
            self._forget_missing_thumbnails()
            self.photos_changed.emit()
            return
        if isinstance(item, UnreadablePhoto):
            self.notice.emit(item.message)
            return
        photo = project.photo(item.photo_id)
        if photo is None:
            return
        photo.info = item.info
        result = self._checker.evaluate(item.analysis.scores)
        project.set_analysis(item.photo_id, result, item.analysis.summary)
        project.set_edited_at(item.photo_id, item.edited_at)
        self._thumbnails[item.photo_id] = item.thumbnail
        self.photo_updated.emit(item.photo_id)

    def _on_scan_finished(self, scan_number: int) -> None:
        """Tell the pages that the scan is done.

        Args:
            scan_number: Number of the finished scan.
        """
        if scan_number != self._scan_number:
            return
        self._scan_task = None
        self.photos_changed.emit()
        self.analysis_changed.emit()
        project = self._project
        if project is not None:
            photos_text = count_text(project.analyzed_count, "photo")
            self.notice.emit(f"{photos_text} measured.")

    def _forget_missing_thumbnails(self) -> None:
        """Drop the thumbnails of photos that are no longer in the project."""
        project = self._project
        kept = {photo_id: image for photo_id, image in self._thumbnails.items() if project.photo(photo_id) is not None}
        self._thumbnails = kept

    def _record_decision(self, photo_id: str, decision: Decision | None, result: object) -> None:
        """Add the user's decision to the history log, with the app's own decision.

        Args:
            photo_id: Id of the photo.
            decision: The user's decision, or None for "back to the app's decision".
            result: The photo's check results, or None.
        """
        app_decision = result.decision.value if result is not None else None
        user_decision = decision.value if decision is not None else "automatic"
        details = {"photo": photo_id, "user": user_decision, "app": app_decision}
        self._services.history_log.record("decision", details)

    # ------------------------------------------------ private: darktable edits

    def _edits_job(self, photos: Sequence[Photo], context: TaskContext) -> dict[str, float | None]:
        """Find out which photos the user edited in darktable, and when. Runs on a worker thread.

        Args:
            photos: The raw photos of the project.
            context: Not used; the look is quick.

        Returns:
            For each photo id, when the user last edited the photo, or None.
        """
        found: dict[str, float | None] = {}
        for photo in photos:
            found[photo.id] = self._services.edits.edited_at(photo)
        return found

    def _on_edits_checked(self, found: dict[str, float | None]) -> None:
        """Store the darktable edits found, and make the versions again when edits changed.

        Args:
            found: For each photo id, when the user last edited the photo, or None.
        """
        self._checking_edits = False
        project = self._project
        if project is None:
            return
        changed: list[str] = []
        changed_ids: list[str] = []
        for photo_id, edited_at in found.items():
            photo = project.photo(photo_id)
            if photo is None or project.edited_at(photo_id) == edited_at:
                continue
            project.set_edited_at(photo_id, edited_at)
            changed.append(photo.name)
            changed_ids.append(photo_id)
        if not changed:
            return
        # The versions show the old edits; the shown group's versions are made again.
        self._versions.clear()
        self._outdated_renders.update(self._rendering)
        self.edits_changed.emit()
        # The edited photos' previews are developed again, so they show the new edits.
        self._start_refresh(changed_ids, False)
        changed_count = len(changed)
        if changed_count == 1:
            self.notice.emit(f"Noticed a new darktable edit of {changed[0]}.")
            return
        photos_text = count_text(changed_count, "photo")
        self.notice.emit(f"Noticed new darktable edits of {photos_text}.")

    def _on_edits_check_failed(self, message: str) -> None:
        """Let the next look for darktable edits start; a failed look is not worth a message.

        Args:
            message: Why the look failed (not shown).
        """
        self._checking_edits = False

    # ------------------------------------------------------- private: sidecars

    def _option_for_photo(self, photo: Photo, option: RefinementPipeline) -> RefinementPipeline:
        """The option as it applies to one photo: with the photo's own sidecar when a sidecar was applied to it alone.

        Args:
            photo: The photo.
            option: The option its group picks, or one of the group's options.

        Returns:
            The option, or a copy of it with the photo's own edit in place of the option's darktable edit.
        """
        edit_file = self._project.photo_edit_of(photo.id)
        if edit_file is None:
            return option
        return option.with_darktable_edit(edit_file)

    def _read_edit(self, source: Path) -> DarktableEdit | None:
        """Read the darktable edit to apply, or say why it cannot be applied.

        Args:
            source: An XMP sidecar file, or a raw file whose sidecar holds the user's own edit.

        Returns:
            The edit, or None after a problem was shown.
        """
        edit_file = DarktableEdit.edit_file_for(source)
        if edit_file is None:
            self.problem.emit(f"{source.name} holds no darktable edit of your own yet. Edit it in darktable first.")
            return None
        try:
            return DarktableEdit.read(edit_file)
        except DarktableEditError as error:
            message = str(error)
            self.problem.emit(message)
            return None

    def _write_sidecars(self, edit: DarktableEdit, photo_ids: Sequence[str]) -> tuple[list[str], Path | None]:
        """Write an edit into the sidecars of some photos, after copying their old sidecars to a backup folder.

        Photos that are not raw files, and the photo the edit belongs to, are left out.

        Args:
            edit: The edit.
            photo_ids: Ids of the photos.

        Returns:
            Ids of the photos whose sidecar was written, and the backup folder
            when an old sidecar was copied there (otherwise None).
        """
        project = self._project
        writer = self._services.sidecars
        backup_folder = self._new_backup_folder()
        written: list[str] = []
        backed_up = False
        for photo_id in photo_ids:
            photo = project.photo(photo_id)
            if photo is None or not photo.is_raw:
                continue
            sidecar = writer.sidecar_of(photo.path)
            if self._same_file(sidecar, edit.path):
                continue
            try:
                backup = writer.write(edit, photo.path, backup_folder)
            except OSError as error:
                self.problem.emit(f"The sidecar of {photo.name} could not be written: {error}")
                break
            if backup is not None:
                backed_up = True
            written.append(photo_id)
        if not written:
            self.notice.emit("No sidecar was written: there is no other raw photo to write the edit into.")
        used_folder = backup_folder if backed_up else None
        return written, used_folder

    def _new_backup_folder(self) -> Path:
        """A new folder, named after the time, for the old sidecars of one "Apply sidecar".

        Returns:
            The folder, inside the project folder; it is made when the first sidecar is copied.
        """
        now = datetime.now()
        stamp = now.strftime("%Y-%m-%d %H-%M-%S")
        return self._project.folder / self.BACKUP_FOLDER_NAME / stamp

    def _backup_text(self, backup_folder: Path | None) -> str:
        """The sentence that says where the old sidecars went.

        Args:
            backup_folder: The backup folder, or None when no old sidecar was copied.

        Returns:
            The sentence, with a space before it; empty without a backup.
        """
        if backup_folder is None:
            return ""
        return f" The old sidecars are in {backup_folder}."

    def _use_sidecars(self, group_id: str) -> None:
        """Let a group's photos be exported with their own sidecars, after an edit was written into them.

        A group without a pick, or whose pick carries another darktable edit,
        gets the unchanged option. A skipped group stays skipped, and a pick
        without a darktable edit stays, since it develops the photos with
        their sidecars already.

        Args:
            group_id: Id of the group.
        """
        project = self._project
        choice = project.choice_of(group_id)
        if choice is not None and choice.pipeline_id is None:
            return
        if choice is not None:
            option = project.pipeline(choice.pipeline_id)
            if option is not None and option.darktable_edit is None:
                return
        self.choose(group_id, RefinementPipeline.CAMERA_ID)

    def _sidecars_written(self, photo_ids: Sequence[str], written: bool = True) -> None:
        """Bring the app up to date after photos' sidecars, or the edits applied to them alone, changed.

        Args:
            photo_ids: Ids of the photos.
            written: True when the app wrote the photos' sidecars; their edits
                then do not count as edits the user made in darktable.
        """
        project = self._project
        edits = self._services.edits
        for photo_id in photo_ids:
            photo = project.photo(photo_id)
            if photo is None:
                continue
            edited_at = edits.edited_at(photo)
            project.set_edited_at(photo_id, edited_at)
            if written:
                project.set_applied_at(photo_id, edited_at)
            self.photo_updated.emit(photo_id)
        # The versions show the old development; the shown group's versions are made again.
        self._versions.clear()
        self._outdated_renders.update(self._rendering)
        self.edits_changed.emit()
        self._changed()

    def _sidecar_of_source(self, source: Path) -> Path | None:
        """The sidecar file an edit is read from.

        Args:
            source: An XMP sidecar file, or a raw file.

        Returns:
            The XMP file, or None when the source holds no edit of the user's own.
        """
        return DarktableEdit.edit_file_for(source)

    def _same_file(self, first: Path | None, second: Path | None) -> bool:
        """Tell whether two paths name the same file, also through a link.

        Args:
            first: A path, or None.
            second: Another path, or None.

        Returns:
            True when both are given and lead to the same file.
        """
        if first is None or second is None:
            return False
        first_path = first.resolve()
        second_path = second.resolve()
        return first_path == second_path

    def _edit_time_of(self, photo: Photo) -> float:
        """Sort key: when the user last edited a photo in darktable.

        Args:
            photo: The photo.

        Returns:
            The time of its sidecar, or 0 when the user has not edited it.
        """
        edited_at = self._project.edited_at(photo.id)
        if edited_at is None:
            return 0.0
        return edited_at

    def _group_title_of(self, photo_id: str) -> str:
        """The title of the group a photo is in.

        Args:
            photo_id: Id of the photo.

        Returns:
            The title, or "no group".
        """
        group = self.group_of_photo(photo_id)
        if group is None:
            return "no group"
        return group.title

    # ------------------------------------------- private: refreshing previews

    def _start_refresh(self, photo_ids: Sequence[str], asked: bool) -> None:
        """Start developing the previews of some photos with darktable, in the background.

        Args:
            photo_ids: Ids of the photos, in the order to develop them; photos
                that are not raw files are left out.
            asked: True when the user asked, so the end is announced. A
                refresh the app starts by itself, after a sidecar changed,
                only tells about photos it could not develop.
        """
        if self._project is None:
            return
        if not self.can_refresh_previews:
            if asked:
                self.problem.emit(
                    "darktable-cli was not found, so the previews cannot show darktable edits. "
                    "Install darktable to refresh them."
                )
            return
        photos = self._raw_photos(photo_ids)
        if not photos:
            if asked:
                self.notice.emit("Only raw files have previews to refresh; other photos already show what the files hold.")
            return
        job = partial(self._refresh_job, photos)
        finished = partial(self._on_previews_refreshed, asked)
        self._tasks.start("Refreshing previews", job, finished, self._on_task_failed, self._on_picture_developed)

    def _raw_photos(self, photo_ids: Sequence[str]) -> list[Photo]:
        """The raw files among some photos, each once, in the order given.

        Args:
            photo_ids: Ids of the photos.

        Returns:
            The raw photos.
        """
        project = self._project
        photos: list[Photo] = []
        if project is None:
            return photos
        seen: set[str] = set()
        for photo_id in photo_ids:
            photo = project.photo(photo_id)
            if photo is None or not photo.is_raw or photo_id in seen:
                continue
            seen.add(photo_id)
            photos.append(photo)
        return photos

    def _preview_ids(self, group_ids: Sequence[str]) -> list[str]:
        """The photos that stand for some groups now.

        Args:
            group_ids: Ids of the groups.

        Returns:
            One photo id per group that has a preview, in the order of the groups.
        """
        preview_ids: list[str] = []
        for group_id in group_ids:
            sample = self.sample_photo(group_id)
            if sample is not None:
                preview_ids.append(sample.id)
        return preview_ids

    def _refresh_job(self, photos: Sequence[Photo], context: TaskContext) -> RefreshResult:
        """Develop the preview of each photo with its sidecar. Runs on a worker thread.

        Args:
            photos: The raw photos.
            context: For progress, the pictures, and stop requests.

        Returns:
            What the refresh did.
        """
        thumbnails = self._services.thumbnails
        problems: list[str] = []
        developed = 0
        total = len(photos)
        for done, photo in enumerate(photos):
            if context.stop_requested:
                break
            context.report_item(done, total, photo.name)
            try:
                pixels = thumbnails.develop(photo)
            except (DarktableError, OSError) as error:
                message = str(error)
                problems.append(message)
                continue
            image = self._converter.to_qimage(pixels)
            picture = DevelopedPicture(photo.id, image)
            context.send(picture)
            developed += 1
        tried = developed + len(problems)
        stopped = tried < total
        context.report(tried, total)
        return RefreshResult(developed, total, problems, stopped)

    def _on_picture_developed(self, picture: DevelopedPicture) -> None:
        """Show a photo's new preview in the photo grids and the group lists.

        Args:
            picture: The photo's id and its new thumbnail.
        """
        project = self._project
        if project is None or project.photo(picture.photo_id) is None:
            return
        self._thumbnails[picture.photo_id] = picture.thumbnail
        self.photo_updated.emit(picture.photo_id)
        self.thumbnail_changed.emit(picture.photo_id)

    def _on_previews_refreshed(self, asked: bool, result: RefreshResult) -> None:
        """Say how a refresh of previews went.

        Args:
            asked: True when the user asked for the refresh; otherwise only problems are told, as a notice.
            result: What the refresh did.
        """
        if result.problems:
            failed = len(result.problems)
            failed_text = count_text(failed, "preview")
            first = result.problems[0]
            message = f"{failed_text} could not be refreshed. {first}"
            if asked:
                self.problem.emit(message)
            else:
                self.notice.emit(message)
            return
        if not asked:
            return
        if result.stopped:
            self.notice.emit(f"Stopped refreshing the previews after {result.developed} of {result.total}.")
            return
        developed_text = count_text(result.developed, "preview")
        self.notice.emit(f"Refreshed {developed_text}.")

    # --------------------------------------------------------- private: faces

    def _faces_job(self, photos: Sequence[Photo], context: TaskContext) -> dict[str, list[Face]]:
        """Find the faces of some photos. Runs on a worker thread.

        Args:
            photos: The photos.
            context: For progress and stop requests.

        Returns:
            The faces by photo id; photos that could not be read get an empty list.
        """
        found: dict[str, list[Face]] = {}
        total = len(photos)
        for done, photo in enumerate(photos):
            if context.stop_requested:
                break
            context.report_item(done, total, photo.name)
            try:
                pixels = self._services.reader.load_pixels(photo, self.FACE_SIDE)
            except PhotoReadError:
                found[photo.id] = []
                continue
            faces = self._services.face_finder.find(photo.id, pixels)
            found[photo.id] = faces
        context.report(total, total)
        return found

    def _on_faces_found(self, then_group: bool, found: dict[str, list[Face]]) -> None:
        """Store the faces found, sort all faces into people, and group again when asked.

        Args:
            then_group: Make the groups again afterwards.
            found: The faces by photo id.
        """
        project = self._project
        if project is None:
            return
        project.set_faces(found)
        faces = project.all_faces()
        people = self._services.people_sorter.sort(faces)
        project.set_people(people)
        self._face_images.clear()
        people_count = len(people)
        people_text = count_text(people_count, "person", "people")
        self.notice.emit(f"Found {people_text}.")
        self.faces_changed.emit()
        self._changed()
        if then_group:
            self.make_groups()

    def _download_job(self, models: FaceModels, context: TaskContext) -> bool:
        """Download the face models. Runs on a worker thread.

        Args:
            models: The model set to download.
            context: For progress.

        Returns:
            True when done.
        """
        models.download(context.report)
        return True

    def _on_models_downloaded(self, _result: object) -> None:
        """Tell the pages that the face models are there.

        Args:
            _result: Not used.
        """
        self.notice.emit("The face models are ready.")
        self.faces_changed.emit()

    def _merged_group(self, groups: Sequence[PhotoGroup]) -> PhotoGroup:
        """The group made of several groups: the photos and people of all of them, with the first group's id and name.

        Args:
            groups: The groups, the first one first.

        Returns:
            The merged group. Its photos are in time order, and its line of
            details gives the new time range; photos missing from the project
            go last, so none is lost.
        """
        project = self._project
        first = groups[0]
        photo_ids: list[str] = []
        person_ids: list[str] = []
        for group in groups:
            for photo_id in group.photo_ids:
                if photo_id not in photo_ids:
                    photo_ids.append(photo_id)
            for person_id in group.person_ids:
                if person_id not in person_ids:
                    person_ids.append(person_id)
        found = [project.photo(photo_id) for photo_id in photo_ids]
        photos = [photo for photo in found if photo is not None]
        photos.sort(key=Photo.sort_key)
        ordered_ids = [photo.id for photo in photos]
        missing = [photo_id for photo_id in photo_ids if photo_id not in ordered_ids]
        ordered_ids.extend(missing)
        details = Grouper.time_range(photos)
        return PhotoGroup(first.id, first.title, ordered_ids, first.sample_id, details, person_ids, first.renamed)

    def _retitle_people_groups(self) -> None:
        """Give the groups made by people the current names, keeping the user's picks and own group names."""
        project = self._project
        grouper = FaceGrouper()
        groups = []
        for group in project.groups:
            if group.person_ids and not group.renamed:
                title = grouper.title_for(group.person_ids, project)
                group = group.with_title(title)
            groups.append(group)
        project.replace_groups(groups)

    # ------------------------------------------------------ private: options

    def _add_darktable_edits(self, paths: Sequence[Path], group_id: str | None, raw_edits: bool) -> list[Path]:
        """Make one option for each darktable edit among the paths.

        Args:
            paths: Files and folders the user chose as references.
            group_id: The group the options are for, or None for every group.
            raw_edits: Also treat a raw file whose sidecar holds the user's own
                edit as that edit (when darktable-cli is there to apply it);
                otherwise only .xmp files count as edits.

        Returns:
            The other paths, which are photos or folders of photos.
        """
        darktable = self._services.darktable
        photo_paths: list[Path] = []
        for path in paths:
            suffix = path.suffix.lower()
            edit_file = None
            if suffix == ".xmp" or (raw_edits and darktable.available):
                edit_file = DarktableEdit.edit_file_for(path)
            if edit_file is None:
                photo_paths.append(path)
                continue
            builder = DarktableEditPipelineBuilder(edit_file, darktable)
            self._build_pipeline(f"Reading the darktable edit {edit_file.name}", builder, "darktable", group_id)
        return photo_paths

    def _build_pipeline(self, title: str, builder: PipelineBuilder, prefix: str, group_id: str | None) -> None:
        """Build an option from references in the background.

        Args:
            title: What is being done, for the status bar.
            builder: The builder for this kind of reference.
            prefix: Start of the new option's id, such as "history".
            group_id: The group the option is for, or None for every group.
        """
        pipeline_id = self._new_pipeline_id(prefix)
        job = partial(self._pipeline_job, builder, pipeline_id)
        built = partial(self._on_pipeline_built, group_id)
        failed = partial(self._on_pipeline_failed, pipeline_id)
        self._tasks.start(title, job, built, failed)

    def _pipeline_job(self, builder: PipelineBuilder, pipeline_id: str, context: TaskContext) -> RefinementPipeline:
        """Run a builder. Runs on a worker thread.

        Args:
            builder: The builder.
            pipeline_id: Id for the new option.
            context: For progress.

        Returns:
            The new option.
        """
        return builder.build(pipeline_id, context.report_item)

    def _on_pipeline_built(self, group_id: str | None, pipeline: RefinementPipeline) -> None:
        """Add a new option to the project, for one group or for every group.

        Args:
            group_id: The group the option is for, or None for every group.
            pipeline: The new option.
        """
        self._reserved_ids.discard(pipeline.id)
        project = self._project
        if project is None:
            return
        project.add_pipeline(pipeline)
        group = project.group(group_id) if group_id else None
        if group is not None:
            self._use_only_for(group.id, pipeline.id)
        self._versions.clear()
        steps = pipeline.describe_steps()
        details = {"option": pipeline.name, "source": pipeline.source.name, "steps": steps, "group": group_id}
        self._services.history_log.record("option", details)
        self.pipelines_changed.emit()
        self._changed()
        if group is None:
            self.notice.emit(f"Added the option {pipeline.name}.")
            return
        self.notice.emit(f"Added the option {pipeline.name} for {group.title}.")

    def _options_only_for(self, group_ids: Sequence[str]) -> list[str]:
        """The options that some of these groups use and no other group does.

        When no other group is left, an option meant for every group cannot be
        told from one meant for these groups, so none is returned.

        Args:
            group_ids: Ids of the groups.

        Returns:
            The option ids.
        """
        project = self._project
        others = [group.id for group in project.groups if group.id not in group_ids]
        if not others:
            return []
        option_ids: list[str] = []
        for option in project.pipelines:
            if option.is_camera:
                continue
            used_by_others = [group_id for group_id in others if project.option_used_in(group_id, option.id)]
            used_by_these = [group_id for group_id in group_ids if project.option_used_in(group_id, option.id)]
            if used_by_these and not used_by_others:
                option_ids.append(option.id)
        return option_ids

    def _use_only_for(self, group_id: str, pipeline_id: str) -> None:
        """Turn an option off for every group but one.

        The option stays in the project, so the user can turn it on for other
        groups in the References step.

        Args:
            group_id: The group that keeps the option.
            pipeline_id: Id of the option.
        """
        project = self._project
        for group in project.groups:
            if group.id != group_id:
                project.set_option_used(group.id, pipeline_id, False)

    def _ask_claude_or_explain(
        self,
        target: str,
        text: str,
        unknown: Sequence[str],
        on_read: Callable[[str, AiReading], None],
        retry: Callable[[], None],
    ) -> None:
        """Let Claude read words the app's phrases did not cover, or say what was not understood.

        Args:
            target: Where the words were typed: the References step or a group id.
            text: What the user typed.
            unknown: The phrases the app's own reader did not understand.
            on_read: Gets the words and Claude's reading when Claude answers.
            retry: Asks again with the same words; kept when Claude Code needs a login first.
        """
        if not self.ai_ready:
            message = self._services.parser.explain(unknown)
            if self.ai_enabled:
                message = f"{message} To let Claude read any words, install Claude Code and log in."
            self.words_answered.emit(target, False, message)
            return
        job = partial(self._claude_job, text)
        handler = partial(self._on_claude_answer, target, on_read, retry, text)
        failed = partial(self._on_words_failed, target)
        self._tasks.start("Asking Claude to read your words", job, handler, failed)

    def _claude_job(self, text: str, context: TaskContext) -> AiReading | None:
        """Ask Claude to read the words. Runs on a worker thread.

        Args:
            text: What the user typed.
            context: Not used; the request is a single call.

        Returns:
            Claude's reading, or None when Claude Code needs a login first.
        """
        try:
            return self._services.ai_reader.read(text)
        except AiLoginNeeded:
            return None

    def _on_claude_answer(
        self,
        target: str,
        on_read: Callable[[str, AiReading], None],
        retry: Callable[[], None],
        text: str,
        reading: AiReading | None,
    ) -> None:
        """Use Claude's reading, or offer the login when Claude Code is not logged in.

        Args:
            target: Where the words were typed.
            on_read: Gets the words and Claude's reading.
            retry: Asks again with the same words, after the login.
            text: What the user typed.
            reading: Claude's reading, or None when a login is needed.
        """
        if reading is not None:
            on_read(text, reading)
            return
        self._retry_after_login = retry
        message = f"{AiWordsReader.LOGIN_NEEDED} Your words are read as soon as you log in."
        self.words_answered.emit(target, False, message)
        self.claude_login_needed.emit()

    def _check_claude_login(self) -> None:
        """Check in the background whether the user finished logging in to Claude Code; give up after a while."""
        if self._checking_login:
            return
        if self._login_checks_left <= 0:
            self._login_timer.stop()
            self._retry_after_login = None
            self.problem.emit("The Claude Code login did not finish. Try again in Settings, AI for your own words.")
            return
        self._login_checks_left -= 1
        self._checking_login = True
        self._tasks.start(
            "Checking the Claude Code login",
            self._login_status_job,
            self._on_login_status,
            self._on_login_check_failed,
            quiet=True,
        )

    def _login_status_job(self, context: TaskContext) -> LoginStatus:
        """Ask Claude Code whether it is logged in. Runs on a worker thread.

        Args:
            context: Not used.

        Returns:
            The status.
        """
        return self._services.ai_reader.login.status()

    def _on_login_status(self, status: LoginStatus) -> None:
        """Once the user is logged in, say so and read the words that waited for the login.

        Args:
            status: Whether Claude Code is logged in now.
        """
        self._checking_login = False
        if not status.logged_in:
            return
        self._login_timer.stop()
        account = f" as {status.account}" if status.account else ""
        self.notice.emit(f"Claude Code is logged in{account}.")
        self.ai_changed.emit()
        retry = self._retry_after_login
        self._retry_after_login = None
        if retry is not None:
            retry()

    def _on_login_check_failed(self, _message: str) -> None:
        """Allow the next login check after one failed.

        Args:
            _message: The error message (not shown; the next check tries again).
        """
        self._checking_login = False

    def _on_claude_read_for_references(self, group_id: str | None, text: str, reading: AiReading) -> None:
        """Make the option Claude read from the words typed in the References step.

        Args:
            group_id: The group the option is for, or None for every group.
            text: What the user typed.
            reading: The steps and Claude's explanation.
        """
        self._add_words_option(text, reading.steps, reading.explanation, group_id)

    def _on_claude_read_for_group(self, group_id: str, base_id: str | None, text: str, reading: AiReading) -> None:
        """Make the group option Claude read from the words typed in the Refine step.

        Args:
            group_id: Id of the group.
            base_id: Id of the option the words are added to.
            text: What the user typed.
            reading: The steps and Claude's explanation.
        """
        self._add_typed_option(group_id, base_id, text, reading.steps, reading.explanation)

    def _on_words_failed(self, target: str, message: str) -> None:
        """Tell the page that the words could not be read.

        Args:
            target: Where the words were typed.
            message: Why.
        """
        self.words_answered.emit(target, False, message)

    def _add_words_option(
        self,
        text: str,
        steps: Sequence[RefinementStep],
        explanation: str,
        group_id: str | None,
    ) -> None:
        """Add an option made from words typed in the References step.

        Args:
            text: What the user typed.
            steps: The steps read from it.
            explanation: Claude's sentence about the steps; empty when the app's own phrases read them.
            group_id: The group the option is for, or None for every group.
        """
        cleaned = text.strip()
        pipeline_id = self._new_pipeline_id("words")
        details = f"Read by Claude: {explanation}" if explanation else ""
        pipeline = RefinementPipeline(pipeline_id, f"Your words: {cleaned}", PipelineSource.WORDS, steps, details)
        self._on_pipeline_built(group_id, pipeline)
        self.words_answered.emit(self.REFERENCES_TARGET, True, explanation)

    def _add_typed_option(
        self,
        group_id: str,
        base_id: str | None,
        text: str,
        steps: Sequence[RefinementStep],
        explanation: str,
    ) -> None:
        """Add a group option made from typed words on top of another option, pick it, and make its version.

        Args:
            group_id: Id of the group.
            base_id: Id of the option to start from; None starts from the unchanged photo.
            text: What the user typed.
            steps: The steps read from it.
            explanation: Claude's sentence about the steps; empty when the app's own phrases read them.
        """
        project = self._project
        if project is None or project.group(group_id) is None:
            return
        base = self._find_option(group_id, base_id) if base_id else None
        if base is None:
            base = RefinementPipeline.camera()
        cleaned = text.strip()
        pipeline_id = self._new_pipeline_id("typed")
        name = cleaned if base.is_camera else f"{base.name} + {cleaned}"
        pipeline = base.extended(pipeline_id, name, steps, PipelineSource.WORDS)
        project.add_group_pipeline(group_id, pipeline)
        self._reserved_ids.discard(pipeline_id)
        reader = "Claude" if explanation else "the app's phrases"
        details = {"group": group_id, "text": cleaned, "base": base.name, "read_by": reader}
        self._services.history_log.record("typed", details)
        self.choose(group_id, pipeline_id)
        self._render_one(group_id, pipeline)
        self.words_answered.emit(group_id, True, explanation)

    def _on_pipeline_failed(self, pipeline_id: str, message: str) -> None:
        """Free the id of an option that could not be built, and show why.

        Args:
            pipeline_id: The id that was set aside for it.
            message: The error message.
        """
        self._reserved_ids.discard(pipeline_id)
        self.problem.emit(message)

    def _new_pipeline_id(self, prefix: str) -> str:
        """A new option id that is not used and not waiting for a build.

        Args:
            prefix: Start of the id, such as "history".

        Returns:
            An id such as "history-2".
        """
        project = self._project
        number = 1
        while True:
            candidate = f"{prefix}-{number}"
            taken = project is not None and project.pipeline(candidate) is not None
            if not taken and candidate not in self._reserved_ids:
                self._reserved_ids.add(candidate)
                return candidate
            number += 1

    def _variant_base(self, shared: Sequence[RefinementPipeline]) -> RefinementPipeline:
        """The option the brighter and darker copies are made from.

        The newest reference wins, because a reference added for one group
        comes after the references shared by every group.

        Args:
            shared: The options a group uses, the unchanged photo first.

        Returns:
            The newest option from a reference, or the unchanged photo when there is none.
        """
        for option in reversed(shared):
            if not option.is_camera:
                return option
        return shared[0]

    def _find_option(self, group_id: str, pipeline_id: str) -> RefinementPipeline | None:
        """Find an option of a group, including the brighter and darker copies.

        Args:
            group_id: Id of the group.
            pipeline_id: Id of the option.

        Returns:
            The option, or None.
        """
        for option in self.options_for(group_id):
            if option.id == pipeline_id:
                return option
        return None

    # ------------------------------------------------------ private: versions

    def _made_on_sample(self, group_id: str, previews: Sequence[VersionPreview]) -> bool:
        """Tell whether versions were made on the photo that stands for the group now.

        Args:
            group_id: Id of the group.
            previews: The versions.

        Returns:
            True when every version shows the group's current sample photo.
        """
        sample = self.sample_photo(group_id)
        if sample is None:
            return False
        others = [preview for preview in previews if preview.sample_id != sample.id]
        return not others

    def _versions_job(
        self,
        group_id: str,
        sample: Photo,
        options: Sequence[RefinementPipeline],
        faces: Sequence[Face],
        sharpen: bool,
        context: TaskContext,
    ) -> tuple[str, list[VersionPreview]]:
        """Make every option's version of a sample photo, the way the export makes it. Runs on a worker thread.

        Args:
            group_id: Id of the group.
            sample: The sample photo.
            options: The options to apply.
            faces: The faces of the sample photo.
            sharpen: Sharpen a little after shrinking, as the export is set to.
            context: For progress.

        Returns:
            The group id and the versions.
        """
        developed: dict[str, np.ndarray] = {}
        previews: list[VersionPreview] = []
        total = len(options)
        for done, option in enumerate(options):
            context.report_item(done, total, option.name)
            pixels = self._developed_sample(sample, option, developed)
            preview = self._make_preview(pixels, option, faces, sharpen, sample.id)
            previews.append(preview)
        context.report(total, total)
        return group_id, previews

    def _developed_sample(
        self,
        sample: Photo,
        option: RefinementPipeline,
        developed: dict[str, np.ndarray],
    ) -> np.ndarray:
        """The sample photo developed for an option, the way the export develops it.

        darktable develops at full size and shrinks at the end, as for the
        export; its faster preview mode shrinks first and loses fine detail.
        Options with the same darktable edit (or none) share one development,
        so the sample is developed once per edit. The sample's own sidecar
        counts as no edit, since darktable reads it either way.

        Args:
            sample: The sample photo.
            option: The option.
            developed: Developments made so far for this sample, by edit file; filled in here.

        Returns:
            RGB values from 0 to 1.
        """
        edit = option.darktable_edit
        key = ""
        if edit is not None and not self._services.developer.is_own_sidecar(sample, edit):
            key = str(edit)
        pixels = developed.get(key)
        if pixels is None:
            pixels = self._services.developer.develop(sample, option, self.VERSION_SIDE, True)
            developed[key] = pixels
        return pixels

    def _make_preview(
        self,
        pixels: np.ndarray,
        option: RefinementPipeline,
        faces: Sequence[Face],
        sharpen: bool,
        sample_id: str,
    ) -> VersionPreview:
        """Apply one option to the sample photo's pixels.

        Args:
            pixels: The sample photo's pixels.
            option: The option.
            faces: The faces of the sample photo.
            sharpen: Sharpen a little after shrinking, as the export does.
            sample_id: Id of the sample photo.

        Returns:
            The version, ready to show.
        """
        refined = self._services.refiner.refine(pixels, option, faces)
        if sharpen:
            refined = self._sharpener.sharpen(refined)
        image = self._converter.to_qimage(refined)
        description = option.describe_steps()
        return VersionPreview(option.id, option.name, description, image, sample_id)

    def _on_versions_ready(self, result: tuple[str, list[VersionPreview]]) -> None:
        """Keep the versions of a group, unless something changed while they were being made.

        They are made again when the options changed, when a recalculation was
        asked for, or when another photo now stands for the group.

        Args:
            result: The group id and the versions.
        """
        group_id, previews = result
        self._rendering.discard(group_id)
        if group_id in self._outdated_renders:
            self._outdated_renders.discard(group_id)
            self.render_versions(group_id)
            return
        made_ids = [preview.pipeline_id for preview in previews]
        options = self.options_for(group_id)
        wanted_ids = [option.id for option in options]
        if made_ids != wanted_ids or not self._made_on_sample(group_id, previews):
            self.render_versions(group_id)
            return
        self._versions[group_id] = previews
        self.versions_changed.emit(group_id)

    def _on_versions_failed(self, group_id: str, message: str) -> None:
        """Show why the versions of a group could not be made.

        Args:
            group_id: Id of the group.
            message: The error message.
        """
        self._rendering.discard(group_id)
        self._outdated_renders.discard(group_id)
        self.problem.emit(message)

    def _render_one(self, group_id: str, option: RefinementPipeline) -> None:
        """Make the version of one new option and add it to the group's versions.

        Args:
            group_id: Id of the group.
            option: The new option.
        """
        project = self._project
        group = project.group(group_id)
        if group is None:
            return
        sample = project.sample_of(group)
        if sample is None:
            return
        faces = project.faces_of(sample.id)
        photo_option = self._option_for_photo(sample, option)
        options = [photo_option]
        sharpen = project.export.sharpen
        job = partial(self._versions_job, group_id, sample, options, faces, sharpen)
        self._tasks.start("Making your version", job, self._on_one_version_ready, self._on_task_failed)

    def _on_one_version_ready(self, result: tuple[str, list[VersionPreview]]) -> None:
        """Add a newly made version to the group's versions.

        Args:
            result: The group id and a list with the one new version.
        """
        group_id, previews = result
        existing = self._versions.get(group_id)
        if existing is None:
            self.render_versions(group_id)
            return
        combined = [*existing, *previews]
        if not self._made_on_sample(group_id, combined):
            self.render_versions(group_id)
            return
        existing.extend(previews)
        self.versions_changed.emit(group_id)

    # -------------------------------------------------------- private: export

    def _start_export(self, items: Sequence[tuple[Photo, RefinementPipeline]]) -> None:
        """Export photos in the background, with the settings of the Export step.

        Args:
            items: The photos, each with the option it is refined with.
        """
        project = self._project
        settings = project.export
        folder = self.export_folder
        folder_text = str(folder)
        run_settings = ExportSettings(
            folder_text,
            settings.long_side,
            settings.quality,
            settings.copy_metadata,
            settings.sharpen,
            settings.overwrite,
        )
        faces = {photo.id: project.faces_of(photo.id) for photo, _option in items}
        job = partial(self._export_job, items, faces, run_settings)
        self._tasks.start("Exporting photos", job, self._on_export_finished, self._on_task_failed)

    def _export_option_of(self, group_id: str) -> RefinementPipeline:
        """The option a group's photos are exported with: its pick, or the unchanged option.

        Args:
            group_id: Id of the group.

        Returns:
            The picked option; the unchanged option when the group has no pick, is skipped, or its pick was removed.
        """
        project = self._project
        choice = project.choice_of(group_id)
        if choice is not None and choice.pipeline_id is not None:
            option = project.pipeline(choice.pipeline_id)
            if option is not None:
                return option
        return RefinementPipeline.camera()

    def _export_job(
        self,
        items: Sequence[tuple[Photo, RefinementPipeline]],
        faces: dict[str, list[Face]],
        settings: ExportSettings,
        context: TaskContext,
    ) -> list[ExportResult]:
        """Export every photo of the plan. Runs on a worker thread.

        Args:
            items: The photos with their refinement.
            faces: The faces of the photos, by photo id.
            settings: Folder, size, quality and metadata options.
            context: For progress and stop requests.

        Returns:
            What happened to each photo.
        """
        results: list[ExportResult] = []
        total = len(items)
        for done, (photo, pipeline) in enumerate(items):
            if context.stop_requested:
                break
            context.report_item(done, total, photo.name)
            photo_faces = faces.get(photo.id, [])
            result = self._services.exporter.export(photo, pipeline, photo_faces, settings)
            results.append(result)
        finished = len(results)
        context.report(finished, total)
        return results

    def _on_export_finished(self, results: list[ExportResult]) -> None:
        """Log the export and hand the results to the export page.

        Args:
            results: What happened to each photo.
        """
        written = 0
        replaced = 0
        skipped = 0
        failed = 0
        for result in results:
            if result.status.is_written:
                written += 1
            elif result.status is ExportStatus.SKIPPED:
                skipped += 1
            else:
                failed += 1
            if result.status is ExportStatus.REPLACED:
                replaced += 1
        details = {"written": written, "replaced": replaced, "skipped": skipped, "failed": failed}
        self._services.history_log.record("export", details)
        written_text = f"{written} written ({replaced} over old files)" if replaced else f"{written} written"
        message = f"Export done: {written_text}, {skipped} skipped, {failed} failed."
        if skipped:
            message = f"{message} Skipped photos already have a file in the folder; the Export step can overwrite them."
        self.notice.emit(message)
        self.export_finished.emit(results)

    # ------------------------------------------------------- private: preview

    def _preview_job(self, photo: Photo, context: TaskContext) -> tuple[str, QImage]:
        """Load a large preview of a photo. Runs on a worker thread.

        Args:
            photo: The photo.
            context: Not used.

        Returns:
            The photo id and the picture.
        """
        pixels = self._services.reader.load_pixels(photo, self.PREVIEW_SIDE)
        image = self._converter.to_qimage(pixels)
        return photo.id, image

    def _deliver_preview(self, receiver: Callable[[str, QImage], None], result: tuple[str, QImage]) -> None:
        """Hand a loaded preview to the page that asked for it.

        Args:
            receiver: The page's function.
            result: The photo id and the picture.
        """
        photo_id, image = result
        receiver(photo_id, image)
