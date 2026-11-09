"""Tests of the previews darktable develops with the photos' sidecars, and of keeping them.

darktable-cli is replaced by a stand-in that returns a mid-grey picture, so
these tests run on computers without darktable.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from easy_photo.model.photo import FileKind, Photo
from easy_photo.services.thumbnails import DevelopedThumbnails
from tests.test_darktable import StandInRenderer


class SidecarWritingRenderer(StandInRenderer):
    """A stand-in for darktable-cli during whose work the photo's sidecar changes, as when darktable saves an edit."""

    def render(self, source: Path, edit_text: str | None, max_side: int, high_quality: bool = True) -> np.ndarray:
        """Write the photo's sidecar, then return the stand-in's picture.

        Args:
            source: The raw file.
            edit_text: The edit's XMP text, or None.
            max_side: Longest side of the result.
            high_quality: Develop at full size and shrink at the end.

        Returns:
            The stand-in's mid-grey picture.
        """
        sidecar = source.with_name(f"{source.name}.xmp")
        sidecar.write_text("<x:xmpmeta/>", encoding="utf-8")
        return super().render(source, edit_text, max_side, high_quality)


def make_photo(folder: Path, name: str) -> Photo:
    """Write a stand-in photo file.

    Args:
        folder: Where the file goes.
        name: Its name, such as "P1000001.RW2".

    Returns:
        The photo.
    """
    path = folder / name
    path.write_bytes(b"photo")
    kind = FileKind.of(path)
    return Photo(path, kind)


def test_a_developed_picture_is_kept_until_the_sidecar_changes(tmp_path: Path) -> None:
    """The picture is developed once and found again; a changed sidecar needs a new one, and only the newest stays."""
    renderer = StandInRenderer()
    cache = tmp_path / "cache"
    thumbnails = DevelopedThumbnails(renderer, cache)
    photo = make_photo(tmp_path, "P1000001.RW2")
    before = thumbnails.kept(photo)
    first = thumbnails.develop(photo)
    kept = thumbnails.kept(photo)
    second = thumbnails.develop(photo)
    requests_before_edit = len(renderer.requests)
    sidecar = photo.path.with_name("P1000001.RW2.xmp")
    sidecar.write_text("<x:xmpmeta/>", encoding="utf-8")
    after_edit = thumbnails.kept(photo)
    thumbnails.develop(photo)
    found = cache.glob("*.jpg")
    files = list(found)
    first_level = int(first[0, 0, 0])
    kept_level = int(kept[100, 100, 1])
    assert before is None
    assert first.dtype == np.uint8
    assert first.shape == (213, 320, 3)
    assert first_level == 128
    assert abs(kept_level - 128) <= 2
    assert second.shape == first.shape
    assert requests_before_edit == 1
    assert renderer.requests[0] == (photo.path, None, 320, False)
    assert after_edit is None
    assert len(renderer.requests) == 2
    assert len(files) == 1


def test_a_picture_made_while_the_sidecar_changed_is_not_kept(tmp_path: Path) -> None:
    """When the sidecar changes while darktable works, the picture is shown but not kept, since it may show the old edit."""
    renderer = SidecarWritingRenderer()
    cache = tmp_path / "cache"
    thumbnails = DevelopedThumbnails(renderer, cache)
    photo = make_photo(tmp_path, "P1000001.RW2")
    pixels = thumbnails.develop(photo)
    kept = thumbnails.kept(photo)
    found = cache.glob("*.jpg")
    files = list(found)
    assert pixels.shape == (213, 320, 3)
    assert kept is None
    assert files == []


def test_other_image_files_have_no_developed_picture(tmp_path: Path) -> None:
    """A JPEG file already shows what it holds, so no developed picture is looked for."""
    renderer = StandInRenderer()
    cache = tmp_path / "cache"
    thumbnails = DevelopedThumbnails(renderer, cache)
    photo = make_photo(tmp_path, "P1000004.jpg")
    assert thumbnails.kept(photo) is None
