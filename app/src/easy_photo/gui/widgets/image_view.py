"""A view that shows one picture, with zoom."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QImage, QMouseEvent, QPainter, QPixmap, QResizeEvent, QWheelEvent
from PySide6.QtWidgets import QFrame, QGraphicsPixmapItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView, QWidget

from easy_photo.gui.style import AppStyle


class ImageView(QGraphicsView):
    """Shows one picture fitted to the view.

    The mouse wheel zooms in and out, dragging moves the picture, and a double
    click fits it to the view again. Without a picture, a short message is shown.
    """

    ZOOM_STEP = 1.25

    def __init__(self, style: AppStyle, message: str = "", parent: QWidget | None = None) -> None:
        """Create the view.

        Args:
            style: Gives the theme colors.
            message: Text shown while there is no picture.
            parent: Qt parent widget.
        """
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._picture = QGraphicsPixmapItem()
        self._picture.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._scene.addItem(self._picture)
        self._message = QGraphicsSimpleTextItem(message)
        muted = style.color("muted")
        muted_brush = QBrush(muted)
        self._message.setBrush(muted_brush)
        self._scene.addItem(self._message)
        background = style.color("image_back")
        background_brush = QBrush(background)
        self.setBackgroundBrush(background_brush)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._fit = True
        self.set_image(None)

    def has_image(self) -> bool:
        """True when a picture is shown."""
        pixmap = self._picture.pixmap()
        return not pixmap.isNull()

    def set_message(self, text: str) -> None:
        """Change the text shown while there is no picture.

        Args:
            text: The message.
        """
        self._message.setText(text)
        if not self.has_image():
            self._show_message()

    def set_image(self, image: QImage | None) -> None:
        """Show a picture, fitted to the view.

        Args:
            image: The picture, or None to show the message instead.
        """
        if image is None or image.isNull():
            empty = QPixmap()
            self._picture.setPixmap(empty)
            self._show_message()
            return
        pixmap = QPixmap.fromImage(image)
        self._picture.setPixmap(pixmap)
        self._message.setVisible(False)
        bounds = self._picture.boundingRect()
        self._scene.setSceneRect(bounds)
        self._fit = True
        self._fit_picture()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Keep the picture fitted when the view changes size.

        Args:
            event: The resize event.
        """
        super().resizeEvent(event)
        if self._fit and self.has_image():
            self._fit_picture()

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Zoom in or out with the mouse wheel.

        Args:
            event: The wheel event.
        """
        if not self.has_image():
            return
        delta = event.angleDelta()
        factor = self.ZOOM_STEP if delta.y() > 0 else 1 / self.ZOOM_STEP
        self._fit = False
        self.scale(factor, factor)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Fit the picture to the view again.

        Args:
            event: The mouse event.
        """
        self._fit = True
        if self.has_image():
            self._fit_picture()

    def _fit_picture(self) -> None:
        """Scale the view so the whole picture is visible."""
        self.resetTransform()
        self.fitInView(self._picture, Qt.AspectRatioMode.KeepAspectRatio)

    def _show_message(self) -> None:
        """Show the message in the middle of the view at normal size."""
        self._message.setVisible(True)
        bounds = self._message.boundingRect()
        self._scene.setSceneRect(bounds)
        self.resetTransform()
        self.centerOn(self._message)
