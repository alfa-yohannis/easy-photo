"""The base class of the workflow pages."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget

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

    def ask_group_name(self, group_id: str) -> None:
        """Ask the user for a new name of a group, and rename the group.

        Args:
            group_id: Id of the group; nothing happens when it is empty or unknown.
        """
        project = self._controller.project
        group = project.group(group_id) if project is not None and group_id else None
        if group is None:
            return
        name, accepted = QInputDialog.getText(
            self, "Rename group", "New name of the group:", QLineEdit.EchoMode.Normal, group.title
        )
        if accepted:
            self._controller.rename_group(group_id, name)

    def ask_to_remove_groups(self, group_ids: Sequence[str]) -> None:
        """Ask the user to confirm, then remove groups.

        Args:
            group_ids: Ids of the groups; unknown ids are left out.
        """
        project = self._controller.project
        if project is None:
            return
        groups = [project.group(group_id) for group_id in group_ids]
        known = [group for group in groups if group is not None]
        if not known:
            return
        count = len(known)
        if count == 1:
            question = f'Remove the group "{known[0].title}"?'
        else:
            question = f"Remove these {count} groups?"
        text = (
            f"{question}\n\nTheir photos stay in the project but are not exported. Their picks, and the "
            "references made only for them, are removed too. Make groups again to bring the photos back."
        )
        buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        answer = QMessageBox.question(self, "Remove groups", text, buttons, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        known_ids = [group.id for group in known]
        self._controller.remove_groups(known_ids)
