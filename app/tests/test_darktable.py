"""Tests of darktable edits read from XMP files, of developing photos, and of exporting developed photos.

darktable-cli itself is replaced by a stand-in, so these tests run on
computers without darktable.
"""

from __future__ import annotations

import base64
import struct
import zlib
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree

import numpy as np
import pytest
from PIL import Image

from easy_photo.model.photo import FileKind, Photo
from easy_photo.refinement.pipeline import PipelineSource, RefinementPipeline
from easy_photo.refinement.steps import ExposureStep, StepCatalog
from easy_photo.services.darktable import DarktableRenderer
from easy_photo.services.darktable_edit import DarktableEdit, DarktableEditError
from easy_photo.services.developer import DevelopError, PhotoDeveloper
from easy_photo.services.exporter import Exporter, ExportStatus
from easy_photo.services.photo_finder import PhotoFinder
from easy_photo.services.photo_reader import PhotoReader
from easy_photo.services.preview_cache import PreviewCache
from easy_photo.services.refiner import Refiner
from easy_photo.settings import ExportSettings
from tests.conftest import PhotoMaker

MORNING = datetime(2024, 12, 14, 10, 0, 0)
NAMESPACES = {"rdf": DarktableEdit.RDF, "darktable": DarktableEdit.DARKTABLE}


def blend_text(mask_mode: int, packed: bool) -> str:
    """darktable's text form of blend settings that start with a mask mode.

    Args:
        mask_mode: darktable's mask mode bits (2 = drawn mask, 4 = brightness or color range).
        packed: Write the "gz" form (base64 of zlib data) instead of hexadecimal text.

    Returns:
        The text for darktable:blendop_params.
    """
    settings = struct.pack("<II", mask_mode, 0)
    if not packed:
        return settings.hex()
    compressed = zlib.compress(settings)
    encoded = base64.b64encode(compressed)
    ascii_text = encoded.decode("ascii")
    return f"gz11{ascii_text}"


def write_sidecar(
    folder: Path,
    entries: list[tuple[str, str]],
    history_end: int,
    name: str = "P1000001.RW2.xmp",
    hashes: str = "",
) -> Path:
    """Write a darktable sidecar file with a history.

    Args:
        folder: Where the file goes.
        entries: (module, blend settings text) for each history entry, in order.
        history_end: darktable's history end; entries from this number on count as undone.
        name: File name.
        hashes: darktable's history hash attributes, written as they are; empty for none.

    Returns:
        The file.
    """
    items: list[str] = []
    for number, (operation, blend) in enumerate(entries):
        item = (
            f'     <rdf:li darktable:num="{number}" darktable:operation="{operation}" darktable:enabled="1"'
            f' darktable:modversion="1" darktable:params="0000803f" darktable:multi_name=""'
            f' darktable:multi_priority="0" darktable:blendop_version="13" darktable:blendop_params="{blend}"/>'
        )
        items.append(item)
    history = "\n".join(items)
    text = f"""<?xml version="1.0" encoding="UTF-8"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:xmpMM="http://ns.adobe.com/xap/1.0/mm/"
    xmlns:darktable="http://darktable.sf.net/"
   xmpMM:DerivedFrom="P1000001.RW2"
   darktable:xmp_version="5"
   darktable:auto_presets_applied="1"
   darktable:history_end="{history_end}"
   darktable:iop_order_version="2"
   {hashes}>
   <darktable:masks_history>
    <rdf:Seq>
     <rdf:li darktable:mask_num="1"/>
    </rdf:Seq>
   </darktable:masks_history>
   <darktable:history>
    <rdf:Seq>
{history}
    </rdf:Seq>
   </darktable:history>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
"""
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


def typical_edit(folder: Path) -> Path:
    """Write a sidecar with entries to keep, entries tied to the photo, and an undone entry.

    Args:
        folder: Where the file goes.

    Returns:
        The file.
    """
    plain = blend_text(0, False)
    drawn = blend_text(3, True)
    by_range = blend_text(5, False)
    entries = [
        ("rawprepare", plain),
        ("exposure", plain),
        ("crop", plain),
        ("toneequal", drawn),
        ("colorbalancergb", by_range),
        ("basecurve", plain),
    ]
    return write_sidecar(folder, entries, 5)


def make_reader(folder: Path) -> PhotoReader:
    """A photo reader with its preview cache in a test folder.

    Args:
        folder: The test folder.

    Returns:
        The reader.
    """
    cache_folder = folder / "cache"
    cache = PreviewCache(cache_folder)
    return PhotoReader(cache)


def edit_option(edit_file: Path) -> RefinementPipeline:
    """An option that applies a darktable edit and changes nothing else.

    Args:
        edit_file: The edit's XMP file.

    Returns:
        The option.
    """
    return RefinementPipeline("darktable-1", "darktable edit", PipelineSource.DARKTABLE, [], "", edit_file)


class StandInRenderer(DarktableRenderer):
    """Stands in for darktable-cli: remembers what it was asked and returns a mid-grey picture."""

    def __init__(self) -> None:
        """Create a stand-in that counts as installed."""
        executable = Path("darktable-cli")
        super().__init__(executable)
        self.requests: list[tuple[Path, str | None, int, bool]] = []

    def render(self, source: Path, edit_text: str | None, max_side: int, high_quality: bool = True) -> np.ndarray:
        """Remember the request and return a landscape picture of the asked size.

        Args:
            source: The raw file.
            edit_text: The edit's XMP text, or None.
            max_side: Longest side of the result.
            high_quality: Develop at full size and shrink at the end.

        Returns:
            RGB values of 0.5, max_side wide and two thirds as high.
        """
        request = (source, edit_text, max_side, high_quality)
        self.requests.append(request)
        height = max_side * 2 // 3
        return np.full((height, max_side, 3), 0.5, dtype=np.float32)


def test_edit_keeps_what_suits_other_photos(tmp_path: Path) -> None:
    """Crops, drawn masks and undone entries are left out; masks by brightness or color stay."""
    path = typical_edit(tmp_path)
    edit = DarktableEdit.read(path)
    assert edit.operations == ["exposure", "colorbalancergb"]
    assert edit.left_out == ["rawprepare", "crop", "toneequal"]
    assert edit.describe() == "exposure, color balance rgb"
    assert edit.describe_left_out() == "crop, tone equalizer"


def test_sidecar_for_darktable_cli_holds_only_the_kept_history(tmp_path: Path) -> None:
    """The new sidecar numbers its entries from 0, ends after them, and has no drawn shapes."""
    path = typical_edit(tmp_path)
    edit = DarktableEdit.read(path)
    text = edit.sidecar_text()
    root = ElementTree.fromstring(text)
    description = root.find(".//rdf:Description", NAMESPACES)
    end_name = DarktableEdit.qualified("history_end")
    presets_name = DarktableEdit.qualified("auto_presets_applied")
    version_name = DarktableEdit.qualified("xmp_version")
    items = description.findall("darktable:history/rdf:Seq/rdf:li", NAMESPACES)
    shapes = description.findall("darktable:masks_history/rdf:Seq/rdf:li", NAMESPACES)
    number_name = DarktableEdit.qualified("num")
    operation_name = DarktableEdit.qualified("operation")
    params_name = DarktableEdit.qualified("params")
    numbers = [item.get(number_name) for item in items]
    operations = [item.get(operation_name) for item in items]
    assert description.get(end_name) == "2"
    assert description.get(presets_name) == "1"
    assert description.get(version_name) == "5"
    assert numbers == ["0", "1"]
    assert operations == ["exposure", "colorbalancergb"]
    assert items[0].get(params_name) == "0000803f"
    assert shapes == []


def test_edit_refuses_files_without_a_darktable_history(tmp_path: Path) -> None:
    """A sidecar from another program, a broken file, and an edit that only fits its photo are refused."""
    other = tmp_path / "other.xmp"
    other.write_text('<x:xmpmeta xmlns:x="adobe:ns:meta/"/>', encoding="utf-8")
    broken = tmp_path / "broken.xmp"
    broken.write_text("<x:xmpmeta", encoding="utf-8")
    plain = blend_text(0, False)
    crop_only = write_sidecar(tmp_path, [("crop", plain)], 1)
    for path in [other, broken, crop_only]:
        with pytest.raises(DarktableEditError):
            DarktableEdit.read(path)


def test_a_raw_file_stands_for_its_edit_only_when_the_user_edited_it(tmp_path: Path) -> None:
    """A raw file counts as a darktable edit when its sidecar's history is not what darktable set up."""
    plain = blend_text(0, False)
    entries = [("exposure", plain)]
    edited_raw = tmp_path / "P1000004.RW2"
    edited_raw.write_bytes(b"raw")
    edited_hashes = 'darktable:history_auto_hash="aaaa" darktable:history_current_hash="bbbb"'
    edited_sidecar = write_sidecar(tmp_path, entries, 1, "P1000004.RW2.xmp", edited_hashes)
    untouched_raw = tmp_path / "P1000005.RW2"
    untouched_raw.write_bytes(b"raw")
    untouched_hashes = 'darktable:history_auto_hash="aaaa" darktable:history_current_hash="aaaa"'
    write_sidecar(tmp_path, entries, 1, "P1000005.RW2.xmp", untouched_hashes)
    bare_raw = tmp_path / "P1000006.RW2"
    bare_raw.write_bytes(b"raw")
    picture = tmp_path / "P1000007.jpg"
    picture.write_bytes(b"jpeg")
    assert DarktableEdit.edit_file_for(edited_raw) == edited_sidecar
    assert DarktableEdit.edit_file_for(edited_sidecar) == edited_sidecar
    assert DarktableEdit.edit_file_for(untouched_raw) is None
    assert DarktableEdit.edit_file_for(bare_raw) is None
    assert DarktableEdit.edit_file_for(picture) is None


def test_developer_applies_the_edit_to_raw_files_with_darktable(tmp_path: Path) -> None:
    """A raw file is developed by darktable with the cleaned edit, at the asked size."""
    edit_file = typical_edit(tmp_path)
    renderer = StandInRenderer()
    reader = make_reader(tmp_path)
    developer = PhotoDeveloper(reader, renderer)
    raw_path = tmp_path / "P1000002.RW2"
    raw = Photo(raw_path, FileKind.RAW)
    option = edit_option(edit_file)
    values = developer.develop(raw, option, 300, True)
    source, edit_text, max_side, high_quality = renderer.requests[0]
    assert values.shape == (200, 300, 3)
    assert source == raw_path
    assert 'darktable:operation="exposure"' in edit_text
    assert 'darktable:operation="crop"' not in edit_text
    assert max_side == 300
    assert high_quality
    assert developer.applies_edit(raw, option)


def test_developer_reads_ordinary_images_without_the_edit(tmp_path: Path, photo_maker: PhotoMaker) -> None:
    """A JPEG file is read as it is: darktable is not asked, and the edit is not applied."""
    pixels = photo_maker.scene((0.9, 0.8, 0.7), 1)
    source = photo_maker.write("P1000003", pixels, MORNING)
    finder = PhotoFinder()
    photos = finder.find([source])
    edit_file = typical_edit(tmp_path)
    renderer = StandInRenderer()
    reader = make_reader(tmp_path)
    developer = PhotoDeveloper(reader, renderer)
    option = edit_option(edit_file)
    values = developer.develop(photos[0], option, 320, True)
    largest = values.max()
    assert values.shape == (240, 320, 3)
    assert largest <= 1.0
    assert renderer.requests == []
    assert not developer.applies_edit(photos[0], option)


def test_developer_needs_darktable_for_an_edit(tmp_path: Path) -> None:
    """Without darktable-cli, a raw file cannot get a darktable edit."""
    edit_file = typical_edit(tmp_path)
    missing = DarktableRenderer(None)
    reader = make_reader(tmp_path)
    developer = PhotoDeveloper(reader, missing)
    raw_path = tmp_path / "P1000002.RW2"
    raw = Photo(raw_path, FileKind.RAW)
    option = edit_option(edit_file)
    with pytest.raises(DevelopError):
        developer.develop(raw, option, 300, True)


def test_export_writes_the_darktable_development(tmp_path: Path) -> None:
    """A raw file is exported from darktable's development, at the asked size, with an sRGB profile."""
    edit_file = typical_edit(tmp_path)
    renderer = StandInRenderer()
    reader = make_reader(tmp_path)
    developer = PhotoDeveloper(reader, renderer)
    refiner = Refiner()
    exporter = Exporter(reader, developer, refiner)
    raw_path = tmp_path / "P1000002.RW2"
    raw = Photo(raw_path, FileKind.RAW)
    brighter = ExposureStep(0.3)
    option = edit_option(edit_file)
    brighter_option = option.extended("darktable-1~brighter", "darktable edit, a little brighter", [brighter])
    output = tmp_path / "export"
    output_text = str(output)
    settings = ExportSettings(output_text, 300, 100, True)
    result = exporter.export(raw, brighter_option, [], settings)
    assert result.status is ExportStatus.WRITTEN
    assert result.message == ""
    with Image.open(result.target) as written:
        size = written.size
        has_profile = "icc_profile" in written.info
        middle = written.getpixel((150, 100))
    assert size == (300, 200)
    assert has_profile
    assert middle[0] > 128


def test_export_says_when_the_edit_was_left_out(tmp_path: Path, photo_maker: PhotoMaker) -> None:
    """A JPEG file in a group with a darktable edit is written without the edit, and the result says so."""
    pixels = photo_maker.scene((0.9, 0.8, 0.7), 1)
    source = photo_maker.write("P1000003", pixels, MORNING)
    finder = PhotoFinder()
    photos = finder.find([source])
    edit_file = typical_edit(tmp_path)
    renderer = StandInRenderer()
    reader = make_reader(tmp_path)
    developer = PhotoDeveloper(reader, renderer)
    refiner = Refiner()
    exporter = Exporter(reader, developer, refiner)
    option = edit_option(edit_file)
    output = tmp_path / "export"
    output_text = str(output)
    settings = ExportSettings(output_text, 320, 95, True)
    result = exporter.export(photos[0], option, [], settings)
    assert result.status is ExportStatus.WRITTEN
    assert result.message == Exporter.EDIT_LEFT_OUT


def test_pipeline_keeps_its_darktable_edit(tmp_path: Path) -> None:
    """The edit file survives the manifest and the brighter copy, and shows in the description."""
    catalog = StepCatalog()
    edit_file = tmp_path / "P1188493.RW2.xmp"
    option = edit_option(edit_file)
    brighter = ExposureStep(0.3)
    longer = option.extended("darktable-1~brighter", "darktable edit, a little brighter", [brighter])
    data = longer.to_data()
    loaded = RefinementPipeline.from_data(data, catalog)
    assert loaded.darktable_edit == edit_file
    assert loaded.source is PipelineSource.DARKTABLE
    assert loaded.describe_steps() == "darktable edit P1188493.RW2.xmp, Exposure +0.3 EV"
