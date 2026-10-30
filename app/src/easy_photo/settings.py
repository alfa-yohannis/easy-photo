"""Settings: the app's own settings, the options of each project, and the app's folders.

The options of the filter, grouping and export steps belong to a project and
are saved in its manifest. The app's own settings (where the face models and
darktable-cli are, and the recent projects) are saved as JSON in the user's
config folder. :class:`AppFolders` uses ``platformdirs``, so the folders
follow each system's rules: ``~/.config``, ``~/.local/share`` and ``~/.cache``
on Ubuntu, and ``%LOCALAPPDATA%`` on Windows.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from platformdirs import PlatformDirs

from easy_photo import APP_NAME


@dataclass
class CheckSettings:
    """Limits for the quality checks of the filter step.

    Each limit has a margin. A photo whose value is past the limit is set
    aside. A photo whose value is within the margin before the limit is marked
    "unsure" and shown to the user, who decides.

    The defaults come from the 314 raw files of a Lumix S5 folder (2026-10-30):
    blurred shots of grass and food scored 23 to 34 on sharpness, while the
    softest good photos (shallow depth of field) scored 43 and up; normal
    photos never had less than 0.088 detail.
    """

    min_sharpness: float = 38.0
    """Lowest sharpness of the sharpest half of the photo (variance of the Laplacian)."""

    sharpness_margin: float = 12.0

    min_contrast: float = 0.05
    """Lowest contrast of the most detailed half of the photo (0 to 1)."""

    contrast_margin: float = 0.02

    min_highlight: float = 0.12
    """Lowest brightness the brightest 5 % of the pixels must reach (0 to 1)."""

    highlight_margin: float = 0.08

    max_blown_share: float = 0.40
    """Highest share of almost white pixels (0 to 1)."""

    blown_margin: float = 0.15


@dataclass
class GroupSettings:
    """Options for the grouping step."""

    by_people: bool = False
    """Group by the people in the photos instead of by similarity."""

    max_gap_minutes: float = 10.0
    """Longest pause between two neighbouring photos of the same group."""

    min_similarity: float = 0.55
    """How alike two neighbouring photos must look to share a group (0 to 1)."""


@dataclass
class ExportSettings:
    """Options for writing the finished photos."""

    output_folder: str = ""
    """Where the photos go; empty means the "export" folder inside the project folder."""

    long_side: int = 1920
    quality: int = 100
    copy_metadata: bool = True

    sharpen: bool = True
    """Sharpen a little after shrinking, to bring back the fine detail that shrinking softens."""


@dataclass
class AppSettings:
    """The app's own settings, shared by all projects."""

    models_folder: str = ""
    """Folder with the face model files. Empty means the app's own models folder."""

    darktable_cli: str = ""
    """Path of the darktable-cli program. Empty means look for it on the PATH."""

    recent_projects: list[str] = field(default_factory=list)
    """Manifest files of recently opened projects, the latest first."""

    ai_enabled: bool = True
    """Ask Claude to read the words the app's own phrases do not cover."""

    ai_api_key: str = ""
    """Anthropic API key. Empty means the key from the environment or from an ``ant auth login`` profile."""

    ai_model: str = "claude-opus-5-5"
    """The Claude model that reads the user's words."""

    MAX_RECENT = 8

    def remember_project(self, manifest: Path) -> None:
        """Put a project at the top of the recent projects.

        Args:
            manifest: The project's manifest file.
        """
        text = str(manifest)
        if text in self.recent_projects:
            self.recent_projects.remove(text)
        self.recent_projects.insert(0, text)
        del self.recent_projects[self.MAX_RECENT:]

    def forget_project(self, manifest: Path) -> None:
        """Remove a project from the recent projects, for example when its folder is gone.

        Args:
            manifest: The project's manifest file.
        """
        text = str(manifest)
        if text in self.recent_projects:
            self.recent_projects.remove(text)


def settings_from_dict(settings_class: type, data: object) -> object:
    """Make a settings dataclass from a dictionary, using only the keys it knows.

    Unknown keys are ignored and missing keys keep their defaults, so data
    written by an older or newer version of the app still loads.

    Args:
        settings_class: The dataclass to make, such as :class:`CheckSettings`.
        data: The dictionary read from a file.

    Returns:
        An instance of ``settings_class``.
    """
    if not isinstance(data, dict):
        return settings_class()
    known_names = {item.name for item in fields(settings_class)}
    known_values = {key: value for key, value in data.items() if key in known_names}
    return settings_class(**known_values)


class AppFolders:
    """Knows where the app keeps its settings, caches and downloaded files."""

    def __init__(self, root: Path | None = None) -> None:
        """Look up the standard folders for this user and this system.

        Args:
            root: Put all folders inside this folder instead, for example in tests.
        """
        self._dirs = PlatformDirs(APP_NAME, appauthor=False)
        self._root = root

    @property
    def config(self) -> Path:
        """Folder for the settings file."""
        if self._root is not None:
            return self._root / "config"
        return Path(self._dirs.user_config_dir)

    @property
    def data(self) -> Path:
        """Folder for lasting files, such as the history log and the face models."""
        if self._root is not None:
            return self._root / "data"
        return Path(self._dirs.user_data_dir)

    @property
    def cache(self) -> Path:
        """Folder for files that can be made again, such as raw previews."""
        if self._root is not None:
            return self._root / "cache"
        return Path(self._dirs.user_cache_dir)

    @property
    def default_models(self) -> Path:
        """Folder for the face model files when the user has not chosen one."""
        return self.data / "models"


class SettingsStore:
    """Loads and saves :class:`AppSettings` as a JSON file."""

    FILE_NAME = "settings.json"

    def __init__(self, folder: Path) -> None:
        """Remember where the settings file is.

        Args:
            folder: Folder that holds the settings file, or will hold it.
        """
        self._path = folder / self.FILE_NAME

    @property
    def path(self) -> Path:
        """Full path of the settings file."""
        return self._path

    def load(self) -> AppSettings:
        """Read the settings file, or return the defaults when there is none or it is broken.

        Returns:
            The settings.
        """
        if not self._path.exists():
            return AppSettings()
        text = self._path.read_text(encoding="utf-8")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return AppSettings()
        return settings_from_dict(AppSettings, data)

    def save(self, settings: AppSettings) -> None:
        """Write the settings file, creating its folder when needed.

        Args:
            settings: The settings to save.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(settings)
        text = json.dumps(data, indent=2)
        self._path.write_text(text, encoding="utf-8")
        try:
            # The file can hold an API key, so only its owner may read it (Windows ignores this).
            os.chmod(self._path, 0o600)
        except OSError:
            pass
