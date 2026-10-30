"""Tests of finding, reading, measuring and checking photos."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import ExifTags, Image

from easy_photo.model.quality import Decision, Problem, QualityScores
from easy_photo.services.photo_analyzer import PhotoAnalyzer
from easy_photo.services.photo_finder import PhotoFinder
from easy_photo.services.photo_reader import PhotoReader
from easy_photo.services.preview_cache import PreviewCache
from easy_photo.services.quality_checks import QualityChecker
from easy_photo.settings import CheckSettings
from tests.conftest import PhotoMaker

MORNING = datetime(2024, 12, 14, 10, 0, 0)


def test_finder_skips_hidden_and_unknown_files(tmp_path: Path) -> None:
    """Only readable photo files are found, each once, also in subfolders."""
    inner = tmp_path / "inner"
    inner.mkdir()
    for name in ("a.JPG", "b.rw2", ".hidden.jpg", "notes.txt", "inner/c.png"):
        path = tmp_path / name
        path.write_bytes(b"x")
    finder = PhotoFinder()
    photos = finder.find([tmp_path, tmp_path])
    names = sorted(photo.name for photo in photos)
    assert names == ["a.JPG", "b.rw2", "c.png"]


def test_reader_turns_photos_upright_and_reads_the_time(tmp_path: Path) -> None:
    """A JPEG with an EXIF orientation comes out upright, with its time and camera."""
    pixels = np.zeros((40, 80, 3), dtype=np.uint8)
    image = Image.fromarray(pixels)
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = 6
    exif[ExifTags.Base.DateTime] = "2024:12:14 10:00:00"
    exif[ExifTags.Base.Make] = "Panasonic"
    exif[ExifTags.Base.Model] = "DC-S5"
    exif_bytes = exif.tobytes()
    path = tmp_path / "turned.jpg"
    image.save(path, "JPEG", exif=exif_bytes)
    finder = PhotoFinder()
    photos = finder.find([path])
    cache_folder = tmp_path / "cache"
    cache = PreviewCache(cache_folder)
    reader = PhotoReader(cache)
    data = reader.read(photos[0], 1024)
    assert data.pixels.shape[:2] == (80, 40)
    assert data.info.taken_at == MORNING
    assert data.info.camera == "Panasonic DC-S5"


def test_analyzer_tells_sharp_from_blurred(photo_maker: PhotoMaker) -> None:
    """A sharp scene scores far higher on sharpness than the same scene blurred."""
    analyzer = PhotoAnalyzer()
    sharp = photo_maker.scene((1.0, 0.9, 0.8), 1)
    blurred = photo_maker.blurred(sharp)
    sharp_scores = analyzer.analyze(sharp).scores
    blurred_scores = analyzer.analyze(blurred).scores
    assert sharp_scores.sharpness > 10 * blurred_scores.sharpness


def test_checker_sets_aside_a_blurred_photo(photo_maker: PhotoMaker) -> None:
    """The default limits set a badly blurred photo aside and keep a sharp one."""
    analyzer = PhotoAnalyzer()
    settings = CheckSettings()
    checker = QualityChecker.from_settings(settings)
    sharp = photo_maker.scene((1.0, 0.9, 0.8), 2)
    blurred = photo_maker.blurred(sharp)
    sharp_analysis = analyzer.analyze(sharp)
    blurred_analysis = analyzer.analyze(blurred)
    sharp_result = checker.evaluate(sharp_analysis.scores)
    blurred_result = checker.evaluate(blurred_analysis.scores)
    assert sharp_result.decision is Decision.KEEP
    assert blurred_result.decision is Decision.SET_ASIDE
    assert Problem.BLURRED in blurred_result.problems


def test_checker_finds_too_dark_and_too_bright() -> None:
    """Very dark and blown-out scores are set aside for the right reason."""
    settings = CheckSettings()
    checker = QualityChecker.from_settings(settings)
    dark = QualityScores(sharpness=500.0, contrast=0.2, highlight=0.03, blown_share=0.0)
    bright = QualityScores(sharpness=500.0, contrast=0.2, highlight=1.0, blown_share=0.9)
    dark_result = checker.evaluate(dark)
    bright_result = checker.evaluate(bright)
    assert dark_result.problems == [Problem.TOO_DARK]
    assert bright_result.problems == [Problem.TOO_BRIGHT]


def test_checker_is_unsure_near_a_limit() -> None:
    """A value just inside the margin makes the photo unsure, not set aside."""
    settings = CheckSettings()
    checker = QualityChecker.from_settings(settings)
    near = settings.min_sharpness + settings.sharpness_margin / 2
    scores = QualityScores(sharpness=near, contrast=0.2, highlight=0.8, blown_share=0.0)
    result = checker.evaluate(scores)
    assert result.decision is Decision.UNSURE
    assert result.decision.is_kept


def test_similar_photos_look_alike(photo_maker: PhotoMaker) -> None:
    """Two photos of one scene are more alike than photos of two different scenes."""
    analyzer = PhotoAnalyzer()
    warm_tint = (1.0, 0.6, 0.3)
    cold_tint = (0.3, 0.5, 1.0)
    warm_one = photo_maker.scene(warm_tint, 3)
    warm_two = photo_maker.scene(warm_tint, 4)
    cold = photo_maker.scene(cold_tint, 5)
    warm_one_summary = analyzer.analyze(warm_one).summary
    warm_two_summary = analyzer.analyze(warm_two).summary
    cold_summary = analyzer.analyze(cold).summary
    same_scene = warm_one_summary.similarity_to(warm_two_summary)
    other_scene = warm_one_summary.similarity_to(cold_summary)
    assert same_scene > other_scene
