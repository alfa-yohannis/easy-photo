"""easy-photo, a desktop app that filters, groups and refines photos.

The package has four parts:

* ``easy_photo.model`` holds the data the app works on: photos, check
  results, groups, people and the user's choices.
* ``easy_photo.refinement`` holds the refinement steps (exposure, contrast,
  shadows and so on), the pipelines made of them, and the reader for
  refinement commands the user types.
* ``easy_photo.services`` does the work: finding and reading photos, checking
  their quality, finding faces, grouping, measuring references and exporting.
* ``easy_photo.gui`` is the PySide6 window that drives everything.

Only ``easy_photo.gui`` uses Qt, so the other parts can be tested and reused
without a window.
"""

APP_NAME = "easy-photo"
APP_VERSION = "0.1.0"
