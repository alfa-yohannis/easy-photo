"""Adding easy-photo to the applications menu and the desktop on Linux."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from platformdirs import user_desktop_dir
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from easy_photo import APP_NAME
from easy_photo.gui.app_icon import AppIcon


class DesktopEntryInstaller:
    """Adds easy-photo to the applications menu and puts a shortcut on the desktop, on Linux.

    It follows the freedesktop.org rules that KDE Plasma, GNOME and the
    other Linux desktops share. The icon goes into the user's hicolor icon
    theme, as the SVG file and as PNG files of the usual sizes. The launcher,
    a ``.desktop`` file, goes into the user's applications folder, and a copy
    of it goes onto the desktop, marked as executable so that Plasma starts
    the app from it without asking first. Only files in the user's home
    folder are written.
    """

    APP_ID = APP_NAME
    """The name of the launcher and of the icon. The app's window says it belongs to this launcher."""

    PNG_SIZES = (16, 22, 24, 32, 48, 64, 128, 256, 512)
    """Sizes of the PNG icons, for desktops and programs that do not draw SVG files."""

    RESERVED_CHARACTERS = frozenset(" \t\n\"'\\><~|&;$*?#()`")
    """Characters that make an argument of the launcher's command need quotes."""

    def __init__(self, command: Sequence[str], data_home: Path, desktop_folder: Path | None, refresh_menus: bool = True) -> None:
        """Create an installer.

        Args:
            command: The program that starts easy-photo, with its arguments.
            data_home: The user's data folder, usually ~/.local/share.
            desktop_folder: The user's desktop folder, or None to put no shortcut there.
            refresh_menus: Ask the desktop to read the applications folder again
                afterwards, so the menu shows the change at once.
        """
        self._command = list(command)
        self._data_home = data_home
        self._desktop_folder = desktop_folder
        self._refresh_menus_after = refresh_menus

    @classmethod
    def for_this_user(cls) -> DesktopEntryInstaller:
        """An installer for the user who runs the app, whose launcher starts the app the way it runs now.

        Returns:
            The installer.
        """
        command = cls.current_command()
        data_home = cls.user_data_home()
        desktop_text = user_desktop_dir()
        desktop_folder = Path(desktop_text)
        return cls(command, data_home, desktop_folder)

    @staticmethod
    def current_command() -> list[str]:
        """The command that starts the app the way it runs now.

        Returns:
            The easy-photo program next to the running Python, or else that
            Python with ``-m easy_photo``.
        """
        python = Path(sys.executable)
        program = python.with_name(APP_NAME)
        if program.exists():
            program_text = str(program)
            return [program_text]
        python_text = str(python)
        return [python_text, "-m", "easy_photo"]

    @staticmethod
    def user_data_home() -> Path:
        """The user's data folder.

        Returns:
            The folder named by XDG_DATA_HOME, or ~/.local/share.
        """
        configured = os.environ.get("XDG_DATA_HOME", "")
        if configured:
            return Path(configured)
        home = Path.home()
        return home / ".local" / "share"

    @property
    def launcher_path(self) -> Path:
        """The launcher in the user's applications folder, which the applications menu shows."""
        return self._data_home / "applications" / f"{self.APP_ID}.desktop"

    @property
    def shortcut_path(self) -> Path | None:
        """The launcher's copy on the desktop, or None without a desktop folder."""
        if self._desktop_folder is None:
            return None
        return self._desktop_folder / f"{self.APP_ID}.desktop"

    def icon_paths(self) -> list[Path]:
        """The icon files in the user's hicolor icon theme.

        Returns:
            The SVG file first, then one PNG file for each of :attr:`PNG_SIZES`.
        """
        hicolor = self._data_home / "icons" / "hicolor"
        paths = [hicolor / "scalable" / "apps" / f"{self.APP_ID}.svg"]
        for size in self.PNG_SIZES:
            paths.append(hicolor / f"{size}x{size}" / "apps" / f"{self.APP_ID}.png")
        return paths

    def entry_text(self) -> str:
        """The text of the launcher file.

        Returns:
            A desktop entry with the app's name, command, icon and categories.
        """
        exec_value = self._exec_value()
        lines = [
            "[Desktop Entry]",
            "Type=Application",
            "Version=1.5",
            f"Name={APP_NAME}",
            "GenericName=Photo culling and refinement",
            "Comment=Filter, group, refine and export photos, with darktable for raw files",
            f"Exec={exec_value}",
            f"Icon={self.APP_ID}",
            "Terminal=false",
            "Categories=Graphics;Photography;",
            "Keywords=photo;raw;darktable;cull;group;export;",
            "StartupNotify=true",
            f"StartupWMClass={self.APP_ID}",
        ]
        text = "\n".join(lines)
        return f"{text}\n"

    def install(self) -> list[Path]:
        """Install the icon and the launcher, and put the shortcut on the desktop.

        Files from an earlier install are written again. No shortcut is made
        when the desktop folder does not exist.

        Returns:
            The files written.
        """
        written = self._write_icons()
        launcher = self.launcher_path
        self._write_entry(launcher, False)
        written.append(launcher)
        shortcut = self.shortcut_path
        if shortcut is not None and shortcut.parent.is_dir():
            self._write_entry(shortcut, True)
            written.append(shortcut)
        if self._refresh_menus_after:
            self._refresh_menus()
        return written

    def remove(self) -> list[Path]:
        """Remove the launcher, the desktop shortcut and the icons that :meth:`install` writes.

        Returns:
            The files removed.
        """
        candidates = [self.launcher_path]
        shortcut = self.shortcut_path
        if shortcut is not None:
            candidates.append(shortcut)
        icons = self.icon_paths()
        candidates.extend(icons)
        removed: list[Path] = []
        for path in candidates:
            if path.exists():
                path.unlink()
                removed.append(path)
        if self._refresh_menus_after:
            self._refresh_menus()
        return removed

    def _write_icons(self) -> list[Path]:
        """Copy the SVG icon into the icon theme, and draw a PNG icon of each size from it.

        Returns:
            The icon files written.
        """
        source = AppIcon.path()
        paths = self.icon_paths()
        svg_target = paths[0]
        svg_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, svg_target)
        source_text = str(source)
        renderer = QSvgRenderer(source_text)
        png_targets = paths[1:]
        for size, target in zip(self.PNG_SIZES, png_targets, strict=True):
            image = self._render(renderer, size)
            target.parent.mkdir(parents=True, exist_ok=True)
            target_text = str(target)
            image.save(target_text)
        # A newer folder time tells the desktop's icon cache that the theme changed.
        hicolor = svg_target.parents[2]
        os.utime(hicolor)
        return paths

    def _render(self, renderer: QSvgRenderer, size: int) -> QImage:
        """Draw the icon at one size.

        Args:
            renderer: The SVG icon, read.
            size: Width and height in pixels.

        Returns:
            The picture, transparent around the tile.
        """
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(0, 0, size, size)
        renderer.render(painter, area)
        painter.end()
        return image

    def _write_entry(self, path: Path, executable: bool) -> None:
        """Write the launcher file.

        Args:
            path: Where to write it.
            executable: Mark it as executable, which a launcher on the desktop needs to start without a question.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        text = self.entry_text()
        path.write_text(text, encoding="utf-8")
        mode = 0o755 if executable else 0o644
        path.chmod(mode)

    def _exec_value(self) -> str:
        """The launcher's command line, with each argument quoted as desktop entries need.

        Returns:
            The value of the Exec key.
        """
        parts = [self._quoted(argument) for argument in self._command]
        return " ".join(parts)

    def _quoted(self, argument: str) -> str:
        """One argument of the launcher's command line, written the way the desktop entry rules ask.

        An argument with a space or another reserved character goes in
        double quotes, with the double quote, backtick, dollar sign and
        backslash escaped by a backslash. Then every backslash is doubled, as
        in any desktop entry text, and a percent sign becomes two, since a
        single one starts a field code.

        Args:
            argument: The argument.

        Returns:
            The argument as it goes into the Exec key.
        """
        needs_quotes = any(character in self.RESERVED_CHARACTERS for character in argument)
        written = argument
        if needs_quotes:
            for character in ("\\", '"', "`", "$"):
                written = written.replace(character, f"\\{character}")
            written = f'"{written}"'
        written = written.replace("\\", "\\\\")
        return written.replace("%", "%%")

    def _refresh_menus(self) -> None:
        """Ask the desktop to read the applications folder again; the programs that are not installed are passed over."""
        applications = self.launcher_path.parent
        applications_text = str(applications)
        commands = [["update-desktop-database", applications_text], ["kbuildsycoca6"], ["kbuildsycoca5"]]
        for command in commands:
            program = shutil.which(command[0])
            if program is None:
                continue
            arguments = command[1:]
            try:
                subprocess.run([program, *arguments], capture_output=True, timeout=120, check=False)
            except (OSError, subprocess.TimeoutExpired):
                continue
