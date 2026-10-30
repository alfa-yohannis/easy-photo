"""Groups of photos that get the same refinement."""

from __future__ import annotations

from collections.abc import Sequence


class PhotoGroup:
    """Photos that belong together, such as one scene or the same people.

    Every photo of a group gets the refinement the user picks for the group.
    The sample photo stands for the group when versions are compared.
    """

    def __init__(
        self,
        group_id: str,
        title: str,
        photo_ids: Sequence[str],
        sample_id: str,
        details: str = "",
        person_ids: Sequence[str] = (),
        renamed: bool = False,
    ) -> None:
        """Create a group.

        Args:
            group_id: Unique id of the group.
            title: Name shown in the window, such as "Group 3".
            photo_ids: Ids of the photos in the group, in time order.
            sample_id: Id of the photo shown when versions are compared.
            details: Extra line for the window, such as the time range.
            person_ids: For a group made by people, the ids of the people it shows.
            renamed: True when the title is a name the user gave the group.
        """
        self._id = group_id
        self._title = title
        self._photo_ids = tuple(photo_ids)
        self._sample_id = sample_id
        self._details = details
        self._person_ids = tuple(person_ids)
        self._renamed = renamed

    @property
    def person_ids(self) -> tuple[str, ...]:
        """For a group made by people, the ids of the people it shows; empty otherwise."""
        return self._person_ids

    @property
    def renamed(self) -> bool:
        """True when the title is a name the user gave the group; the app then never changes it."""
        return self._renamed

    def with_title(self, title: str) -> PhotoGroup:
        """A copy of this group with another title, for example after a person was renamed.

        Args:
            title: The new title.

        Returns:
            The new group; this group does not change.
        """
        return PhotoGroup(
            self._id, title, self._photo_ids, self._sample_id, self._details, self._person_ids, self._renamed
        )

    def renamed_to(self, title: str) -> PhotoGroup:
        """A copy of this group with a name the user gave it.

        Args:
            title: The user's name for the group.

        Returns:
            The new group; this group does not change.
        """
        return PhotoGroup(self._id, title, self._photo_ids, self._sample_id, self._details, self._person_ids, True)

    @property
    def id(self) -> str:
        """Unique id of the group."""
        return self._id

    @property
    def title(self) -> str:
        """Name shown in the window."""
        return self._title

    @property
    def details(self) -> str:
        """Extra line for the window, such as the time range."""
        return self._details

    @property
    def photo_ids(self) -> tuple[str, ...]:
        """Ids of the photos in the group, in time order."""
        return self._photo_ids

    @property
    def size(self) -> int:
        """Number of photos in the group."""
        return len(self._photo_ids)

    @property
    def sample_id(self) -> str:
        """Id of the photo shown when versions are compared."""
        return self._sample_id

    def contains(self, photo_id: str) -> bool:
        """Tell whether a photo belongs to this group.

        Args:
            photo_id: Id of the photo.

        Returns:
            True when the photo is in the group.
        """
        return photo_id in self._photo_ids
