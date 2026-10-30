"""Sliders for the limits of the quality checks."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

from easy_photo.settings import CheckSettings


class LimitSlider(QWidget):
    """One limit: its name, a slider and the current value.

    The slider works in whole steps; ``scale`` turns a step into the real value.
    """

    value_changed = Signal()

    def __init__(self, minimum: float, maximum: float, scale: float, value_format: str, parent: QWidget | None = None) -> None:
        """Create the slider.

        Args:
            minimum: Lowest value.
            maximum: Highest value.
            scale: Real value of one slider step.
            value_format: How to write the value, such as "{:.2f}".
            parent: Qt parent widget.
        """
        super().__init__(parent)
        self._scale = scale
        self._format = value_format
        self._slider = QSlider(Qt.Orientation.Horizontal, self)
        lowest = round(minimum / scale)
        highest = round(maximum / scale)
        self._slider.setRange(lowest, highest)
        self._slider.valueChanged.connect(self._on_moved)
        self._value_label = QLabel("")
        self._value_label.setMinimumWidth(52)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._slider, 1)
        layout.addWidget(self._value_label)

    def value(self) -> float:
        """The current value.

        Returns:
            The real value of the slider position.
        """
        steps = self._slider.value()
        return steps * self._scale

    def set_value(self, value: float) -> None:
        """Move the slider without announcing a change.

        Args:
            value: The real value.
        """
        steps = round(value / self._scale)
        self._slider.blockSignals(True)
        self._slider.setValue(steps)
        self._slider.blockSignals(False)
        self._show_value()

    def _on_moved(self, _steps: int) -> None:
        """Show the new value and announce the change.

        Args:
            _steps: The slider position (read again through :meth:`value`).
        """
        self._show_value()
        self.value_changed.emit()

    def _show_value(self) -> None:
        """Write the current value next to the slider."""
        value = self.value()
        text = self._format.format(value)
        self._value_label.setText(text)


class LimitsPanel(QFrame):
    """The four limits of the filter step, with a button that restores the defaults."""

    settings_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create the panel.

        Args:
            parent: Qt parent widget.
        """
        super().__init__(parent)
        self.setObjectName("Panel")
        self._settings = CheckSettings()
        self._sharpness = LimitSlider(0.0, 300.0, 1.0, "{:.0f}", self)
        self._contrast = LimitSlider(0.0, 0.2, 0.001, "{:.3f}", self)
        self._highlight = LimitSlider(0.0, 0.6, 0.01, "{:.2f}", self)
        self._blown = LimitSlider(0.05, 1.0, 0.01, "{:.0%}", self)
        rows = [
            ("Badly blurred below", "sharpness of the sharpest half", self._sharpness),
            ("No clear subject below", "detail of the most detailed half", self._contrast),
            ("Too dark below", "brightness of the brightest tones", self._highlight),
            ("Too bright above", "share of blown-out pixels", self._blown),
        ]
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        for row, (title, hint, slider) in enumerate(rows):
            title_label = QLabel(title)
            hint_label = QLabel(hint)
            hint_label.setObjectName("Muted")
            grid.addWidget(title_label, row, 0)
            grid.addWidget(hint_label, row, 1)
            grid.addWidget(slider, row, 2)
            slider.value_changed.connect(self.settings_changed)
        grid.setColumnStretch(2, 1)
        reset_button = QPushButton("Restore defaults")
        reset_button.clicked.connect(self._restore_defaults)
        bottom = QHBoxLayout()
        note = QLabel("Photos just inside a limit are marked unsure, so you decide.")
        note.setObjectName("Muted")
        bottom.addWidget(note, 1)
        bottom.addWidget(reset_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.addLayout(grid)
        layout.addLayout(bottom)

    def set_settings(self, settings: CheckSettings) -> None:
        """Show a project's limits without announcing a change.

        Args:
            settings: The limits.
        """
        self._settings = settings
        self._sharpness.set_value(settings.min_sharpness)
        self._contrast.set_value(settings.min_contrast)
        self._highlight.set_value(settings.min_highlight)
        self._blown.set_value(settings.max_blown_share)

    def settings(self) -> CheckSettings:
        """The limits set on the sliders; the margins stay as they were.

        Returns:
            The limits.
        """
        sharpness = self._sharpness.value()
        contrast = self._contrast.value()
        highlight = self._highlight.value()
        blown = self._blown.value()
        return replace(
            self._settings,
            min_sharpness=sharpness,
            min_contrast=contrast,
            min_highlight=highlight,
            max_blown_share=blown,
        )

    def _restore_defaults(self) -> None:
        """Put the default limits back and announce the change."""
        defaults = CheckSettings()
        self.set_settings(defaults)
        self.settings_changed.emit()
