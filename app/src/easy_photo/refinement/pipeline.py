"""Refinement pipelines: named lists of refinement steps."""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum
from pathlib import Path

import numpy as np

from easy_photo.refinement.steps import RefinementStep, StepCatalog, StepContext


class PipelineSource(Enum):
    """Where a refinement pipeline came from."""

    CAMERA = "Camera"
    HISTORY = "Your history"
    INTERNET = "Internet"
    EXAMPLES = "Examples"
    WORDS = "Your words"
    DARKTABLE = "Your darktable edit"


class RefinementPipeline:
    """A named list of refinement steps that turns a photo into its refined version.

    A pipeline can also carry a darktable edit: an XMP sidecar file whose
    edit darktable-cli applies while it develops each raw photo. The steps
    then work on darktable's result.

    Pipelines do not change after they are made. :meth:`extended` gives a new
    pipeline with more steps, which is how the brighter and darker options and
    the user's typed changes are made.
    """

    CAMERA_ID = "camera"
    """Id of the option that changes nothing. Saved projects pick it under this id."""

    def __init__(
        self,
        pipeline_id: str,
        name: str,
        source: PipelineSource,
        steps: Sequence[RefinementStep] = (),
        details: str = "",
        darktable_edit: Path | None = None,
    ) -> None:
        """Create a pipeline.

        Args:
            pipeline_id: Unique id of the pipeline.
            name: Name shown in the window.
            source: Where the pipeline came from.
            steps: The steps, applied in this order.
            details: Extra text for the window, such as which references were used.
            darktable_edit: XMP file of a darktable edit to apply while developing raw photos, or None.
        """
        self._id = pipeline_id
        self._name = name
        self._source = source
        self._steps = tuple(steps)
        self._details = details
        self._darktable_edit = darktable_edit

    @classmethod
    def camera(cls) -> RefinementPipeline:
        """The pipeline that changes nothing: each photo as it is developed.

        Returns:
            The pipeline, with the id :attr:`CAMERA_ID`.
        """
        return cls(cls.CAMERA_ID, "Unchanged", PipelineSource.CAMERA, (), "Each photo as it is developed, unchanged")

    @property
    def id(self) -> str:
        """Unique id of the pipeline."""
        return self._id

    @property
    def name(self) -> str:
        """Name shown in the window."""
        return self._name

    @property
    def source(self) -> PipelineSource:
        """Where the pipeline came from."""
        return self._source

    @property
    def steps(self) -> tuple[RefinementStep, ...]:
        """The steps, in the order they are applied."""
        return self._steps

    @property
    def details(self) -> str:
        """Extra text for the window."""
        return self._details

    @property
    def darktable_edit(self) -> Path | None:
        """XMP file of the darktable edit applied while developing raw photos, or None."""
        return self._darktable_edit

    @property
    def is_camera(self) -> bool:
        """True for the pipeline that changes nothing."""
        return self._id == self.CAMERA_ID

    def describe_steps(self) -> str:
        """List the darktable edit and the steps as text.

        Returns:
            Text such as "darktable edit P1188493.RW2.xmp, Exposure +0.3 EV", or "No changes".
        """
        texts = [step.describe() for step in self._steps]
        if self._darktable_edit is not None:
            edit_text = f"darktable edit {self._darktable_edit.name}"
            texts.insert(0, edit_text)
        if not texts:
            return "No changes"
        return ", ".join(texts)

    def extended(
        self,
        pipeline_id: str,
        name: str,
        extra_steps: Sequence[RefinementStep],
        source: PipelineSource | None = None,
    ) -> RefinementPipeline:
        """Make a new pipeline with this pipeline's steps followed by more steps.

        Args:
            pipeline_id: Id of the new pipeline.
            name: Name of the new pipeline.
            extra_steps: Steps added after this pipeline's steps.
            source: Source of the new pipeline; this pipeline's source when not given.

        Returns:
            The new pipeline, with this pipeline's darktable edit. This pipeline does not change.
        """
        steps = list(self._steps)
        steps.extend(extra_steps)
        new_source = source or self._source
        return RefinementPipeline(pipeline_id, name, new_source, steps, self._details, self._darktable_edit)

    def apply(self, linear: np.ndarray, context: StepContext) -> np.ndarray:
        """Run all steps on a photo.

        Args:
            linear: RGB values in linear light.
            context: Face boxes and measuring tools for this photo.

        Returns:
            The refined values.
        """
        result = linear
        for step in self._steps:
            result = step.apply(result, context)
        return result

    def to_data(self) -> dict:
        """The pipeline as a dictionary for the project manifest.

        Returns:
            A dictionary that :meth:`from_data` reads back.
        """
        steps = [step.to_data() for step in self._steps]
        data = {
            "id": self._id,
            "name": self._name,
            "source": self._source.name,
            "details": self._details,
            "steps": steps,
        }
        if self._darktable_edit is not None:
            data["darktable_edit"] = str(self._darktable_edit)
        return data

    @classmethod
    def from_data(cls, data: dict, catalog: StepCatalog) -> RefinementPipeline:
        """Read a pipeline saved by :meth:`to_data`.

        Args:
            data: The saved dictionary.
            catalog: Turns the saved steps back into step objects.

        Returns:
            The pipeline.
        """
        source_name = data.get("source", PipelineSource.WORDS.name)
        source = PipelineSource[source_name]
        steps = [catalog.load(item) for item in data.get("steps", [])]
        details = data.get("details", "")
        edit_text = data.get("darktable_edit")
        darktable_edit = Path(edit_text) if edit_text else None
        return cls(data["id"], data["name"], source, steps, details, darktable_edit)
