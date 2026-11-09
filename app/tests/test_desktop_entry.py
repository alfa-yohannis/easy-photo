"""Tests of the app's icon, the launcher installer and the About box, run without a screen.

The installer writes into a test folder and does not ask the real desktop
to read its menus again.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QApplication

from easy_photo import APP_VERSION
from easy_photo.gui.about_dialog import AboutDialog
from easy_photo.gui.app_icon import AppIcon
from easy_photo.gui.application import EasyPhotoApp
from easy_photo.gui.desktop_entry import DesktopEntryInstaller
from easy_photo.settings import AppFolders


def make_installer(tmp_path: Path, program: Path) -> DesktopEntryInstaller:
    """An installer that writes into a test folder, with a desktop folder there, and leaves the real menus alone.

    Args:
        tmp_path: pytest's temporary folder for the test.
        program: The program the launcher starts.

    Returns:
        The installer.
    """
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    program_text = str(program)
    return DesktopEntryInstaller([program_text], tmp_path / "share", desktop, refresh_menus=False)


def test_install_adds_the_launcher_the_icons_and_the_desktop_shortcut(tmp_path: Path, qt_application: QApplication) -> None:
    """The launcher goes into the applications folder, the icons into the hicolor theme, and an executable copy onto the desktop.

    Args:
        tmp_path: pytest's temporary folder for the test.
        qt_application: Draws the PNG icons.
    """
    program = tmp_path / "my apps" / "easy-photo"
    installer = make_installer(tmp_path, program)
    written = installer.install()
    launcher = tmp_path / "share" / "applications" / "easy-photo.desktop"
    shortcut = tmp_path / "Desktop" / "easy-photo.desktop"
    svg = tmp_path / "share" / "icons" / "hicolor" / "scalable" / "apps" / "easy-photo.svg"
    png = tmp_path / "share" / "icons" / "hicolor" / "48x48" / "apps" / "easy-photo.png"
    text = launcher.read_text(encoding="utf-8")
    lines = text.splitlines()
    shortcut_text = shortcut.read_text(encoding="utf-8")
    shortcut_status = shortcut.stat()
    source = AppIcon.path()
    png_text = str(png)
    picture = QImage(png_text)
    corner = picture.pixelColor(0, 0)
    middle = picture.pixelColor(24, 24)
    assert f'Exec="{program}"' in lines
    assert "Icon=easy-photo" in lines
    assert "StartupWMClass=easy-photo" in lines
    assert "Categories=Graphics;Photography;" in lines
    assert shortcut_text == text
    assert shortcut_status.st_mode & 0o111
    assert svg.read_bytes() == source.read_bytes()
    assert picture.width() == 48
    assert corner.alpha() == 0
    assert middle.alpha() == 255
    assert len(written) == 12


def test_remove_takes_away_what_install_wrote(tmp_path: Path, qt_application: QApplication) -> None:
    """Removing deletes the launcher, the desktop shortcut and every icon, and nothing else.

    Args:
        tmp_path: pytest's temporary folder for the test.
        qt_application: Draws the PNG icons.
    """
    program = tmp_path / "easy-photo"
    installer = make_installer(tmp_path, program)
    written = installer.install()
    removed = installer.remove()
    left = [path for path in written if path.exists()]
    written.sort()
    removed.sort()
    assert removed == written
    assert left == []


def test_the_command_is_quoted_the_way_desktop_entries_need(tmp_path: Path) -> None:
    """A plain path stays as it is; spaces, dollar signs, quotes, backslashes and percent signs are escaped.

    Args:
        tmp_path: pytest's temporary folder for the test.
    """
    command = ["/opt/easy-photo/bin/easy-photo", r'/a b/$x"y\z%', "-m"]
    installer = DesktopEntryInstaller(command, tmp_path, None, refresh_menus=False)
    text = installer.entry_text()
    lines = text.splitlines()
    assert r'Exec=/opt/easy-photo/bin/easy-photo "/a b/\\$x\\"y\\\\z%%" -m' in lines
    assert installer.shortcut_path is None


def test_the_about_box_names_the_version_the_programs_and_the_folders(tmp_path: Path, qt_application: QApplication) -> None:
    """The About box shows the version, the source link, darktable-cli and the cache folder; the app has its icon.

    Args:
        tmp_path: pytest's temporary folder for the test.
        qt_application: The Qt application the app runs in.
    """
    folders = AppFolders(tmp_path / "app")
    app = EasyPhotoApp(["easy-photo"], folders)
    dialog = AboutDialog(app.controller, folders, app.window)
    texts = dialog.label_texts()
    joined = "\n".join(texts)
    cache_text = str(folders.cache)
    window_icon = QGuiApplication.windowIcon()
    desktop_file = QGuiApplication.desktopFileName()
    app_icon = AppIcon.icon()
    assert f"Version {APP_VERSION}" in texts
    assert AboutDialog.REPOSITORY_URL in joined
    assert "darktable-cli: " in joined
    assert cache_text in joined
    assert not window_icon.isNull()
    assert not app_icon.isNull()
    assert desktop_file == "easy-photo"
