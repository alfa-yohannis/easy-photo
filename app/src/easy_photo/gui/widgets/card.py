"""A framed panel with a title and a hint."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class Card(QFrame):
    """A framed panel with a title and a hint, with room for its own widgets below."""

    def __init__(self, title: str, hint: str, parent: QWidget | None = None) -> None:
        """Create the card.

        Args:
            title: The title.
            hint: One or two sentences under the title.
            parent: Qt parent widget.
        """
        super().__init__(parent)
        self.setObjectName("Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 14, 16, 14)
        self._layout.setSpacing(8)
        title_label = QLabel(title)
        title_label.setObjectName("CardTitle")
        hint_label = QLabel(hint)
        hint_label.setObjectName("Muted")
        hint_label.setWordWrap(True)
        self._layout.addWidget(title_label)
        self._layout.addWidget(hint_label)

    @property
    def body(self) -> QVBoxLayout:
        """The layout to add the card's own widgets to."""
        return self._layout
