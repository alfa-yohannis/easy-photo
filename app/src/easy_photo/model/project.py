"""Everything the user does in one project.

A project lives in a folder with a manifest file (see
:class:`easy_photo.services.manifest.ProjectManifest`). Only one project is
open at a time.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from easy_photo.model.face import Face, Person
from easy_photo.model.group import PhotoGroup
from easy_photo.model.photo import Photo
from easy_photo.model.quality import Decision, QualityResult
from easy_photo.model.summary import VisualSummary
from easy_photo.refinement.pipeline import RefinementPipeline
from easy_photo.settings import CheckSettings, ExportSettings, GroupSettings


@dataclass(frozen=True)
class GroupChoice:
    """The refinement the user picked for a group.

    ``pipeline_id`` is None when the user chose to skip the group; its photos
    are then not exported.
    """

    pipeline_id: str | None


@dataclass(frozen=True)
class SavedName:
    """A name the user gave a person, with the ids of that person's faces.

    Faces are found again each time a project is opened. The face ids let the
    app give the name back to the person who has those faces.
    """

    name: str
    face_ids: tuple[str, ...]


class Project:
    """The sources, photos, results, groups, options and choices of one project.

    The project only stores data. The services fill it in, the window shows
    it, and the manifest saves it, so there is one place that holds the truth.
    """

    EXPORT_FOLDER_NAME = "export"

    def __init__(self, name: str, folder: Path) -> None:
        """Start an empty project whose only refinement option is the unchanged photo.

        Args:
            name: Name of the project, shown in the window title.
            folder: Folder that holds the project's manifest file.
        """
        self._name = name
        self._folder = folder
        self._checks = CheckSettings()
        self._grouping = GroupSettings()
        self._export = ExportSettings()
        self._sources: list[Path] = []
        self._photos: dict[str, Photo] = {}
        self._quality: dict[str, QualityResult] = {}
        self._summaries: dict[str, VisualSummary] = {}
        self._user_decisions: dict[str, Decision] = {}
        self._faces: dict[str, list[Face]] = {}
        self._people: list[Person] = []
        self._saved_names: list[SavedName] = []
        self._groups: list[PhotoGroup] = []
        camera = RefinementPipeline.camera()
        self._pipelines: list[RefinementPipeline] = [camera]
        self._group_pipelines: dict[str, list[RefinementPipeline]] = {}
        self._choices: dict[str, GroupChoice] = {}
        self._unused_options: dict[str, set[str]] = {}

    # ----------------------------------------------------------------- basics

    @property
    def name(self) -> str:
        """Name of the project."""
        return self._name

    @property
    def folder(self) -> Path:
        """Folder that holds the project's manifest file."""
        return self._folder

    @property
    def default_export_folder(self) -> Path:
        """Where finished photos go when the user has not chosen a folder."""
        return self._folder / self.EXPORT_FOLDER_NAME

    @property
    def checks(self) -> CheckSettings:
        """Limits of the quality checks."""
        return self._checks

    @checks.setter
    def checks(self, checks: CheckSettings) -> None:
        """Replace the limits of the quality checks.

        Args:
            checks: The new limits.
        """
        self._checks = checks

    @property
    def grouping(self) -> GroupSettings:
        """Options of the grouping step."""
        return self._grouping

    @grouping.setter
    def grouping(self, grouping: GroupSettings) -> None:
        """Replace the options of the grouping step.

        Args:
            grouping: The new options.
        """
        self._grouping = grouping

    @property
    def export(self) -> ExportSettings:
        """Options of the export step."""
        return self._export

    @export.setter
    def export(self, export: ExportSettings) -> None:
        """Replace the options of the export step.

        Args:
            export: The new options.
        """
        self._export = export

    # ---------------------------------------------------------------- sources

    @property
    def sources(self) -> tuple[Path, ...]:
        """The folders and files the user added."""
        return tuple(self._sources)

    def add_source(self, path: Path) -> bool:
        """Add a folder or file to the sources.

        Args:
            path: The folder or file.

        Returns:
            False when it was already there.
        """
        if path in self._sources:
            return False
        self._sources.append(path)
        return True

    def remove_source(self, path: Path) -> None:
        """Remove a folder or file from the sources.

        Args:
            path: The folder or file.
        """
        if path in self._sources:
            self._sources.remove(path)

    # ----------------------------------------------------------------- photos

    def set_photos(self, photos: Sequence[Photo]) -> None:
        """Replace the photo list after the sources were searched.

        Results of photos that are still in the list are kept, so adding a
        source does not mean measuring every photo again. Groups are not
        touched; the caller clears them when the sources changed.

        Args:
            photos: The photos found in the sources.
        """
        new_photos: dict[str, Photo] = {}
        for photo in photos:
            old = self._photos.get(photo.id)
            if old is not None:
                photo.info = old.info
            new_photos[photo.id] = photo
        self._photos = new_photos
        self._quality = self._keep_known(self._quality)
        self._summaries = self._keep_known(self._summaries)
        self._faces = self._keep_known(self._faces)

    @property
    def photos(self) -> list[Photo]:
        """All photos, sorted by the time they were taken."""
        values = self._photos.values()
        return sorted(values, key=Photo.sort_key)

    @property
    def photo_count(self) -> int:
        """Number of photos found in the sources."""
        return len(self._photos)

    def photo(self, photo_id: str) -> Photo | None:
        """Find a photo by its id.

        Args:
            photo_id: Id of the photo.

        Returns:
            The photo, or None when it is not in the project.
        """
        return self._photos.get(photo_id)

    # ---------------------------------------------------------------- quality

    def set_analysis(self, photo_id: str, result: QualityResult, summary: VisualSummary) -> None:
        """Store the measurements of a photo.

        Args:
            photo_id: Id of the photo.
            result: Results of the quality checks.
            summary: Colors and layout, for grouping.
        """
        self._quality[photo_id] = result
        self._summaries[photo_id] = summary

    def set_quality(self, photo_id: str, result: QualityResult) -> None:
        """Replace the check results of a photo, after the user changed the limits.

        Args:
            photo_id: Id of the photo.
            result: The new results.
        """
        self._quality[photo_id] = result

    def quality_of(self, photo_id: str) -> QualityResult | None:
        """The check results of a photo.

        Args:
            photo_id: Id of the photo.

        Returns:
            The results, or None when the photo has not been measured yet.
        """
        return self._quality.get(photo_id)

    def summary_of(self, photo_id: str) -> VisualSummary | None:
        """The colors and layout of a photo.

        Args:
            photo_id: Id of the photo.

        Returns:
            The summary, or None when the photo has not been measured yet.
        """
        return self._summaries.get(photo_id)

    def is_analyzed(self, photo_id: str) -> bool:
        """Tell whether a photo has been measured.

        Args:
            photo_id: Id of the photo.

        Returns:
            True when its check results are known.
        """
        return photo_id in self._quality

    @property
    def analyzed_count(self) -> int:
        """Number of photos that have been measured."""
        return len(self._quality)

    # -------------------------------------------------------------- decisions

    def decide(self, photo_id: str, decision: Decision | None) -> None:
        """Store the user's own decision for a photo.

        Args:
            photo_id: Id of the photo.
            decision: The user's decision, or None to go back to the app's decision.
        """
        if decision is None:
            self._user_decisions.pop(photo_id, None)
        else:
            self._user_decisions[photo_id] = decision

    def user_decision_of(self, photo_id: str) -> Decision | None:
        """The decision the user made for a photo.

        Args:
            photo_id: Id of the photo.

        Returns:
            The user's decision, or None when the user has not decided.
        """
        return self._user_decisions.get(photo_id)

    @property
    def user_decisions(self) -> dict[str, Decision]:
        """All decisions the user made, by photo id."""
        return dict(self._user_decisions)

    def decision_of(self, photo_id: str) -> Decision | None:
        """The decision that counts for a photo: the user's, otherwise the app's.

        Args:
            photo_id: Id of the photo.

        Returns:
            The decision, or None when the photo has not been measured and the user has not decided.
        """
        decision = self._user_decisions.get(photo_id)
        if decision is not None:
            return decision
        result = self._quality.get(photo_id)
        if result is None:
            return None
        return result.decision

    def kept_photos(self) -> list[Photo]:
        """The measured photos that go on to the next steps, sorted by time.

        Returns:
            The kept photos, including the unsure ones the user has not set aside.
        """
        kept: list[Photo] = []
        for photo in self.photos:
            decision = self.decision_of(photo.id)
            if decision is not None and decision.is_kept:
                kept.append(photo)
        return kept

    def count_by_decision(self) -> dict[Decision, int]:
        """Count the measured photos per decision.

        Returns:
            The number of photos for every decision.
        """
        counts = {decision: 0 for decision in Decision}
        for photo_id in self._photos:
            decision = self.decision_of(photo_id)
            if decision is not None:
                counts[decision] += 1
        return counts

    # ------------------------------------------------------- faces and people

    def set_faces(self, faces_by_photo: dict[str, list[Face]]) -> None:
        """Store the faces found in some photos; other photos keep what they had.

        Args:
            faces_by_photo: Faces by photo id. An empty list means "searched, none found".
        """
        self._faces.update(faces_by_photo)

    def faces_of(self, photo_id: str) -> list[Face]:
        """The faces found in a photo.

        Args:
            photo_id: Id of the photo.

        Returns:
            The faces; an empty list when none were found or none were searched for.
        """
        return self._faces.get(photo_id, [])

    def faces_searched(self, photo_id: str) -> bool:
        """Tell whether the app has looked for faces in a photo.

        Args:
            photo_id: Id of the photo.

        Returns:
            True when faces were searched for, even if none were found.
        """
        return photo_id in self._faces

    def all_faces(self) -> list[Face]:
        """Every face found in the project's photos.

        Returns:
            The faces, photo by photo.
        """
        faces: list[Face] = []
        for photo_faces in self._faces.values():
            faces.extend(photo_faces)
        return faces

    def set_saved_names(self, names: Sequence[SavedName]) -> None:
        """Remember names read from the manifest, to give back once faces are found.

        Args:
            names: The saved names.
        """
        self._saved_names = list(names)

    def saved_names(self) -> list[SavedName]:
        """The names to write into the manifest.

        Returns:
            The current people's names with their face ids, or the names read
            from the manifest when no faces have been found in this session.
        """
        if not self._people:
            return list(self._saved_names)
        names: list[SavedName] = []
        for person in self._people:
            face_ids = [face.face_id for face in person.faces]
            face_tuple = tuple(face_ids)
            saved = SavedName(person.name, face_tuple)
            names.append(saved)
        return names

    def set_people(self, people: Sequence[Person]) -> None:
        """Store the people the faces were sorted into, and give back the names they had.

        Each earlier name (from this session, or from the manifest) goes to the
        person who has the most of the faces that carried the name before.

        Args:
            people: The people, most faces first.
        """
        previous = self.saved_names()
        self._people = list(people)
        for saved in previous:
            person = self._best_owner(saved.face_ids)
            if person is not None:
                person.name = saved.name

    @property
    def people(self) -> list[Person]:
        """The people found in the photos, most faces first."""
        return list(self._people)

    def person(self, person_id: str) -> Person | None:
        """Find a person by id.

        Args:
            person_id: Id of the person.

        Returns:
            The person, or None.
        """
        for person in self._people:
            if person.id == person_id:
                return person
        return None

    def people_in(self, photo_id: str) -> list[Person]:
        """The people who appear in a photo.

        Args:
            photo_id: Id of the photo.

        Returns:
            The people, in the order of :attr:`people`.
        """
        return [person for person in self._people if photo_id in person.photo_ids]

    def merge_people(self, keep_id: str, other_id: str) -> None:
        """Treat two people as one: the second person's faces move to the first.

        Args:
            keep_id: Id of the person who stays.
            other_id: Id of the person whose faces move.
        """
        keep = self.person(keep_id)
        other = self.person(other_id)
        if keep is None or other is None or keep is other:
            return
        keep.take_faces_from(other)
        self._people.remove(other)

    # ----------------------------------------------------------------- groups

    def set_groups(self, groups: Sequence[PhotoGroup]) -> None:
        """Replace the groups. Choices and typed options of the old groups are cleared.

        Args:
            groups: The new groups.
        """
        self._groups = list(groups)
        self._choices.clear()
        self._group_pipelines.clear()
        self._unused_options.clear()

    def restore_groups(
        self,
        groups: Sequence[PhotoGroup],
        choices: dict[str, GroupChoice],
        group_pipelines: dict[str, list[RefinementPipeline]],
        unused_options: dict[str, set[str]],
    ) -> None:
        """Put back groups, choices, typed options and turned-off options read from the manifest.

        Args:
            groups: The saved groups.
            choices: The saved choices, by group id.
            group_pipelines: The saved typed options, by group id.
            unused_options: Ids of the shared options turned off for each group.
        """
        self._groups = list(groups)
        self._choices = dict(choices)
        self._group_pipelines = dict(group_pipelines)
        self._unused_options = {group_id: set(option_ids) for group_id, option_ids in unused_options.items()}

    def replace_groups(self, groups: Sequence[PhotoGroup]) -> None:
        """Replace the group objects but keep the choices, for groups that only got a new title.

        Args:
            groups: The groups, with the same ids as before.
        """
        self._groups = list(groups)

    def clear_groups(self) -> None:
        """Remove all groups, with their choices and typed options."""
        self.set_groups([])

    @property
    def groups(self) -> list[PhotoGroup]:
        """The groups, in the order they were made."""
        return list(self._groups)

    def group(self, group_id: str) -> PhotoGroup | None:
        """Find a group by id.

        Args:
            group_id: Id of the group.

        Returns:
            The group, or None.
        """
        for group in self._groups:
            if group.id == group_id:
                return group
        return None

    # -------------------------------------------------------------- pipelines

    @property
    def pipelines(self) -> list[RefinementPipeline]:
        """The refinement options shared by all groups, the unchanged photo first."""
        return list(self._pipelines)

    def add_pipeline(self, pipeline: RefinementPipeline) -> None:
        """Add a refinement option for all groups.

        Args:
            pipeline: The new option.
        """
        self._pipelines.append(pipeline)

    def remove_pipeline(self, pipeline_id: str) -> None:
        """Remove a shared refinement option. The camera option cannot be removed.

        Choices that used the option are cleared.

        Args:
            pipeline_id: Id of the option.
        """
        if pipeline_id == RefinementPipeline.CAMERA_ID:
            return
        self._pipelines = [pipeline for pipeline in self._pipelines if pipeline.id != pipeline_id]
        chosen = {group_id: choice for group_id, choice in self._choices.items() if choice.pipeline_id != pipeline_id}
        self._choices = chosen
        for option_ids in self._unused_options.values():
            option_ids.discard(pipeline_id)

    def option_used_in(self, group_id: str, pipeline_id: str) -> bool:
        """Tell whether a shared option is shown for a group. The camera option always is.

        Args:
            group_id: Id of the group.
            pipeline_id: Id of the option.

        Returns:
            False only when the user turned the option off for this group.
        """
        if pipeline_id == RefinementPipeline.CAMERA_ID:
            return True
        unused = self._unused_options.get(group_id)
        if unused is None:
            return True
        return pipeline_id not in unused

    def set_option_used(self, group_id: str, pipeline_id: str, used: bool) -> None:
        """Turn a shared option on or off for a group.

        Turning off the option a group has picked removes that pick, so the
        group is not exported with an option the user no longer wants for it.

        Args:
            group_id: Id of the group.
            pipeline_id: Id of the option.
            used: True to show the option for the group.
        """
        if pipeline_id == RefinementPipeline.CAMERA_ID:
            return
        unused = self._unused_options.get(group_id)
        if unused is None:
            unused = set()
            self._unused_options[group_id] = unused
        if used:
            unused.discard(pipeline_id)
            return
        unused.add(pipeline_id)
        choice = self._choices.get(group_id)
        if choice is not None and choice.pipeline_id == pipeline_id:
            del self._choices[group_id]

    @property
    def unused_options(self) -> dict[str, list[str]]:
        """Ids of the shared options turned off, by group id, for the manifest."""
        return {group_id: sorted(option_ids) for group_id, option_ids in self._unused_options.items() if option_ids}

    def add_group_pipeline(self, group_id: str, pipeline: RefinementPipeline) -> None:
        """Add a refinement option that only one group has, such as a change the user typed.

        Args:
            group_id: Id of the group.
            pipeline: The new option.
        """
        options = self._group_pipelines.setdefault(group_id, [])
        options.append(pipeline)

    def group_pipelines(self, group_id: str) -> list[RefinementPipeline]:
        """The options only this group has.

        Args:
            group_id: Id of the group.

        Returns:
            The group's own options, oldest first.
        """
        options = self._group_pipelines.get(group_id, [])
        return list(options)

    @property
    def all_group_pipelines(self) -> dict[str, list[RefinementPipeline]]:
        """Every group's own options, by group id."""
        return {group_id: list(options) for group_id, options in self._group_pipelines.items()}

    def pipeline(self, pipeline_id: str) -> RefinementPipeline | None:
        """Find a refinement option by id, shared or belonging to a group.

        Args:
            pipeline_id: Id of the option.

        Returns:
            The option, or None.
        """
        for pipeline in self._pipelines:
            if pipeline.id == pipeline_id:
                return pipeline
        for options in self._group_pipelines.values():
            for pipeline in options:
                if pipeline.id == pipeline_id:
                    return pipeline
        return None

    # ---------------------------------------------------------------- choices

    def choose(self, group_id: str, pipeline_id: str | None) -> None:
        """Store the option the user picked for a group.

        Args:
            group_id: Id of the group.
            pipeline_id: Id of the option, or None to skip the group.
        """
        self._choices[group_id] = GroupChoice(pipeline_id)

    def choice_of(self, group_id: str) -> GroupChoice | None:
        """The option the user picked for a group.

        Args:
            group_id: Id of the group.

        Returns:
            The choice, or None when the user has not picked yet.
        """
        return self._choices.get(group_id)

    @property
    def choices(self) -> dict[str, GroupChoice]:
        """All choices, by group id."""
        return dict(self._choices)

    @property
    def chosen_count(self) -> int:
        """Number of groups the user has picked an option for (or skipped)."""
        return len(self._choices)

    # ---------------------------------------------------------------- helpers

    def _keep_known(self, values: dict) -> dict:
        """Keep only the entries whose key is the id of a photo in the project.

        Args:
            values: A dictionary keyed by photo id.

        Returns:
            A new dictionary without entries for photos that are gone.
        """
        return {key: value for key, value in values.items() if key in self._photos}

    def _best_owner(self, face_ids: Sequence[str]) -> Person | None:
        """Find the person who has the most of the given faces.

        Args:
            face_ids: Ids of faces.

        Returns:
            That person, or None when nobody has any of them.
        """
        wanted = set(face_ids)
        best: Person | None = None
        best_count = 0
        for person in self._people:
            own_ids = {face.face_id for face in person.faces}
            shared = own_ids & wanted
            count = len(shared)
            if count > best_count:
                best = person
                best_count = count
        return best
