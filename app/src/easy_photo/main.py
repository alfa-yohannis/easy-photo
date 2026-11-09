"""The function that starts the easy-photo window, or adds the app to the applications menu."""

import sys

from PySide6.QtWidgets import QApplication

from easy_photo.gui.application import EasyPhotoApp
from easy_photo.gui.desktop_entry import DesktopEntryInstaller

INSTALL_OPTION = "--install-launcher"
"""Adds easy-photo to the applications menu and puts a shortcut on the desktop (Linux)."""

REMOVE_OPTION = "--remove-launcher"
"""Takes the launcher, the desktop shortcut and the icons away again."""


def main() -> int:
    """Start the app and wait until its window is closed, or install or remove the launcher.

    Returns:
        The exit code: 0 after a normal close, or after the launcher was installed or removed.
    """
    first_options = sys.argv[1:2]
    if first_options in ([INSTALL_OPTION], [REMOVE_OPTION]):
        return change_launcher(first_options[0])
    app = EasyPhotoApp(sys.argv)
    return app.run()


def change_launcher(option: str) -> int:
    """Add easy-photo to the applications menu and the desktop, or take it away, and list the files.

    Args:
        option: :data:`INSTALL_OPTION` or :data:`REMOVE_OPTION`.

    Returns:
        0 when it worked, 1 when it could not be done.
    """
    if not sys.platform.startswith("linux"):
        print("The launcher can only be installed on Linux so far.", file=sys.stderr)
        return 1
    # Drawing the PNG icons needs a Qt application, but no screen.
    application = QApplication(["easy-photo", "-platform", "offscreen"])
    installer = DesktopEntryInstaller.for_this_user()
    try:
        if option == INSTALL_OPTION:
            paths = installer.install()
            verb = "Wrote"
        else:
            paths = installer.remove()
            verb = "Removed"
    except OSError as error:
        print(f"The launcher could not be changed: {error}", file=sys.stderr)
        return 1
    for path in paths:
        print(f"{verb} {path}")
    application.quit()
    return 0
