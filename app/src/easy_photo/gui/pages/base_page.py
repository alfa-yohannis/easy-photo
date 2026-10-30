"""The base class of the workflow pages."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from easy_photo.gui.controller import ProjectController
from easy_photo.gui.style import AppStyle


class WorkflowPage(QWidget):
    """Base class of the six workflow pages.

    A page has a header with its title and a hint, and its own content below.
    Subclasses put their content in with :meth:`set_content`, say whether the
    user can go on with :meth:`is_ready`, and give the status line shown
    under their name in the sidebar with :meth:`status_text`. They send
    ``readiness_changed`` when either of those may have changed.
    """

    readiness_changed = Signal()

    def __init__(self, controller: ProjectController, style: AppStyle, title: str, hint: str, parent: QWidget | None = None) -> None:
        """Create the page with its header.

        Args:
            controller: Runs the work and holds the project.
            style: Gives the theme colors.
            title: The page title.
            hint: One or two sentences that explain the step.
            parent: Qt parent widget.
        """
        super().__init__(parent)
        self._controller = controller
        self._style = style
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(28, 22, 28, 12)
        self._outer.setSpacing(12)
        title_label = QLabel(title)
        title_label.setObjectName("PageTitle")
        hint_label = QLabel(hint)
        hint_label.setObjectName("PageHint")
        hint_label.setWordWrap(True)
        self._outer.addWidget(title_label)
        self._outer.addWidget(hint_label)

    def set_content(self, content: QWidget) -> None:
        """Put the page's own content under the header.

        Args:
            content: The content widget; it gets all the free space.
        """
        self._outer.addWidget(content, 1)

    def is_ready(self) -> bool:
        """Tell whether the user can go on to the next step.

        Returns:
            True by default; pages that need something done first override this.
        """
        return True

    def is_done(self) -> bool:
        """Tell whether the step is finished, which puts a check mark next to it in the sidebar.

        Returns:
            The same as :meth:`is_ready` by default; pages where "may go on" and
            "finished" differ override this.
        """
        return self.is_ready()

    def status_text(self) -> str:
        """The short status line shown under the step's name in the sidebar.

        Returns:
            The status line; empty by default.
        """
        return ""

    def on_shown(self) -> None:
        """Called each time the page becomes visible. Pages refresh what they show here."""

    def make_button(self, text: str, handler: Callable[[], None], primary: bool = False) -> QPushButton:
        """Make a push button that calls a function when clicked.

        Args:
            text: The button text.
            handler: Called on click.
            primary: Draw it as the page's main action.

        Returns:
            The button.
        """
        button = QPushButton(text)
        if primary:
            button.setProperty("primary", True)
        button.clicked.connect(handler)
        return button

    def make_label(self, text: str, object_name: str = "") -> QLabel:
        """Make a label, optionally with a style name such as "Muted" or "SectionTitle".

        Args:
            text: The label text.
            object_name: Name used by the style sheet.

        Returns:
            The label.
        """
        label = QLabel(text)
        if object_name:
            label.setObjectName(object_name)
        return label
