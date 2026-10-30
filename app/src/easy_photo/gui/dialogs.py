"""Dialogs of the app."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from easy_photo.services.manifest import ProjectManifest
from easy_photo.settings import AppSettings


class AiSettingsDialog(QDialog):
    """Lets the user switch Claude on or off for reading typed refinements, and set the API key and model."""

    def __init__(self, settings: AppSettings, models: Sequence[tuple[str, str]], parent: QWidget | None = None) -> None:
        """Create the dialog with the current settings filled in.

        Args:
            settings: The app's settings.
            models: The models to offer, as (model id, name for the window).
            parent: Qt parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("AI for your own words")
        self.setMinimumWidth(580)
        self._enabled = QCheckBox("Let Claude read the words the app's own phrases do not cover")
        self._enabled.setChecked(settings.ai_enabled)
        self._key = QLineEdit(settings.ai_api_key)
        self._key.setEchoMode(QLineEdit.EchoMode.Password)
        self._key.setPlaceholderText("sk-ant-...   (empty: use ANTHROPIC_API_KEY or an ant login)")
        self._model = QComboBox()
        for model_id, name in models:
            self._model.addItem(name, model_id)
        index = self._model.findData(settings.ai_model)
        if index >= 0:
            self._model.setCurrentIndex(index)
        note = QLabel(
            "Only the words you type are sent to Anthropic, never your photos. You can get a key at "
            "console.anthropic.com. The key is kept in the app's settings file, which only you can read."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        form = QFormLayout()
        form.addRow("Model", self._model)
        form.addRow("API key", self._key)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self._enabled)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)

    @property
    def ai_enabled(self) -> bool:
        """Whether Claude may read typed words."""
        return self._enabled.isChecked()

    @property
    def api_key(self) -> str:
        """The API key typed in, without spaces around it."""
        text = self._key.text()
        return text.strip()

    @property
    def model(self) -> str:
        """The chosen model id."""
        return self._model.currentData()


class NewProjectDialog(QDialog):
    """Asks for the name of a new project and the folder to put it in.

    The project gets its own folder, named after the project, inside the
    chosen folder.
    """

    UNSAFE_CHARACTERS = re.compile(r'[<>:"/\\|?*]')
    """Characters that Windows does not allow in folder names."""

    def __init__(self, default_parent: Path, parent: QWidget | None = None) -> None:
        """Create the dialog.

        Args:
            default_parent: The folder suggested for new projects.
            parent: Qt parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("New project")
        self.setMinimumWidth(560)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("for example: Japan 2024")
        self._name_edit.textChanged.connect(self._update)
        parent_text = str(default_parent)
        self._parent_edit = QLineEdit(parent_text)
        self._parent_edit.textChanged.connect(self._update)
        browse_button = QPushButton("Browse…")
        browse_button.clicked.connect(self._browse)
        location = QHBoxLayout()
        location.addWidget(self._parent_edit, 1)
        location.addWidget(browse_button)
        form = QFormLayout()
        form.addRow("Name", self._name_edit)
        form.addRow("Put it in", location)
        self._result = QLabel("")
        self._result.setObjectName("Muted")
        self._result.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._result)
        layout.addWidget(buttons)
        self._update()

    @property
    def project_name(self) -> str:
        """The name the user typed, without spaces around it."""
        text = self._name_edit.text()
        return text.strip()

    @property
    def project_folder(self) -> Path:
        """The folder the new project gets."""
        parent_text = self._parent_edit.text()
        parent_folder = Path(parent_text)
        folder_name = self._folder_name(self.project_name)
        return parent_folder / folder_name

    def _update(self) -> None:
        """Show where the project goes, and allow OK only for a usable name and a free folder."""
        name = self.project_name
        if not name:
            self._result.setText("Type a name for the project.")
            self._ok_button.setEnabled(False)
            return
        folder = self.project_folder
        manifest = folder / ProjectManifest.FILE_NAME
        if manifest.exists():
            self._result.setText(f"{folder} already holds a project. Choose another name or open that project.")
            self._ok_button.setEnabled(False)
            return
        self._result.setText(f"The project folder will be {folder}")
        self._ok_button.setEnabled(True)

    def _browse(self) -> None:
        """Let the user pick the folder the project goes in."""
        start = self._parent_edit.text()
        folder = QFileDialog.getExistingDirectory(self, "Choose where the project goes", start)
        if folder:
            self._parent_edit.setText(folder)

    def _folder_name(self, name: str) -> str:
        """Turn a project name into a folder name that works on Windows and Ubuntu.

        Args:
            name: The project name.

        Returns:
            The name with unsafe characters replaced by "-".
        """
        safe = self.UNSAFE_CHARACTERS.sub("-", name)
        return safe.strip(" .")
