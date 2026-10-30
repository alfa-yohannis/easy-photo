"""Building refinement options from references.

There are four kinds of reference, one builder each: photos the user picked
before (their history), photos found on the internet, example files the user
selects now, and darktable edits (XMP sidecar files). Words the user types are
read by the controller, with the app's own phrases first and Claude after.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
from PIL import Image

from easy_photo.model.photo import Photo
from easy_photo.refinement.light import BrightnessMeter, LinearLight
from easy_photo.refinement.pipeline import PipelineSource, RefinementPipeline
from easy_photo.refinement.steps import MatchBrightnessStep
from easy_photo.refinement.targets import BrightnessTargets
from easy_photo.services.darktable import DarktableError, DarktableRenderer
from easy_photo.services.darktable_edit import DarktableEdit, DarktableEditError
from easy_photo.services.faces import FaceFinder
from easy_photo.services.photo_finder import PhotoFinder
from easy_photo.services.photo_reader import PhotoReader, PhotoReadError
from easy_photo.services.web_search import WebSearch, WebSearchError
from easy_photo.wording import count_text

ProgressReport = Callable[[int, int], None]
"""Called with (items done, items in total) while a builder works."""


class PipelineError(Exception):
    """Raised when a refinement option cannot be built, for example when no reference can be read."""


class BrightnessSamples:
    """Collects the key brightness of reference pictures and turns it into targets.

    For every picture it keeps the brightness of the whole picture and, when
    faces were found, of the faces. Faces are used when enough pictures have
    them, because people photos should be judged by their faces.
    """

    MIN_FACE_PICTURES = 3
    MIN_FACE_SHARE = 0.3

    def __init__(self) -> None:
        """Start with no samples."""
        self._photo_values: list[float] = []
        self._face_values: list[float] = []

    @property
    def count(self) -> int:
        """Number of pictures measured."""
        return len(self._photo_values)

    def add(self, photo_value: float, face_value: float | None) -> None:
        """Add the measurements of one picture.

        Args:
            photo_value: Brightness of the whole picture.
            face_value: Brightness of its faces, or None when it has none.
        """
        self._photo_values.append(photo_value)
        if face_value is not None:
            self._face_values.append(face_value)

    def targets(self) -> BrightnessTargets:
        """Turn the samples into brightness targets.

        Returns:
            The 25th, 50th, 75th and 90th percentiles of the faces, or of the
            whole pictures when too few pictures have faces.

        Raises:
            PipelineError: When no picture was measured.
        """
        if not self._photo_values:
            raise PipelineError("None of the reference pictures could be read.")
        face_count = len(self._face_values)
        enough_faces = face_count >= self.MIN_FACE_PICTURES
        enough_share = face_count >= self.MIN_FACE_SHARE * self.count
        uses_faces = enough_faces and enough_share
        values = self._face_values if uses_faces else self._photo_values
        low, typical, high, ceiling = np.percentile(values, [25, 50, 75, 90])
        low_value = float(low)
        typical_value = float(typical)
        high_value = float(high)
        ceiling_value = float(ceiling)
        return BrightnessTargets(low_value, typical_value, high_value, ceiling_value, uses_faces, self.count)


class ReferenceMeasurer:
    """Measures the brightness of reference pictures, with their faces when a face finder is there."""

    MEASURE_SIDE = 1280

    def __init__(self, reader: PhotoReader, face_finder: FaceFinder | None) -> None:
        """Create a measurer.

        Args:
            reader: Reads reference photos from files.
            face_finder: Finds faces in the references, or None to measure whole pictures only.
        """
        self._reader = reader
        self._face_finder = face_finder
        self._light = LinearLight()
        self._meter = BrightnessMeter()

    def set_face_finder(self, face_finder: FaceFinder | None) -> None:
        """Use another face finder, for example after the face models were downloaded.

        Args:
            face_finder: The new face finder, or None.
        """
        self._face_finder = face_finder

    def measure_photos(self, photos: Sequence[Photo], report: ProgressReport | None) -> BrightnessTargets:
        """Measure reference photos read from files. Photos that cannot be read are skipped.

        Args:
            photos: The reference photos.
            report: Called with (photos done, photos in total).

        Returns:
            Their brightness targets.

        Raises:
            PipelineError: When none of them could be read.
        """
        samples = BrightnessSamples()
        total = len(photos)
        for done, photo in enumerate(photos, start=1):
            try:
                pixels = self._reader.load_pixels(photo, self.MEASURE_SIDE)
            except PhotoReadError:
                continue
            self._add_sample(samples, photo.id, pixels)
            if report is not None:
                report(done, total)
        return samples.targets()

    def measure_pixels(self, pictures: Sequence[np.ndarray]) -> BrightnessTargets:
        """Measure reference pictures that are already in memory.

        Args:
            pictures: RGB pixels of each picture.

        Returns:
            Their brightness targets.

        Raises:
            PipelineError: When the list is empty.
        """
        samples = BrightnessSamples()
        for number, pixels in enumerate(pictures):
            self._add_sample(samples, f"reference-{number}", pixels)
        return samples.targets()

    def _add_sample(self, samples: BrightnessSamples, picture_id: str, pixels: np.ndarray) -> None:
        """Measure one picture and add it to the samples.

        Args:
            samples: Where the measurements go.
            picture_id: Id for the faces found in the picture.
            pixels: RGB pixels of the picture.
        """
        linear = self._light.to_linear(pixels)
        photo_value = self._meter.photo_brightness(linear)
        face_value = self._face_value(picture_id, pixels, linear)
        samples.add(photo_value, face_value)

    def _face_value(self, picture_id: str, pixels: np.ndarray, linear: np.ndarray) -> float | None:
        """Measure the faces of a picture.

        Args:
            picture_id: Id for the faces.
            pixels: RGB pixels, for the face finder.
            linear: The same picture in linear light, for measuring.

        Returns:
            The faces' brightness, or None without a face finder or faces.
        """
        if self._face_finder is None or not self._face_finder.available:
            return None
        faces = self._face_finder.find(picture_id, pixels)
        if not faces:
            return None
        height, width = pixels.shape[:2]
        boxes = [face.box.to_pixels(width, height) for face in faces]
        return self._meter.face_brightness(linear, boxes)


class PipelineBuilder(ABC):
    """Builds one refinement option from one kind of reference."""

    @abstractmethod
    def build(self, pipeline_id: str, report: ProgressReport | None) -> RefinementPipeline:
        """Build the option.

        Args:
            pipeline_id: Id for the new option.
            report: Called with (items done, items in total) while working.

        Returns:
            The new refinement option.

        Raises:
            PipelineError: When the option cannot be built.
        """


class HistoryPipelineBuilder(PipelineBuilder):
    """Learns the brightness the user likes from photos they picked before (folders or files)."""

    def __init__(self, sources: Sequence[Path], finder: PhotoFinder, measurer: ReferenceMeasurer) -> None:
        """Create the builder.

        Args:
            sources: Folders and files of photos the user picked before.
            finder: Finds the photos in the sources.
            measurer: Measures them.
        """
        self._sources = list(sources)
        self._finder = finder
        self._measurer = measurer

    def build(self, pipeline_id: str, report: ProgressReport | None) -> RefinementPipeline:
        """Measure the user's earlier picks and make an option that matches their brightness.

        Args:
            pipeline_id: Id for the new option.
            report: Called with (photos done, photos in total).

        Returns:
            The new option.

        Raises:
            PipelineError: When no photo is found or none can be read.
        """
        photos = self._finder.find(self._sources)
        if not photos:
            raise PipelineError("No photos were found in the chosen folders and files.")
        targets = self._measurer.measure_photos(photos, report)
        photos_text = count_text(targets.reference_count, "photo")
        step = MatchBrightnessStep(targets, "your history")
        names = [source.name for source in self._sources]
        joined = ", ".join(names)
        details = f"Learned from {photos_text} in {joined}"
        name = f"Your history ({photos_text})"
        return RefinementPipeline(pipeline_id, name, PipelineSource.HISTORY, [step], details)


class ExamplePipelineBuilder(PipelineBuilder):
    """Learns the brightness of example files the user selects now.

    A raw file is developed with darktable-cli when it is installed, with its
    own sidecar when it has one, so the user's edit is what gets measured, and
    the measuring starts from the same development as the export. Other files
    are measured as they are.
    """

    DEVELOP_SIDE = 1280

    def __init__(
        self,
        files: Sequence[Path],
        finder: PhotoFinder,
        reader: PhotoReader,
        measurer: ReferenceMeasurer,
        darktable: DarktableRenderer,
    ) -> None:
        """Create the builder.

        Args:
            files: The example files.
            finder: Turns the files into photos (and skips files the app cannot read).
            reader: Reads files that are not developed with darktable.
            measurer: Measures the examples.
            darktable: Develops raw files with their darktable edit, when installed.
        """
        self._files = list(files)
        self._finder = finder
        self._reader = reader
        self._measurer = measurer
        self._darktable = darktable
        self._light = LinearLight()

    def build(self, pipeline_id: str, report: ProgressReport | None) -> RefinementPipeline:
        """Measure the examples and make an option that matches their brightness.

        Args:
            pipeline_id: Id for the new option.
            report: Called with (files done, files in total).

        Returns:
            The new option.

        Raises:
            PipelineError: When no example can be read.
        """
        photos = self._finder.find(self._files)
        pictures: list[np.ndarray] = []
        developed = 0
        total = len(photos)
        for done, photo in enumerate(photos, start=1):
            pixels, was_developed = self._picture_of(photo)
            if pixels is not None:
                pictures.append(pixels)
            if was_developed:
                developed += 1
            if report is not None:
                report(done, total)
        if not pictures:
            raise PipelineError("None of the example files could be read.")
        targets = self._measurer.measure_pixels(pictures)
        count = len(pictures)
        files_text = count_text(count, "file")
        step = MatchBrightnessStep(targets, "your examples")
        names = [photo.name for photo in photos]
        joined = ", ".join(names)
        details = f"Learned from {joined}"
        if developed:
            details = f"{details}; {developed} developed with darktable"
        name = f"Examples ({files_text})"
        return RefinementPipeline(pipeline_id, name, PipelineSource.EXAMPLES, [step], details)

    def _picture_of(self, photo: Photo) -> tuple[np.ndarray | None, bool]:
        """Read one example, developing it with darktable when it is a raw file.

        Args:
            photo: The example.

        Returns:
            Its 8-bit pixels (None when it cannot be read) and whether darktable developed it.
        """
        if photo.is_raw and self._darktable.available:
            try:
                values = self._darktable.render(photo.path, None, self.DEVELOP_SIDE, False)
            except DarktableError:
                values = None
            if values is not None:
                pixels = self._light.to_8bit(values)
                return pixels, True
        try:
            pixels = self._reader.load_pixels(photo, self.DEVELOP_SIDE)
        except PhotoReadError:
            return None, False
        return pixels, False


class DarktableEditPipelineBuilder(PipelineBuilder):
    """Makes an option that applies a darktable edit, from an XMP sidecar file, to every raw photo.

    The edit itself is applied: darktable-cli develops each raw photo with it,
    module by module, the way darktable would after a copy and paste of the
    history. The parts that only fit the edited photo, such as its crop, are
    left out (see :class:`DarktableEdit`). The option refers to the file, so a
    later change to the edit in darktable is used by the next export.
    """

    def __init__(self, edit_file: Path, darktable: DarktableRenderer) -> None:
        """Create the builder.

        Args:
            edit_file: The XMP file, such as P1188493.RW2.xmp.
            darktable: Applies the edit; it must be installed.
        """
        self._edit_file = edit_file
        self._darktable = darktable

    def build(self, pipeline_id: str, report: ProgressReport | None) -> RefinementPipeline:
        """Check the edit and make an option that applies it.

        Args:
            pipeline_id: Id for the new option.
            report: Called once, with (1, 1), when the file was read.

        Returns:
            The new option.

        Raises:
            PipelineError: When darktable-cli is missing or the file holds no usable edit.
        """
        if not self._darktable.available:
            raise PipelineError(
                "darktable-cli was not found, so a darktable edit cannot be applied. "
                "Install darktable to use .xmp files."
            )
        try:
            edit = DarktableEdit.read(self._edit_file)
        except DarktableEditError as error:
            message = str(error)
            raise PipelineError(message) from error
        if report is not None:
            report(1, 1)
        modules = edit.describe()
        details = f"darktable-cli applies {self._edit_file}: {modules}"
        left_out = edit.describe_left_out()
        if left_out:
            details = f"{details}. Left out, since they only fit the edited photo: {left_out}"
        name = f"darktable edit: {self._edit_file.name}"
        return RefinementPipeline(pipeline_id, name, PipelineSource.DARKTABLE, [], details, self._edit_file)


class InternetPipelineBuilder(PipelineBuilder):
    """Learns the brightness of photos found on the internet for a search phrase."""

    def __init__(
        self,
        query: str,
        search: WebSearch,
        measurer: ReferenceMeasurer,
        download_folder: Path,
        limit: int = 12,
    ) -> None:
        """Create the builder.

        Args:
            query: What to search for, such as "Mount Fuji autumn".
            search: The search service.
            measurer: Measures the downloaded photos.
            download_folder: Where the downloaded photos are kept.
            limit: Most photos to download.
        """
        self._query = query
        self._search = search
        self._measurer = measurer
        self._download_folder = download_folder
        self._limit = limit

    def build(self, pipeline_id: str, report: ProgressReport | None) -> RefinementPipeline:
        """Search, download, measure, and make an option that matches the photos found.

        Args:
            pipeline_id: Id for the new option.
            report: Called with (photos done, photos in total).

        Returns:
            The new option.

        Raises:
            PipelineError: When nothing is found or nothing can be downloaded.
        """
        try:
            found = self._search.find_images(self._query, self._limit)
        except WebSearchError as error:
            raise PipelineError(f"The search did not work: {error}") from error
        if not found:
            raise PipelineError(f'Nothing was found for "{self._query}".')
        pictures: list[np.ndarray] = []
        total = len(found)
        for done, image in enumerate(found, start=1):
            pixels = self._download(image)
            if pixels is not None:
                pictures.append(pixels)
            if report is not None:
                report(done, total)
        if not pictures:
            raise PipelineError("None of the photos found could be downloaded.")
        targets = self._measurer.measure_pixels(pictures)
        count = len(pictures)
        photos_text = count_text(count, "photo")
        step = MatchBrightnessStep(targets, f'"{self._query}" photos')
        name = f'Internet: "{self._query}" ({photos_text})'
        details = f"From {self._search.name}"
        return RefinementPipeline(pipeline_id, name, PipelineSource.INTERNET, [step], details)

    def _download(self, image) -> np.ndarray | None:
        """Download one found photo and read its pixels.

        Args:
            image: The found photo.

        Returns:
            Its RGB pixels, or None when it cannot be downloaded or read.
        """
        try:
            path = self._search.download(image, self._download_folder)
            with Image.open(path) as opened:
                rgb_image = opened.convert("RGB")
        except (WebSearchError, OSError, ValueError):
            return None
        return np.array(rgb_image)
