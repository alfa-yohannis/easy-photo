"""Tests of the project manifest and of the export."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from PIL import ExifTags, Image

from easy_photo.model.group import PhotoGroup
from easy_photo.model.photo import FileKind, Photo
from easy_photo.model.project import Project, SavedName
from easy_photo.model.quality import Decision, QualityResult, QualityScores
from easy_photo.refinement.pipeline import PipelineSource, RefinementPipeline
from easy_photo.refinement.steps import ContrastStep, StepCatalog
from easy_photo.services.darktable import DarktableRenderer
from easy_photo.services.developer import PhotoDeveloper
from easy_photo.services.exporter import Exporter, ExportStatus
from easy_photo.services.manifest import ManifestError, ProjectManifest
from easy_photo.services.photo_finder import PhotoFinder
from easy_photo.services.photo_reader import PhotoReader
from easy_photo.services.preview_cache import PreviewCache
from easy_photo.services.refiner import Refiner
from easy_photo.settings import ExportSettings
from tests.conftest import PhotoMaker

MORNING = datetime(2024, 12, 14, 10, 0, 0)


def make_manifest() -> ProjectManifest:
    """A manifest reader and writer with the standard step catalog.

    Returns:
        The manifest object.
    """
    catalog = StepCatalog()
    return ProjectManifest(catalog)


def make_exporter(folder: Path) -> Exporter:
    """An exporter for ordinary image files, without darktable.

    Args:
        folder: Test folder for the preview cache.

    Returns:
        The exporter.
    """
    cache_folder = folder / "cache"
    cache = PreviewCache(cache_folder)
    reader = PhotoReader(cache)
    missing = DarktableRenderer(None)
    developer = PhotoDeveloper(reader, missing)
    refiner = Refiner()
    return Exporter(reader, developer, refiner)


def test_manifest_keeps_the_users_work(tmp_path: Path) -> None:
    """Sources, limits, decisions, names, groups, options and picks survive saving and opening."""
    manifest = make_manifest()
    folder = tmp_path / "Japan 2024"
    project = manifest.create("Japan 2024", folder)
    photos_folder = tmp_path / "photos"
    project.add_source(photos_folder)
    project.checks.min_sharpness = 33.0
    project.decide("photo-a", Decision.SET_ASIDE)
    contrast = ContrastStep(20)
    option = RefinementPipeline("words-1", "Your words: more contrast", PipelineSource.WORDS, [contrast])
    project.add_pipeline(option)
    other = RefinementPipeline("words-2", "Your words: less contrast", PipelineSource.WORDS, [contrast])
    project.add_pipeline(other)
    group = PhotoGroup("group-1", "Group 1", ["photo-a", "photo-b"], "photo-b", "14 Dec 2024", ["person-1"])
    named_group = group.renamed_to("Tokyo Tower")
    project.set_groups([named_group])
    project.choose("group-1", "words-1")
    project.set_option_used("group-1", "words-2", False)
    saved_name = SavedName("Papa", ("photo-b#0",))
    project.set_saved_names([saved_name])
    manifest.save(project)
    opened = manifest.load(folder)
    reopened_group = opened.group("group-1")
    assert opened.name == "Japan 2024"
    assert opened.sources == (photos_folder,)
    assert opened.checks.min_sharpness == 33.0
    assert opened.user_decision_of("photo-a") is Decision.SET_ASIDE
    assert opened.pipeline("words-1").describe_steps() == "Contrast +20 %"
    assert reopened_group.photo_ids == ("photo-a", "photo-b")
    assert reopened_group.person_ids == ("person-1",)
    assert reopened_group.title == "Tokyo Tower"
    assert reopened_group.renamed
    assert opened.choice_of("group-1").pipeline_id == "words-1"
    assert opened.saved_names() == [saved_name]
    assert opened.option_used_in("group-1", "words-1")
    assert not opened.option_used_in("group-1", "words-2")


def test_the_sharpest_selected_photo_stands_for_a_group(tmp_path: Path) -> None:
    """The group's sample is the sharpest selected photo; with none selected, the photo picked at grouping."""
    project = Project("Samples", tmp_path)
    photos = [Photo(tmp_path / f"P100000{number}.RW2", FileKind.RAW) for number in range(3)]
    project.set_photos(photos)
    for photo, sharpness in zip(photos, [40.0, 90.0, 60.0]):
        scores = QualityScores(sharpness, 0.2, 0.8, 0.0)
        result = QualityResult(scores, ())
        project.set_quality(photo.id, result)
    photo_ids = [photo.id for photo in photos]
    group = PhotoGroup("group-1", "Group 1", photo_ids, photo_ids[0])
    sharpest = project.sample_of(group)
    project.decide(photo_ids[1], Decision.SET_ASIDE)
    sharpest_selected = project.sample_of(group)
    project.decide(photo_ids[0], Decision.SET_ASIDE)
    project.decide(photo_ids[2], Decision.SET_ASIDE)
    none_selected = project.sample_of(group)
    assert sharpest is photos[1]
    assert sharpest_selected is photos[2]
    assert none_selected is photos[0]


def test_removing_a_group_takes_its_pick_and_own_options(tmp_path: Path) -> None:
    """A removed group leaves no pick, typed option or turned-off option behind; the other group keeps its own."""
    manifest = make_manifest()
    project = manifest.create("Two groups", tmp_path)
    first = PhotoGroup("group-1", "Group 1", ["photo-a"], "photo-a")
    second = PhotoGroup("group-2", "Group 2", ["photo-b"], "photo-b")
    project.set_groups([first, second])
    contrast = ContrastStep(20)
    typed = RefinementPipeline("typed-1", "more contrast", PipelineSource.WORDS, [contrast])
    shared = RefinementPipeline("words-1", "Your words: more contrast", PipelineSource.WORDS, [contrast])
    project.add_pipeline(shared)
    project.add_group_pipeline("group-2", typed)
    project.choose("group-1", "words-1")
    project.choose("group-2", "typed-1")
    project.set_option_used("group-2", "words-1", False)
    project.remove_group("group-2")
    group_ids = [group.id for group in project.groups]
    assert group_ids == ["group-1"]
    assert project.choice_of("group-2") is None
    assert project.group_pipelines("group-2") == []
    assert project.unused_options == {}
    assert project.choice_of("group-1").pipeline_id == "words-1"


def test_manifest_refuses_a_second_project_in_one_folder(tmp_path: Path) -> None:
    """Creating a project where one already exists fails."""
    manifest = make_manifest()
    manifest.create("One", tmp_path)
    with pytest.raises(ManifestError):
        manifest.create("Two", tmp_path)


def test_manifest_reports_a_file_that_is_not_a_project(tmp_path: Path) -> None:
    """Opening a JSON file of another kind fails with a clear error."""
    manifest = make_manifest()
    path = tmp_path / ProjectManifest.FILE_NAME
    other = {"format": "something else"}
    text = json.dumps(other)
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ManifestError):
        manifest.load(path)


def test_export_shrinks_keeps_details_and_never_overwrites(tmp_path: Path, photo_maker: PhotoMaker) -> None:
    """The export writes the long side asked for, copies the camera details, and skips existing files."""
    pixels = photo_maker.scene((0.9, 0.8, 0.7), 1)
    source = photo_maker.write("P1000001", pixels, MORNING)
    finder = PhotoFinder()
    photos = finder.find([source])
    exporter = make_exporter(tmp_path)
    camera = RefinementPipeline.camera()
    output = tmp_path / "export"
    output_text = str(output)
    settings = ExportSettings(output_text, 320, 95, True)
    first = exporter.export(photos[0], camera, [], settings)
    second = exporter.export(photos[0], camera, [], settings)
    assert first.status is ExportStatus.WRITTEN
    assert second.status is ExportStatus.SKIPPED
    with Image.open(first.target) as written:
        size = written.size
        exif = written.getexif()
    assert max(size) == 320
    assert exif.get(ExifTags.Base.DateTime) == "2024:12:14 10:00:00"
    leftovers = [path for path in output.glob("*.part")]
    assert leftovers == []


def test_export_overwrites_only_when_asked(tmp_path: Path, photo_maker: PhotoMaker) -> None:
    """With overwrite on, an existing file is replaced in one step and the result says so."""
    pixels = photo_maker.scene((0.9, 0.8, 0.7), 1)
    source = photo_maker.write("P1000001", pixels, MORNING)
    finder = PhotoFinder()
    photos = finder.find([source])
    exporter = make_exporter(tmp_path)
    camera = RefinementPipeline.camera()
    output = tmp_path / "export"
    output_text = str(output)
    first_settings = ExportSettings(output_text, 320, 95, True)
    replace_settings = ExportSettings(output_text, 200, 95, True, True, True)
    first = exporter.export(photos[0], camera, [], first_settings)
    replaced = exporter.export(photos[0], camera, [], replace_settings)
    with Image.open(replaced.target) as written:
        size = written.size
    leftovers = [path for path in output.glob(".*.part")]
    assert first.status is ExportStatus.WRITTEN
    assert replaced.status is ExportStatus.REPLACED
    assert replaced.status.is_written
    assert max(size) == 200
    assert leftovers == []


def test_export_sharpens_only_when_asked(tmp_path: Path, photo_maker: PhotoMaker) -> None:
    """The light sharpen after shrinking adds edge contrast, and can be switched off."""
    pixels = photo_maker.scene((0.9, 0.8, 0.7), 1)
    source = photo_maker.write("P1000001", pixels, MORNING)
    finder = PhotoFinder()
    photos = finder.find([source])
    exporter = make_exporter(tmp_path)
    camera = RefinementPipeline.camera()
    edge_contrast: list[float] = []
    for sharpen in [False, True]:
        output = tmp_path / f"export-{sharpen}"
        output_text = str(output)
        settings = ExportSettings(output_text, 320, 100, False, sharpen)
        result = exporter.export(photos[0], camera, [], settings)
        with Image.open(result.target) as written:
            values = np.asarray(written, dtype=np.float64)
        steps = np.diff(values, axis=0)
        sizes = np.abs(steps)
        mean_size = sizes.mean()
        contrast = float(mean_size)
        edge_contrast.append(contrast)
    soft, sharpened = edge_contrast
    assert sharpened > soft
