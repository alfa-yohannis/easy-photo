"""The function that starts the easy-photo window."""

import sys

from easy_photo.gui.application import EasyPhotoApp


def main() -> int:
    """Start the app and wait until its window is closed.

    Returns:
        The exit code of the Qt event loop, 0 after a normal close.
    """
    app = EasyPhotoApp(sys.argv)
    return app.run()
