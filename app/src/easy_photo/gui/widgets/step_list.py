"""The sidebar with the workflow steps."""

from __future__ import annotations

from collections.abc import Sequence
from functools import partial

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from easy_photo import APP_NAME


class StepButton(QPushButton):
    """One step in the sidebar: its number (or a check mark when done), its name and a short status line."""

    def __init__(self, number: int, title: str, parent: QWidget | None = None) -> None:
        """Create the button.

        Args:
            number: Number of the step, from 1.
            title: Name of the step.
            parent: Qt parent widget.
        """
        super().__init__(parent)
        self.setObjectName("StepButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._number = number
        self._title = title
        self._status = ""
        self._done = False
        self._update_text()

    def set_status(self, text: str) -> None:
        """Change the status line, such as "332 photos".

        Args:
            text: The status line.
        """
        if text == self._status:
            return
        self._status = text
        self._update_text()

    def set_done(self, done: bool) -> None:
        """Show a check mark instead of the number when the step is done.

        Args:
            done: Whether the step is done.
        """
        if done == self._done:
            return
        self._done = done
        self._update_text()

    def _update_text(self) -> None:
        """Write the button's two lines."""
        mark = "✓" if self._done else f"{self._number}"
        first_line = f"{mark}   {self._title}"
        if self._status:
            self.setText(f"{first_line}\n      {self._status}")
        else:
            self.setText(first_line)


class StepList(QFrame):
    """The sidebar: the app name, the project name and the workflow steps."""

    step_clicked = Signal(int)

    WIDTH = 236

    def __init__(self, titles: Sequence[str], parent: QWidget | None = None) -> None:
        """Create the sidebar.

        Args:
            titles: Names of the steps, in order.
            parent: Qt parent widget.
        """
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(self.WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(4)
        app_title = QLabel(APP_NAME)
        app_title.setObjectName("AppTitle")
        self._project_label = QLabel("")
        self._project_label.setObjectName("ProjectName")
        self._project_label.setWordWrap(True)
        layout.addWidget(app_title)
        layout.addWidget(self._project_label)
        layout.addSpacing(16)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: list[StepButton] = []
        for number, title in enumerate(titles, start=1):
            button = StepButton(number, title, self)
            handler = partial(self._on_clicked, number - 1)
            button.clicked.connect(handler)
            self._group.addButton(button)
            layout.addWidget(button)
            self._buttons.append(button)
        layout.addStretch(1)

    def set_project_name(self, name: str) -> None:
        """Show the name of the open project.

        Args:
            name: The project name.
        """
        self._project_label.setText(name)

    def set_current(self, index: int) -> None:
        """Highlight the step that is shown.

        Args:
            index: Index of the step, from 0.
        """
        button = self._buttons[index]
        button.setChecked(True)

    def set_status(self, index: int, text: str) -> None:
        """Change the status line of a step.

        Args:
            index: Index of the step, from 0.
            text: The status line.
        """
        button = self._buttons[index]
        button.set_status(text)

    def set_done(self, index: int, done: bool) -> None:
        """Mark a step as done or not.

        Args:
            index: Index of the step, from 0.
            done: Whether the step is done.
        """
        button = self._buttons[index]
        button.set_done(done)

    def _on_clicked(self, index: int, _checked: bool = False) -> None:
        """Tell the window that a step was clicked.

        Args:
            index: Index of the step.
            _checked: The button's checked state (not used).
        """
        self.step_clicked.emit(index)
