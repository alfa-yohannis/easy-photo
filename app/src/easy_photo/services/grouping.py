"""Splitting photos into groups that get the same refinement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from easy_photo.model.group import PhotoGroup
from easy_photo.model.photo import Photo
from easy_photo.model.project import Project


class Grouper(ABC):
    """Splits photos into groups.

    Subclasses decide which photos belong together. This base class picks
    each group's sample photo and writes its time range.
    """

    TIME_FORMAT = "%d %b %Y, %H:%M"

    @abstractmethod
    def make_groups(self, photos: Sequence[Photo], project: Project) -> list[PhotoGroup]:
        """Split photos into groups.

        Args:
            photos: The photos to group, usually the kept photos.
            project: Gives the measurements and the people of the photos.

        Returns:
            The groups.
        """

    def _sample_of(self, photos: Sequence[Photo], project: Project) -> str:
        """Pick the sharpest photo of a group to stand for it.

        Args:
            photos: The photos of the group.
            project: Gives the sharpness of each photo.

        Returns:
            Id of the sharpest photo (the first photo when none was measured).
        """
        sharpest = project.sharpest_of(photos)
        return sharpest.id

    def _time_range(self, photos: Sequence[Photo]) -> str:
        """Describe when the photos of a group were taken.

        Args:
            photos: The photos, in time order.

        Returns:
            Text such as "14 Dec 2024, 10:32 to 10:41", or an empty text when the times are unknown.
        """
        first = photos[0].info.taken_at
        last = photos[-1].info.taken_at
        if first is None or last is None:
            return ""
        start = first.strftime(self.TIME_FORMAT)
        if first.date() == last.date():
            end = last.strftime("%H:%M")
        else:
            end = last.strftime(self.TIME_FORMAT)
        if start.endswith(end):
            return start
        return f"{start} to {end}"


class SimilarityGrouper(Grouper):
    """Puts neighbouring photos together when they were taken close in time and look alike.

    Photos are taken in time order. A photo starts a new group when the pause
    since the photo before is longer than the limit, or when the two photos
    look too different.
    """

    def __init__(self, max_gap_minutes: float, min_similarity: float) -> None:
        """Create a grouper.

        Args:
            max_gap_minutes: Longest pause between two photos of one group.
            min_similarity: How alike two neighbouring photos must look (0 to 1).
        """
        self._max_gap_minutes = max_gap_minutes
        self._min_similarity = min_similarity

    def make_groups(self, photos: Sequence[Photo], project: Project) -> list[PhotoGroup]:
        """Split photos into runs of similar photos.

        Args:
            photos: The photos to group.
            project: Gives the visual summaries of the photos.

        Returns:
            The groups, in time order.
        """
        ordered = sorted(photos, key=Photo.sort_key)
        runs: list[list[Photo]] = []
        previous: Photo | None = None
        for photo in ordered:
            if previous is None or self._starts_new_group(previous, photo, project):
                runs.append([photo])
            else:
                runs[-1].append(photo)
            previous = photo
        groups: list[PhotoGroup] = []
        for number, run in enumerate(runs, start=1):
            group = self._make_group(number, run, project)
            groups.append(group)
        return groups

    def _starts_new_group(self, previous: Photo, photo: Photo, project: Project) -> bool:
        """Tell whether a photo is too far from the photo before it to share its group.

        Args:
            previous: The photo before.
            photo: The photo to place.
            project: Gives the visual summaries.

        Returns:
            True when the pause is too long or the photos look too different.
        """
        before = previous.info.taken_at
        after = photo.info.taken_at
        if before is not None and after is not None:
            pause = after - before
            minutes = pause.total_seconds() / 60.0
            if minutes > self._max_gap_minutes:
                return True
        before_summary = project.summary_of(previous.id)
        after_summary = project.summary_of(photo.id)
        if before_summary is None or after_summary is None:
            return False
        similarity = before_summary.similarity_to(after_summary)
        return similarity < self._min_similarity

    def _make_group(self, number: int, photos: Sequence[Photo], project: Project) -> PhotoGroup:
        """Make a group from a run of photos.

        Args:
            number: Number of the group, from 1.
            photos: The photos of the group, in time order.
            project: Gives the sharpness for the sample photo.

        Returns:
            The group.
        """
        photo_ids = [photo.id for photo in photos]
        sample_id = self._sample_of(photos, project)
        details = self._time_range(photos)
        return PhotoGroup(f"group-{number}", f"Group {number}", photo_ids, sample_id, details)


class FaceGrouper(Grouper):
    """Puts photos together that show the same people.

    Photos with exactly the same people form one group. Photos without any
    known face form the last group.
    """

    NOBODY_TITLE = "No people found"

    def make_groups(self, photos: Sequence[Photo], project: Project) -> list[PhotoGroup]:
        """Split photos by the people they show.

        Args:
            photos: The photos to group.
            project: Gives the people in each photo.

        Returns:
            The groups, the largest first, and the group without people last.
        """
        ordered = sorted(photos, key=Photo.sort_key)
        buckets: dict[tuple[str, ...], list[Photo]] = {}
        for photo in ordered:
            people = project.people_in(photo.id)
            person_ids = [person.id for person in people]
            key = tuple(person_ids)
            bucket = buckets.setdefault(key, [])
            bucket.append(photo)
        items = [(key, bucket) for key, bucket in buckets.items()]
        items.sort(key=self._bucket_order)
        groups: list[PhotoGroup] = []
        for number, (key, bucket) in enumerate(items, start=1):
            group = self._make_group(number, key, bucket, project)
            groups.append(group)
        return groups

    def _bucket_order(self, item: tuple[tuple[str, ...], list[Photo]]) -> tuple[bool, int]:
        """Sort key for the groups: groups with people first, then larger groups first.

        Args:
            item: The ids of the people and the photos that show them.

        Returns:
            (has no people, minus the number of photos).
        """
        person_ids, photos = item
        size = len(photos)
        return (not person_ids, -size)

    def _make_group(self, number: int, person_ids: tuple[str, ...], photos: Sequence[Photo], project: Project) -> PhotoGroup:
        """Make a group for the photos of one set of people.

        Args:
            number: Number of the group, from 1.
            person_ids: Ids of the people the photos show.
            photos: The photos, in time order.
            project: Gives the people's names and the sharpness for the sample photo.

        Returns:
            The group.
        """
        title = self.title_for(person_ids, project)
        photo_ids = [photo.id for photo in photos]
        sample_id = self._sample_of(photos, project)
        details = self._time_range(photos)
        return PhotoGroup(f"group-{number}", title, photo_ids, sample_id, details, person_ids)

    def title_for(self, person_ids: Sequence[str], project: Project) -> str:
        """The title of a group made by people: their names joined with "&".

        Args:
            person_ids: Ids of the people.
            project: Gives the people's names.

        Returns:
            Text such as "Person 1 & Person 2", or "No people found".
        """
        names: list[str] = []
        for person_id in person_ids:
            person = project.person(person_id)
            if person is not None:
                names.append(person.name)
        if not names:
            return self.NOBODY_TITLE
        return " & ".join(names)
