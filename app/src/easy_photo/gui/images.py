"""Turning numpy pixel arrays into Qt images."""

from __future__ import annotations

import numpy as np
from PySide6.QtGui import QImage


class ImageConverter:
    """Turns numpy RGB pixel arrays into Qt images.

    QImage objects may be made on worker threads, so background tasks can
    prepare pictures for the window. (QPixmap may only be made on the window
    thread, which is why the tasks hand over QImage objects.)
    """

    def to_qimage(self, pixels: np.ndarray) -> QImage:
        """Copy RGB pixels into a QImage.

        Args:
            pixels: RGB pixels, 8 bits per channel, shape (height, width, 3).

        Returns:
            A QImage that owns its own copy of the pixels.
        """
        contiguous = np.ascontiguousarray(pixels, dtype=np.uint8)
        height, width = contiguous.shape[:2]
        bytes_per_line = contiguous.strides[0]
        image = QImage(contiguous.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
        # The QImage only points at the array's memory; the copy owns its pixels after the array is gone.
        return image.copy()
