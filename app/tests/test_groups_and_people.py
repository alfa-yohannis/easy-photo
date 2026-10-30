"""Tests of grouping photos and sorting faces into people."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from easy_photo.model.face import Face, FaceBox
from easy_photo.model.photo import FileKind, Photo, PhotoInfo
from easy_photo.model.project import Project
from easy_photo.model.quality import QualityResult, QualityScores
from easy_photo.model.summary import VisualSummary
from easy_photo.services.faces import PeopleSorter
from easy_photo.services.grouping import FaceGrouper, SimilarityGrouper

START = datetime(2024, 12, 14, 10, 0, 0)


def make_project(tmp_path: Path, minutes: list[int], looks: list[int]) -> tuple[Project, list[Photo]]:
    """Make a project with measured photos taken at the given minutes, with one of two looks.

    Args:
        tmp_path: Folder for the project.
        minutes: Minute after 10:00 at which each photo was taken.
        looks: 0 or 1 for each photo; photos with the same look look alike.

    Returns:
        The project and its photos.
    """
    project = Project("Test", tmp_path)
    histograms = [np.array([1.0, 0.0]), np.array([0.0, 1.0])]
    layout = np.array([1.0, 0.0])
    scores = QualityScores(sharpness=100.0, contrast=0.2, highlight=0.8, blown_share=0.0)
    result = QualityResult(scores, ())
    photos: list[Photo] = []
    for number, minute in enumerate(minutes):
        path = tmp_path / f"photo-{number}.jpg"
        photo = Photo(path, FileKind.IMAGE)
        offset = timedelta(minutes=minute)
        photo.info = PhotoInfo(taken_at=START + offset)
        photos.append(photo)
    project.set_photos(photos)
    for photo, look in zip(photos, looks):
        summary = VisualSummary(histograms[look], layout)
        project.set_analysis(photo.id, result, summary)
    return project, photos


def make_face(photo_id: str, number: int, direction: np.ndarray) -> Face:
    """Make a face whose description points in a given direction.

    Args:
        photo_id: Id of the photo it is in.
        number: Number of the face in the photo.
        direction: The description before scaling to length 1.

    Returns:
        The face.
    """
    length = np.linalg.norm(direction)
    description = direction / length
    box = FaceBox(0.4, 0.3, 0.1, 0.15)
    thumbnail = np.zeros((8, 8, 3), dtype=np.uint8)
    return Face(f"{photo_id}#{number}", photo_id, box, 0.9, description, thumbnail)


def test_similarity_grouper_splits_on_long_pauses(tmp_path: Path) -> None:
    """A pause longer than the limit starts a new group, even when the photos look alike."""
    project, photos = make_project(tmp_path, [0, 1, 2, 40, 41], [0, 0, 0, 0, 0])
    grouper = SimilarityGrouper(max_gap_minutes=10, min_similarity=0.5)
    groups = grouper.make_groups(photos, project)
    sizes = [group.size for group in groups]
    assert sizes == [3, 2]


def test_similarity_grouper_splits_on_a_different_look(tmp_path: Path) -> None:
    """Photos taken close together but looking different go into different groups."""
    project, photos = make_project(tmp_path, [0, 1, 2, 3], [0, 0, 1, 1])
    grouper = SimilarityGrouper(max_gap_minutes=10, min_similarity=0.6)
    groups = grouper.make_groups(photos, project)
    sizes = [group.size for group in groups]
    assert sizes == [2, 2]
    assert groups[0].details.startswith("14 Dec 2024, 10:00")


def test_people_sorter_finds_two_people() -> None:
    """Faces with two kinds of description are sorted into two people."""
    generator = np.random.default_rng(7)
    first_direction = generator.normal(size=128)
    second_direction = generator.normal(size=128)
    faces: list[Face] = []
    for number in range(4):
        first_noise = generator.normal(scale=0.2, size=128)
        second_noise = generator.normal(scale=0.2, size=128)
        first = make_face(f"a{number}", 0, first_direction + first_noise)
        second = make_face(f"b{number}", 0, second_direction + second_noise)
        faces.extend([first, second])
    sorter = PeopleSorter()
    people = sorter.sort(faces)
    counts = [person.face_count for person in people]
    names = [person.name for person in people]
    assert counts == [4, 4]
    assert names == ["Person 1", "Person 2"]


def test_face_grouper_groups_by_people_and_keeps_names(tmp_path: Path) -> None:
    """Photos with the same people share a group; renaming keeps the group but changes its title."""
    project, photos = make_project(tmp_path, [0, 1, 2], [0, 0, 0])
    generator = np.random.default_rng(3)
    direction = generator.normal(size=128)
    faces = {photos[0].id: [make_face(photos[0].id, 0, direction)], photos[1].id: [], photos[2].id: []}
    second = make_face(photos[2].id, 0, direction)
    faces[photos[2].id].append(second)
    project.set_faces(faces)
    all_faces = project.all_faces()
    sorter = PeopleSorter()
    people = sorter.sort(all_faces)
    project.set_people(people)
    grouper = FaceGrouper()
    groups = grouper.make_groups(photos, project)
    titles = [group.title for group in groups]
    sizes = [group.size for group in groups]
    assert titles == ["Person 1", FaceGrouper.NOBODY_TITLE]
    assert sizes == [2, 1]
    people[0].name = "Papa"
    title = grouper.title_for(groups[0].person_ids, project)
    assert title == "Papa"
