"""The panel of the Filter step that shows one photo large, with its check results."""

from __future__ import annotations

import html

from PySide6.QtCore import Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from easy_photo.gui.file_locations import FileLocations
from easy_photo.gui.style import AppStyle
from easy_photo.gui.widgets.image_view import ImageView
from easy_photo.model.photo import Photo
from easy_photo.model.quality import Decision, Problem, QualityResult


class PhotoInspector(QFrame):
    """Shows one photo large, its camera details, the result of each check, and the decision buttons."""

    keep_clicked = Signal()
    set_aside_clicked = Signal()
    reset_clicked = Signal()

    VALUE_FORMATS = {
        Problem.BLURRED: "{:.0f}",
        Problem.UNCLEAR: "{:.3f}",
        Problem.TOO_DARK: "{:.2f}",
        Problem.TOO_BRIGHT: "{:.0%}",
    }
    """How each check's value and limit are written."""

    MEASURE_NAMES = {
        Problem.BLURRED: "Sharpness",
        Problem.UNCLEAR: "Detail",
        Problem.TOO_DARK: "Brightest tones",
        Problem.TOO_BRIGHT: "Blown out",
    }

    def __init__(self, style: AppStyle, parent: QWidget | None = None) -> None:
        """Create the panel.

        Args:
            style: Gives the theme colors.
            parent: Qt parent widget.
        """
        super().__init__(parent)
        self.setObjectName("Inspector")
        self._style = style
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self._view = ImageView(style, "Select a photo", self)
        self._view.setMinimumHeight(280)
        self._name = QLabel("")
        self._name.setObjectName("CardTitle")
        self._details = QLabel("")
        self._details.setObjectName("Muted")
        self._details.setWordWrap(True)
        self._checks = QLabel("")
        self._checks.setWordWrap(True)
        self._decision = QLabel("")
        self._decision.setWordWrap(True)
        keep_button = QPushButton("Keep   (K)")
        keep_button.clicked.connect(self.keep_clicked)
        aside_button = QPushButton("Set aside   (X)")
        aside_button.clicked.connect(self.set_aside_clicked)
        reset_button = QPushButton("Undo my choice   (U)")
        reset_button.clicked.connect(self.reset_clicked)
        buttons = QHBoxLayout()
        buttons.addWidget(keep_button)
        buttons.addWidget(aside_button)
        self._photo: Photo | None = None
        self._locations = FileLocations()
        self._open_button = QPushButton("Open the file")
        self._open_button.clicked.connect(self._open_file)
        self._show_button = QPushButton("Show in folder")
        self._show_button.clicked.connect(self._show_in_folder)
        file_buttons = QHBoxLayout()
        file_buttons.addWidget(self._open_button)
        file_buttons.addWidget(self._show_button)
        file_buttons.addStretch(1)
        self._set_file_buttons_enabled(False)
        layout.addWidget(self._view, 1)
        layout.addWidget(self._name)
        layout.addLayout(file_buttons)
        layout.addWidget(self._details)
        layout.addWidget(self._checks)
        layout.addWidget(self._decision)
        layout.addLayout(buttons)
        layout.addWidget(reset_button)

    def show_photo(self, photo: Photo | None, result: QualityResult | None, decision: Decision | None, by_user: bool) -> None:
        """Show a photo's details and check results.

        Args:
            photo: The photo, or None to show nothing.
            result: Its check results, or None while it is being measured.
            decision: The decision that counts.
            by_user: True when the decision is the user's own.
        """
        self._photo = photo
        self._set_file_buttons_enabled(photo is not None)
        if photo is None:
            self._name.setText("")
            self._details.setText("")
            self._checks.setText("")
            self._decision.setText("")
            self._view.set_image(None)
            return
        self._name.setText(photo.name)
        details = self._details_text(photo)
        self._details.setText(details)
        checks = self._checks_html(result)
        self._checks.setText(checks)
        decision_text = self._decision_html(decision, by_user)
        self._decision.setText(decision_text)

    def set_image(self, image: QImage | None) -> None:
        """Show the photo's picture.

        Args:
            image: The picture, or None.
        """
        self._view.set_image(image)

    def _set_file_buttons_enabled(self, enabled: bool) -> None:
        """Switch the "Open the file" and "Show in folder" buttons on or off.

        Args:
            enabled: True while a photo is shown.
        """
        self._open_button.setEnabled(enabled)
        self._show_button.setEnabled(enabled)

    def _open_file(self) -> None:
        """Open the shown photo's file with the program the system uses for it."""
        if self._photo is not None:
            self._locations.open_file(self._photo.path)

    def _show_in_folder(self) -> None:
        """Show the shown photo in its folder in the file manager."""
        if self._photo is not None:
            self._locations.show_in_folder(self._photo.path)

    def _details_text(self, photo: Photo) -> str:
        """The camera details line.

        Args:
            photo: The photo.

        Returns:
            Text with the time, the camera and the exposure.
        """
        parts: list[str] = []
        taken_at = photo.info.taken_at
        if taken_at is not None:
            time_text = taken_at.strftime("%d %b %Y, %H:%M:%S")
            parts.append(time_text)
        if photo.info.camera:
            parts.append(photo.info.camera)
        exposure = photo.info.exposure_text()
        if exposure:
            parts.append(exposure)
        return "\n".join(parts)

    def _checks_html(self, result: QualityResult | None) -> str:
        """A small table of the checks: what was measured, the limit, and the outcome.

        Args:
            result: The check results, or None.

        Returns:
            Rich text for the label.
        """
        if result is None:
            return "Measuring…"
        rows: list[str] = []
        for check in result.checks:
            value_format = self.VALUE_FORMATS[check.problem]
            value = value_format.format(check.value)
            limit = value_format.format(check.limit)
            measure = self.MEASURE_NAMES[check.problem]
            color_name = self._color_name(check.decision)
            color = self._style.color(color_name)
            color_text = color.name()
            outcome = html.escape(check.decision.value)
            rows.append(
                f"<tr><td>{measure}</td><td align='right'>&nbsp;{value}</td>"
                f"<td align='right'>&nbsp;limit {limit}</td>"
                f"<td>&nbsp;<span style='color:{color_text}'>{outcome}</span></td></tr>"
            )
        body = "".join(rows)
        return f"<table cellspacing='2'>{body}</table>"

    def _decision_html(self, decision: Decision | None, by_user: bool) -> str:
        """The line that says what happens to the photo.

        Args:
            decision: The decision that counts.
            by_user: True when it is the user's own.

        Returns:
            Rich text for the label.
        """
        if decision is None:
            return ""
        color_name = self._color_name(decision)
        color = self._style.color(color_name)
        color_text = color.name()
        who = "your choice" if by_user else "the app's suggestion"
        return f"<b style='color:{color_text}'>{decision.value}</b> &nbsp;({who})"

    def _color_name(self, decision: Decision) -> str:
        """The theme color of a decision.

        Args:
            decision: The decision.

        Returns:
            "keep", "unsure" or "set_aside".
        """
        names = {Decision.KEEP: "keep", Decision.UNSURE: "unsure", Decision.SET_ASIDE: "set_aside"}
        return names[decision]
