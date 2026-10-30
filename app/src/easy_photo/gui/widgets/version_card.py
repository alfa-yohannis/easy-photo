"""One version of a group's sample photo, as shown in the Refine step."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from easy_photo.gui.controller import VersionPreview
from easy_photo.gui.style import AppStyle
from easy_photo.gui.widgets.image_view import ImageView


class VersionCard(QFrame):
    """One refined version of a sample photo: the picture, its name, what it changes, and a Pick button."""

    picked = Signal(str)

    def __init__(self, preview: VersionPreview, number: int, style: AppStyle, parent: QWidget | None = None) -> None:
        """Create the card.

        Args:
            preview: The version.
            number: Its number on the page; pressing that key picks it.
            style: Gives the theme colors.
            parent: Qt parent widget.
        """
        super().__init__(parent)
        self.setObjectName("VersionCard")
        self._style = style
        self._pipeline_id = preview.pipeline_id
        self._pick_text = f"Pick   ({number})"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        self._view = ImageView(style, "", self)
        self._view.setMinimumHeight(250)
        self._view.set_image(preview.image)
        title = QLabel(f"{number}.  {preview.name}")
        title.setObjectName("CardTitle")
        title.setWordWrap(True)
        description = QLabel(preview.description)
        description.setObjectName("Muted")
        description.setWordWrap(True)
        self._button = QPushButton(self._pick_text)
        self._button.clicked.connect(self._on_pick)
        layout.addWidget(self._view, 1)
        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(self._button)

    @property
    def pipeline_id(self) -> str:
        """Id of the option this card shows."""
        return self._pipeline_id

    def set_selected(self, selected: bool) -> None:
        """Show whether this version is the group's pick.

        Args:
            selected: True when it is picked.
        """
        self.setProperty("selected", selected)
        self._button.setProperty("primary", selected)
        text = "Picked" if selected else self._pick_text
        self._button.setText(text)
        self._style.refresh(self)
        self._style.refresh(self._button)

    def _on_pick(self) -> None:
        """Tell the page that this version was picked."""
        self.picked.emit(self._pipeline_id)
