"""Projects on disk: a project folder with a manifest file."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from easy_photo import APP_VERSION
from easy_photo.model.group import PhotoGroup
from easy_photo.model.project import GroupChoice, Project, SavedName
from easy_photo.model.quality import Decision
from easy_photo.refinement.pipeline import RefinementPipeline
from easy_photo.refinement.steps import StepCatalog
from easy_photo.settings import CheckSettings, ExportSettings, GroupSettings, settings_from_dict


class ManifestError(Exception):
    """Raised when a manifest file cannot be read."""


class ProjectManifest:
    """Reads and writes a project's manifest file, ``easy-photo-project.json``.

    A project is a folder with this file in it. The manifest holds everything
    the user decided: the sources, the options of each step, the user's own
    keep and set-aside decisions, the names given to people, the groups, the
    refinement options with their steps, and the option picked for each group.
    Measurements and previews are not saved; they are made again from the
    photos when the project opens, which is quick because raw previews are
    cached.
    """

    FILE_NAME = "easy-photo-project.json"
    FORMAT = "easy-photo-project"
    VERSION = 1

    def __init__(self, catalog: StepCatalog) -> None:
        """Create a manifest reader and writer.

        Args:
            catalog: Turns saved refinement steps back into step objects.
        """
        self._catalog = catalog

    def path_in(self, folder: Path) -> Path:
        """The manifest file of a project folder.

        Args:
            folder: The project folder.

        Returns:
            The path of its manifest file.
        """
        return folder / self.FILE_NAME

    def create(self, name: str, folder: Path) -> Project:
        """Make a new, empty project and save its manifest.

        Args:
            name: Name of the project.
            folder: The project folder; it is created when it does not exist.

        Returns:
            The new project.

        Raises:
            ManifestError: When the folder already holds a project.
        """
        manifest = self.path_in(folder)
        if manifest.exists():
            raise ManifestError(f"{folder} already holds a project.")
        folder.mkdir(parents=True, exist_ok=True)
        project = Project(name, folder)
        self.save(project)
        return project

    def save(self, project: Project) -> Path:
        """Write a project's manifest.

        The file is written under a temporary name and then renamed, so a
        crash while saving never leaves a broken manifest.

        Args:
            project: The project.

        Returns:
            The manifest file.
        """
        data = self._to_data(project)
        text = json.dumps(data, indent=2, ensure_ascii=False)
        manifest = self.path_in(project.folder)
        unique = uuid.uuid4().hex
        temporary = manifest.with_name(f".{manifest.name}.{unique}.part")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, manifest)
        return manifest

    def load(self, path: Path) -> Project:
        """Open a project from its manifest file or its folder.

        Args:
            path: The manifest file, or the folder that holds it.

        Returns:
            The project, with everything the manifest holds.

        Raises:
            ManifestError: When there is no manifest or it cannot be read.
        """
        manifest = self.path_in(path) if path.is_dir() else path
        if not manifest.exists():
            raise ManifestError(f"No project manifest was found at {manifest}.")
        try:
            text = manifest.read_text(encoding="utf-8")
            data = json.loads(text)
        except (OSError, json.JSONDecodeError) as error:
            raise ManifestError(f"The manifest {manifest} cannot be read: {error}") from error
        if not isinstance(data, dict) or data.get("format") != self.FORMAT:
            raise ManifestError(f"{manifest} is not an easy-photo project manifest.")
        try:
            return self._from_data(data, manifest.parent)
        except (KeyError, TypeError, ValueError) as error:
            raise ManifestError(f"The manifest {manifest} is damaged: {error}") from error

    def _to_data(self, project: Project) -> dict:
        """Turn a project into the manifest's dictionary.

        Args:
            project: The project.

        Returns:
            The dictionary to write as JSON.
        """
        now = datetime.now()
        sources = [str(source) for source in project.sources]
        decisions = {photo_id: decision.name for photo_id, decision in project.user_decisions.items()}
        people = [{"name": saved.name, "faces": list(saved.face_ids)} for saved in project.saved_names()]
        groups = [self._group_to_data(group) for group in project.groups]
        pipelines = [pipeline.to_data() for pipeline in project.pipelines if not pipeline.is_camera]
        group_pipelines = {
            group_id: [pipeline.to_data() for pipeline in options]
            for group_id, options in project.all_group_pipelines.items()
        }
        choices = {group_id: choice.pipeline_id for group_id, choice in project.choices.items()}
        unused_options = project.unused_options
        return {
            "format": self.FORMAT,
            "version": self.VERSION,
            "app_version": APP_VERSION,
            "saved_at": now.isoformat(timespec="seconds"),
            "name": project.name,
            "sources": sources,
            "checks": asdict(project.checks),
            "grouping": asdict(project.grouping),
            "export": asdict(project.export),
            "decisions": decisions,
            "people": people,
            "groups": groups,
            "pipelines": pipelines,
            "group_pipelines": group_pipelines,
            "choices": choices,
            "unused_options": unused_options,
        }

    def _from_data(self, data: dict, folder: Path) -> Project:
        """Build a project from the manifest's dictionary.

        Args:
            data: The dictionary read from the manifest.
            folder: The project folder.

        Returns:
            The project.
        """
        name = data.get("name") or folder.name
        project = Project(name, folder)
        checks_data = data.get("checks", {})
        grouping_data = data.get("grouping", {})
        export_data = data.get("export", {})
        project.checks = settings_from_dict(CheckSettings, checks_data)
        project.grouping = settings_from_dict(GroupSettings, grouping_data)
        project.export = settings_from_dict(ExportSettings, export_data)
        for source_text in data.get("sources", []):
            source = Path(source_text)
            project.add_source(source)
        decisions = data.get("decisions", {})
        for photo_id, decision_name in decisions.items():
            decision = Decision[decision_name]
            project.decide(photo_id, decision)
        saved_names = [self._saved_name_from(item) for item in data.get("people", [])]
        project.set_saved_names(saved_names)
        for pipeline_data in data.get("pipelines", []):
            pipeline = RefinementPipeline.from_data(pipeline_data, self._catalog)
            project.add_pipeline(pipeline)
        groups = [self._group_from_data(item) for item in data.get("groups", [])]
        group_pipelines: dict[str, list[RefinementPipeline]] = {}
        saved_group_pipelines = data.get("group_pipelines", {})
        for group_id, options in saved_group_pipelines.items():
            group_pipelines[group_id] = [RefinementPipeline.from_data(item, self._catalog) for item in options]
        saved_choices = data.get("choices", {})
        choices = {group_id: GroupChoice(pipeline_id) for group_id, pipeline_id in saved_choices.items()}
        saved_unused = data.get("unused_options", {})
        unused_options = {group_id: set(option_ids) for group_id, option_ids in saved_unused.items()}
        project.restore_groups(groups, choices, group_pipelines, unused_options)
        return project

    def _group_to_data(self, group: PhotoGroup) -> dict:
        """Turn a group into a dictionary.

        Args:
            group: The group.

        Returns:
            Its id, title, details, photos and sample photo.
        """
        return {
            "id": group.id,
            "title": group.title,
            "details": group.details,
            "photos": list(group.photo_ids),
            "sample": group.sample_id,
            "people": list(group.person_ids),
        }

    def _group_from_data(self, data: dict) -> PhotoGroup:
        """Read a group saved by :meth:`_group_to_data`.

        Args:
            data: The saved dictionary.

        Returns:
            The group.
        """
        details = data.get("details", "")
        person_ids = data.get("people", [])
        return PhotoGroup(data["id"], data["title"], data["photos"], data["sample"], details, person_ids)

    def _saved_name_from(self, data: dict) -> SavedName:
        """Read a person's saved name and face ids.

        Args:
            data: The saved dictionary.

        Returns:
            The saved name.
        """
        faces = data.get("faces", [])
        face_ids = tuple(faces)
        return SavedName(data["name"], face_ids)
