"""The app's icon, which ships inside the package as an SVG file."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from PySide6.QtGui import QIcon


class AppIcon:
    """The easy-photo icon: two photo prints on a blue tile, drawn as a scalable SVG file.

    The windows and the About box show it, and the launcher installer copies
    it into the user's icon theme.
    """

    FILE_NAME = "easy-photo.svg"
    """The icon's file name in the package's resources folder."""

    @classmethod
    def path(cls) -> Path:
        """The icon's SVG file.

        Returns:
            Its path inside the installed package.
        """
        package_files = resources.files("easy_photo")
        icon_file = package_files / "resources" / cls.FILE_NAME
        icon_text = str(icon_file)
        return Path(icon_text)

    @classmethod
    def icon(cls) -> QIcon:
        """The icon for windows and dialogs; Qt draws it sharp at every size.

        Returns:
            The icon.
        """
        path = cls.path()
        path_text = str(path)
        return QIcon(path_text)
