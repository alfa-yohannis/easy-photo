"""Starts the app with ``python -m easy_photo``."""

from easy_photo.main import main

exit_code = main()
raise SystemExit(exit_code)
