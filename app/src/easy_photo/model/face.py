"""Faces found in photos, and the people they belong to."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DESCRIPTION_LENGTH = 128
"""Number of values in a face description made by the SFace model."""


@dataclass(frozen=True)
class FaceBox:
    """Where a face is in a photo, as fractions (0 to 1) of the photo's width and height."""

    left: float
    top: float
    width: float
    height: float

    def to_pixels(self, image_width: int, image_height: int) -> tuple[int, int, int, int]:
        """Give the box in pixels for a picture of the given size.

        Args:
            image_width: Width of the picture in pixels.
            image_height: Height of the picture in pixels.

        Returns:
            The box as (x, y, width, height) in pixels.
        """
        x = round(self.left * image_width)
        y = round(self.top * image_height)
        width = round(self.width * image_width)
        height = round(self.height * image_height)
        return (x, y, width, height)


@dataclass(frozen=True, eq=False)
class Face:
    """One face found in a photo."""

    face_id: str
    photo_id: str
    box: FaceBox

    score: float
    """How sure the face finder is that this is a face, 0 to 1."""

    description: np.ndarray
    """128 numbers that describe the face, scaled to length 1. Faces of one person have similar numbers."""

    thumbnail: np.ndarray
    """A small RGB picture of the face, for the window."""


class Person:
    """A person: a name and the faces found for them."""

    def __init__(self, person_id: str, name: str) -> None:
        """Create a person without faces.

        Args:
            person_id: Unique id of the person.
            name: Name shown in the window, such as "Person 1".
        """
        self._id = person_id
        self._name = name
        self._faces: list[Face] = []
        self._description_sum = np.zeros(DESCRIPTION_LENGTH, dtype=np.float32)

    @property
    def id(self) -> str:
        """Unique id of the person."""
        return self._id

    @property
    def name(self) -> str:
        """Name shown in the window."""
        return self._name

    @name.setter
    def name(self, name: str) -> None:
        """Give the person a new name.

        Args:
            name: The new name.
        """
        self._name = name

    @property
    def faces(self) -> tuple[Face, ...]:
        """The faces of this person."""
        return tuple(self._faces)

    @property
    def face_count(self) -> int:
        """Number of faces of this person."""
        return len(self._faces)

    @property
    def photo_ids(self) -> set[str]:
        """Ids of the photos that show this person."""
        return {face.photo_id for face in self._faces}

    @property
    def average_description(self) -> np.ndarray:
        """The average of the person's face descriptions, scaled to length 1."""
        length = np.linalg.norm(self._description_sum)
        if length == 0:
            return self._description_sum
        return self._description_sum / length

    @property
    def sample_face(self) -> Face | None:
        """The face the face finder was most sure about, to show in the window."""
        best: Face | None = None
        for face in self._faces:
            if best is None or face.score > best.score:
                best = face
        return best

    def add_face(self, face: Face) -> None:
        """Add a face to this person.

        Args:
            face: The face to add.
        """
        self._faces.append(face)
        self._description_sum = self._description_sum + face.description

    def take_faces_from(self, other: Person) -> None:
        """Move all faces of another person to this one, when both are the same person.

        Args:
            other: The person whose faces are taken over.
        """
        for face in other.faces:
            self.add_face(face)
