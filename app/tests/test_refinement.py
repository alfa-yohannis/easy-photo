"""Tests of the brightness curve, the refinement steps, pipelines and typed commands."""

from __future__ import annotations

import numpy as np
import pytest

from easy_photo.refinement.commands import CommandParser
from easy_photo.refinement.light import BrightnessCurve, LinearLight
from easy_photo.refinement.pipeline import PipelineSource, RefinementPipeline
from easy_photo.refinement.steps import (
    ContrastStep,
    ExposureStep,
    FaceBrightnessStep,
    HighlightsStep,
    MatchBrightnessStep,
    NeutralColorStep,
    SaturationStep,
    ShadowsStep,
    StepCatalog,
    StepContext,
    WarmthStep,
)
from easy_photo.refinement.targets import BrightnessTargets


def test_curve_moves_one_level_to_another() -> None:
    """The curve made from two levels moves the first level onto the second."""
    curve = BrightnessCurve.from_levels(0.1, 0.25)
    moved = curve.apply_to_value(0.1)
    assert moved == pytest.approx(0.25)


def test_curve_keeps_black_and_white() -> None:
    """Black and white do not move."""
    curve = BrightnessCurve.from_stops(1.0)
    black = curve.apply_to_value(0.0)
    white = curve.apply_to_value(1.0)
    assert black == 0.0
    assert white == pytest.approx(1.0)


def test_curve_keeps_the_colors() -> None:
    """All three channels of a pixel are scaled by the same factor."""
    pixel = np.array([[[0.2, 0.1, 0.05]]], dtype=np.float32)
    curve = BrightnessCurve.from_stops(0.8)
    brighter = curve.apply(pixel)
    ratios = brighter / pixel
    smallest = ratios.min()
    largest = ratios.max()
    assert largest == pytest.approx(smallest, rel=1e-5)
    assert brighter[0, 0, 0] > pixel[0, 0, 0]


def test_linear_light_round_trip() -> None:
    """Going to linear light and back gives the same 8-bit values."""
    light = LinearLight()
    levels = np.arange(256, dtype=np.uint8)
    pixels = levels.reshape(16, 16)
    linear = light.to_linear(pixels)
    back = light.to_srgb_8bit(linear)
    assert np.array_equal(back, pixels)


def test_tone_steps_keep_black_and_white() -> None:
    """Contrast, shadows and highlights leave pure black and pure white alone."""
    context = StepContext()
    pixels = np.array([[[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]]], dtype=np.float32)
    for step in (ContrastStep(40), ShadowsStep(1.0), HighlightsStep(-1.0)):
        changed = step.apply(pixels, context)
        assert changed == pytest.approx(pixels, abs=1e-4)


def test_shadows_lift_dark_tones_more_than_bright_ones() -> None:
    """Lifting the shadows brightens a dark grey much more than a light grey."""
    light = LinearLight()
    context = StepContext()
    dark_grey = np.float32(0.25)
    light_grey = np.float32(0.85)
    dark_value = light.to_linear_values(dark_grey)
    bright_value = light.to_linear_values(light_grey)
    pixels = np.array([[[dark_value] * 3, [bright_value] * 3]], dtype=np.float32)
    changed = ShadowsStep(1.0).apply(pixels, context)
    dark_gain = changed[0, 0, 0] / pixels[0, 0, 0]
    bright_gain = changed[0, 1, 0] / pixels[0, 1, 0]
    assert dark_gain > bright_gain > 1.0


def test_saturation_minus_100_gives_grey() -> None:
    """Saturation -100 removes all color."""
    context = StepContext()
    pixels = np.array([[[0.6, 0.2, 0.1]]], dtype=np.float32)
    grey = SaturationStep(-100).apply(pixels, context)
    assert grey[0, 0, 0] == pytest.approx(grey[0, 0, 2])


def test_neutral_colors_remove_a_warm_cast() -> None:
    """A grey photo with a warm cast becomes grey again."""
    context = StepContext()
    cast = np.array([0.24, 0.2, 0.16], dtype=np.float32)
    pixels = np.tile(cast, (20, 20, 1))
    neutral = NeutralColorStep(1.0).apply(pixels, context)
    red, green, blue = neutral[0, 0]
    assert red == pytest.approx(green, rel=1e-3)
    assert blue == pytest.approx(green, rel=1e-3)


def test_neutral_colors_ignore_a_colorful_subject() -> None:
    """A strongly colored subject is not taken for a cast when grey areas exist."""
    context = StepContext()
    pixels = np.full((20, 20, 3), 0.2, dtype=np.float32)
    pixels[:10] = np.array([0.5, 0.05, 0.05], dtype=np.float32)
    neutral = NeutralColorStep(1.0).apply(pixels, context)
    assert neutral == pytest.approx(pixels, rel=1e-3)


def test_amounts_are_kept_in_range() -> None:
    """An amount far outside the step's range is moved to the nearest end."""
    step = ExposureStep(50)
    assert step.amount == ExposureStep.HIGHEST


def test_match_brightness_raises_a_dark_photo() -> None:
    """A photo darker than the references' lower quarter is raised to their typical level."""
    targets = BrightnessTargets(0.15, 0.25, 0.32, 0.36, False, 10)
    step = MatchBrightnessStep(targets, "test references")
    context = StepContext()
    pixels = np.full((10, 10, 3), 0.05, dtype=np.float32)
    changed = step.apply(pixels, context)
    middle = np.median(changed)
    assert middle == pytest.approx(0.25, abs=0.01)


def test_match_brightness_leaves_a_photo_in_range() -> None:
    """A photo within the references' range is not changed."""
    targets = BrightnessTargets(0.15, 0.25, 0.32, 0.36, False, 10)
    step = MatchBrightnessStep(targets, "test references")
    context = StepContext()
    pixels = np.full((10, 10, 3), 0.2, dtype=np.float32)
    changed = step.apply(pixels, context)
    assert np.array_equal(changed, pixels)


def test_face_step_uses_the_face_box() -> None:
    """Brightening faces by one stop doubles the light of a dark face (whole photo, one curve)."""
    pixels = np.full((100, 100, 3), 0.4, dtype=np.float32)
    pixels[40:60, 40:60] = 0.05
    context = StepContext(face_boxes=((40, 40, 20, 20),))
    changed = FaceBrightnessStep(1.0).apply(pixels, context)
    face_after = changed[50, 50, 0]
    assert face_after == pytest.approx(0.1, rel=0.1)


def test_parser_reads_several_phrases() -> None:
    """Commas, "and" and strength words are understood."""
    parser = CommandParser()
    parsed = parser.parse("brighter, more contrast and slightly warmer")
    kinds = [step.KIND for step in parsed.steps]
    amounts = [step.amount for step in parsed.steps]
    assert parsed.is_complete
    assert kinds == ["exposure", "contrast", "warmth"]
    assert amounts == [0.3, 20.0, 3.0]


def test_parser_reads_numbers() -> None:
    """A phrase can give its amount as a number, with a dot or a comma."""
    parser = CommandParser()
    parsed = parser.parse("exposure +0.5; contrast -10; shadows 0,4")
    amounts = [step.amount for step in parsed.steps]
    assert amounts == [0.5, -10.0, 0.4]


def test_parser_reads_neutral_once() -> None:
    """ "neutral, not warm, not cool" means one change: neutral colors."""
    parser = CommandParser()
    parsed = parser.parse("neutral, not warm, not cool")
    kinds = [step.KIND for step in parsed.steps]
    assert parsed.is_complete
    assert kinds == ["neutral_colors"]


def test_parser_reports_unknown_phrases() -> None:
    """Phrases that match no rule are listed, and the command is not complete."""
    parser = CommandParser()
    parsed = parser.parse("brighter, make it pop")
    assert parsed.unknown == ("make it pop",)
    assert not parsed.is_complete


def test_every_example_phrase_is_understood() -> None:
    """The examples shown to the user all work."""
    parser = CommandParser()
    for example in parser.examples():
        parsed = parser.parse(example)
        assert parsed.is_complete, example


def test_steps_survive_the_manifest() -> None:
    """Every kind of step can be saved and read back."""
    catalog = StepCatalog()
    targets = BrightnessTargets(0.1, 0.2, 0.3, 0.35, True, 5)
    steps = [
        ExposureStep(0.4),
        ContrastStep(-15),
        ShadowsStep(0.5),
        HighlightsStep(-0.5),
        SaturationStep(10),
        WarmthStep(-4),
        NeutralColorStep(0.5),
        FaceBrightnessStep(0.3),
        MatchBrightnessStep(targets, "your history"),
    ]
    for step in steps:
        data = step.to_data()
        loaded = catalog.load(data)
        loaded_data = loaded.to_data()
        assert loaded_data == data


def test_pipeline_survives_the_manifest() -> None:
    """A pipeline can be saved and read back, and extending it keeps the original."""
    catalog = StepCatalog()
    exposure = ExposureStep(0.3)
    pipeline = RefinementPipeline("words-1", "Your words: brighter", PipelineSource.WORDS, [exposure], "typed")
    contrast = ContrastStep(20)
    longer = pipeline.extended("words-2", "brighter + contrast", [contrast])
    data = longer.to_data()
    loaded = RefinementPipeline.from_data(data, catalog)
    assert loaded.describe_steps() == "Exposure +0.3 EV, Contrast +20 %"
    assert pipeline.describe_steps() == "Exposure +0.3 EV"
    assert loaded.source is PipelineSource.WORDS
