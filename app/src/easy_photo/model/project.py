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
        self._chosen_samples: dict[str, str] = {}
        """Ids of the photos the user chose to stand for groups (their previews), by group id."""
        self._edited_at: dict[str, float] = {}
        """When the user last edited a photo in darktable (its sidecar's file time), for the photos they edited."""
        self._photo_edits: dict[str, Path] = {}
        """darktable edits (XMP files) applied to single photos, by photo id."""
        self._applied_at: dict[str, float] = {}
        """The file time of the sidecars the app wrote ("Apply sidecar"), by photo id."""

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
        self._edited_at = self._keep_known(self._edited_at)

    def set_edited_at(self, photo_id: str, edited_at: float | None) -> None:
        """Store when the user last edited a photo in darktable.

        Args:
            photo_id: Id of the photo.
            edited_at: The time its sidecar was last written, when it holds the
                user's own edit; None when the user has not edited the photo.
        """
        if edited_at is None:
            self._edited_at.pop(photo_id, None)
            return
        self._edited_at[photo_id] = edited_at

    def edited_at(self, photo_id: str) -> float | None:
        """When the user last edited a photo in darktable.

        Args:
            photo_id: Id of the photo.

        Returns:
            The time its sidecar was last written, or None when the user has not edited the photo.
        """
        return self._edited_at.get(photo_id)

    def set_applied_at(self, photo_id: str, applied_at: float | None) -> None:
        """Store the file time of a sidecar the app wrote, so its edit is not taken for one the user made.

        Args:
            photo_id: Id of the photo.
            applied_at: The time the app wrote its sidecar, or None to forget it.
        """
        if applied_at is None:
            self._applied_at.pop(photo_id, None)
            return
        self._applied_at[photo_id] = applied_at

    @property
    def applied_times(self) -> dict[str, float]:
        """The file times of the sidecars the app wrote, by photo id, for the manifest."""
        return dict(self._applied_at)

    def edited_by_user(self, photo_id: str) -> bool:
        """Tell whether the user edited a photo in darktable themselves.

        A sidecar the app wrote counts once darktable wrote it again, for
        example after the user changed the edit there.

        Args:
            photo_id: Id of the photo.

        Returns:
            True when the photo's sidecar holds an edit the app did not write as it is now.
        """
        edited_at = self._edited_at.get(photo_id)
        if edited_at is None:
            return False
        applied_at = self._applied_at.get(photo_id)
        return edited_at != applied_at

    def set_photo_edit(self, photo_id: str, edit_file: Path | None) -> None:
        """Apply a darktable edit to one photo, or take it away again.

        The photo is then developed with that edit, whatever its group picks;
        the pick's other steps still apply.

        Args:
            photo_id: Id of the photo.
            edit_file: XMP file of the edit, or None to develop the photo as its group's pick says.
        """
        if edit_file is None:
            self._photo_edits.pop(photo_id, None)
            return
        self._photo_edits[photo_id] = edit_file

    def photo_edit_of(self, photo_id: str) -> Path | None:
        """The darktable edit applied to one photo.

        Args:
            photo_id: Id of the photo.

        Returns:
            The edit's XMP file, or None when no edit was applied to the photo alone.
        """
        return self._photo_edits.get(photo_id)

    @property
    def photo_edits(self) -> dict[str, Path]:
        """The darktable edits applied to single photos, by photo id, for the manifest."""
        return dict(self._photo_edits)

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
        self._chosen_samples.clear()

    def restore_groups(
        self,
        groups: Sequence[PhotoGroup],
        choices: dict[str, GroupChoice],
        group_pipelines: dict[str, list[RefinementPipeline]],
        unused_options: dict[str, set[str]],
        chosen_samples: dict[str, str],
    ) -> None:
        """Put back groups, choices, typed options, turned-off options and chosen previews read from the manifest.

        Args:
            groups: The saved groups.
            choices: The saved choices, by group id.
            group_pipelines: The saved typed options, by group id.
            unused_options: Ids of the shared options turned off for each group.
            chosen_samples: Ids of the photos the user chose to stand for groups, by group id.
        """
        self._groups = list(groups)
        self._choices = dict(choices)
        self._group_pipelines = dict(group_pipelines)
        self._unused_options = {group_id: set(option_ids) for group_id, option_ids in unused_options.items()}
        self._chosen_samples = dict(chosen_samples)

    def selected_photos_of(self, group: PhotoGroup) -> list[Photo]:
        """The photos of a group that are selected (kept), so they are exported.

        Args:
            group: The group.

        Returns:
            The photos, in the group's order.
        """
        selected: list[Photo] = []
        for photo_id in group.photo_ids:
            photo = self._photos.get(photo_id)
            decision = self.decision_of(photo_id)
            if photo is not None and decision is not None and decision.is_kept:
                selected.append(photo)
        return selected

    def sample_of(self, group: PhotoGroup) -> Photo | None:
        """The photo that stands for a group (its preview).

        Among the group's selected photos, that is the photo the user chose;
        otherwise the photo the user edited in darktable most recently, since
        its sidecar holds an edit to apply to the group; otherwise the
        sharpest photo. When none of its photos is selected, the photo picked
        when the group was made stands for it.

        Args:
            group: The group.

        Returns:
            The photo, or None when none of the group's photos is in the project.
        """
        selected = self.selected_photos_of(group)
        chosen_id = self._chosen_samples.get(group.id)
        for photo in selected:
            if photo.id == chosen_id:
                return photo
        edited = self.latest_edited_of(selected)
        if edited is not None:
            return edited
        if selected:
            return self.sharpest_of(selected)
        stored = self._photos.get(group.sample_id)
        if stored is not None:
            return stored
        for photo_id in group.photo_ids:
            photo = self._photos.get(photo_id)
            if photo is not None:
                return photo
        return None

    def latest_edited_of(self, photos: Sequence[Photo]) -> Photo | None:
        """The photo the user edited in darktable most recently; sidecars the app wrote do not count.

        Args:
            photos: The photos to look at.

        Returns:
            That photo, or None when the user edited none of them.
        """
        latest: Photo | None = None
        latest_time = 0.0
        for photo in photos:
            if not self.edited_by_user(photo.id):
                continue
            edited_at = self._edited_at[photo.id]
            if latest is None or edited_at > latest_time:
                latest = photo
                latest_time = edited_at
        return latest

    def sharpest_of(self, photos: Sequence[Photo]) -> Photo:
        """The sharpest of some photos, by the sharpness the Filter step measured.

        Args:
            photos: The photos; at least one.

        Returns:
            The sharpest photo; the first when none was measured.
        """
        best = photos[0]
        best_sharpness = -1.0
        for photo in photos:
            result = self._quality.get(photo.id)
            if result is None:
                continue
            sharpness = result.scores.sharpness
            if sharpness > best_sharpness:
                best = photo
                best_sharpness = sharpness
        return best

    def remove_group(self, group_id: str) -> None:
        """Remove one group, with its pick, its own typed options and its turned-off options.

        Its photos stay in the project, but no group holds them, so they are
        not exported until the groups are made again.

        Args:
            group_id: Id of the group.
        """
        self._groups = [group for group in self._groups if group.id != group_id]
        self._choices.pop(group_id, None)
        self._group_pipelines.pop(group_id, None)
        self._unused_options.pop(group_id, None)
        self._chosen_samples.pop(group_id, None)

    def merge_groups(self, merged: PhotoGroup, other_ids: Sequence[str]) -> None:
        """Put a merged group in the place of the first group it was made from, and drop the other groups.

        The merged group has the first group's id, so that group's pick and
        chosen preview stay; when it has none, the first of the other groups
        that has one gives its own. A shared option stays on when any of the
        groups used it, and the typed options of all the groups go to the
        merged group.

        Args:
            merged: The merged group, with the id of the first group.
            other_ids: Ids of the other groups, in the order of the group list.
        """
        merged_id = merged.id
        group_ids = [merged_id, *other_ids]
        for other_id in other_ids:
            if merged_id not in self._choices and other_id in self._choices:
                self._choices[merged_id] = self._choices[other_id]
            if merged_id not in self._chosen_samples and other_id in self._chosen_samples:
                self._chosen_samples[merged_id] = self._chosen_samples[other_id]
        typed: list[RefinementPipeline] = []
        for group_id in group_ids:
            own = self._group_pipelines.get(group_id, [])
            typed.extend(own)
        none_unused: set[str] = set()
        unused_sets = [self._unused_options.get(group_id, none_unused) for group_id in group_ids]
        unused_everywhere = set.intersection(*unused_sets)
        for other_id in other_ids:
            self.remove_group(other_id)
        self._group_pipelines.pop(merged_id, None)
        self._unused_options.pop(merged_id, None)
        if typed:
            self._group_pipelines[merged_id] = typed
        if unused_everywhere:
            self._unused_options[merged_id] = unused_everywhere
        self._groups = [merged if group.id == merged_id else group for group in self._groups]

    def chosen_sample_of(self, group_id: str) -> str | None:
        """The photo the user chose to stand for a group (its preview), when they chose one.

        Args:
            group_id: Id of the group.

        Returns:
            Id of the photo, or None when the sharpest selected photo stands for the group.
        """
        return self._chosen_samples.get(group_id)

    def choose_sample(self, group_id: str, photo_id: str | None) -> None:
        """Let a photo stand for its group (the group's preview), or go back to the sharpest selected photo.

        Args:
            group_id: Id of the group.
            photo_id: Id of a photo of the group, or None for the sharpest selected photo.
        """
        if photo_id is None:
            self._chosen_samples.pop(group_id, None)
            return
        self._chosen_samples[group_id] = photo_id

    @property
    def chosen_samples(self) -> dict[str, str]:
        """The photos the user chose to stand for groups, by group id, for the manifest."""
        return dict(self._chosen_samples)

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
