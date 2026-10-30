"""A grid of photo tiles."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QModelIndex, QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListView,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from easy_photo.gui.file_locations import FileLocations
from easy_photo.gui.photo_model import PhotoListModel
from easy_photo.gui.style import AppStyle
from easy_photo.model.quality import Decision


class PhotoTileDelegate(QStyledItemDelegate):
    """Draws one photo tile: the thumbnail, a badge with the filter decision, and two lines of text."""

    PADDING = 6
    TEXT_HEIGHT = 40
    BADGE_SIZE = 22
    IMAGE_SHARE = 0.72
    """Height of the picture area as a share of the tile width."""

    BADGE_TEXT = {Decision.KEEP: "✓", Decision.UNSURE: "?", Decision.SET_ASIDE: "✕"}
    BADGE_COLOR = {Decision.KEEP: "keep", Decision.UNSURE: "unsure", Decision.SET_ASIDE: "set_aside"}

    def __init__(self, style: AppStyle, parent: QWidget | None = None) -> None:
        """Create the delegate.

        Args:
            style: Gives the theme colors.
            parent: Qt parent object.
        """
        super().__init__(parent)
        self._style = style
        self._tile_width = 210
        self._show_badges = True

    def set_tile_width(self, width: int) -> None:
        """Change the width of the tiles.

        Args:
            width: Width in pixels.
        """
        self._tile_width = width

    def set_show_badges(self, show: bool) -> None:
        """Show or hide the decision badges.

        Args:
            show: True to show them.
        """
        self._show_badges = show

    def tile_size(self) -> QSize:
        """The size of one tile.

        Returns:
            Width and height in pixels.
        """
        image_height = round(self._tile_width * self.IMAGE_SHARE)
        height = image_height + self.TEXT_HEIGHT + 2 * self.PADDING
        return QSize(self._tile_width, height)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        """Tell Qt the size of a tile.

        Args:
            option: Drawing options (not used).
            index: Which photo (not used; all tiles have the same size).

        Returns:
            The tile size.
        """
        return self.tile_size()

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        """Draw one tile.

        Args:
            painter: Draws on the grid.
            option: Where to draw, and whether the tile is selected.
            index: Which photo.
        """
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        tile = option.rect.adjusted(3, 3, -3, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        self._paint_background(painter, tile, selected)
        image_area = self._image_area(tile)
        image = index.data(Qt.ItemDataRole.DecorationRole)
        self._paint_image(painter, image_area, image)
        decision = index.data(PhotoListModel.DECISION_ROLE)
        if self._show_badges and decision is not None:
            self._paint_badge(painter, image_area, decision)
        name = index.data(Qt.ItemDataRole.DisplayRole) or ""
        summary = index.data(PhotoListModel.SUMMARY_ROLE) or ""
        self._paint_text(painter, tile, image_area, name, summary)
        painter.restore()

    def _paint_background(self, painter: QPainter, tile: QRect, selected: bool) -> None:
        """Draw the rounded tile, highlighted when selected.

        Args:
            painter: The painter.
            tile: The tile's rectangle.
            selected: Whether the tile is selected.
        """
        outline = QRectF(tile)
        path = QPainterPath()
        path.addRoundedRect(outline, 8, 8)
        fill_name = "accent_soft" if selected else "tile"
        fill = self._style.color(fill_name)
        painter.fillPath(path, fill)
        if selected:
            accent = self._style.color("accent")
            pen = QPen(accent, 2)
            painter.setPen(pen)
            painter.drawPath(path)

    def _image_area(self, tile: QRect) -> QRect:
        """The part of the tile where the picture goes.

        Args:
            tile: The tile's rectangle.

        Returns:
            The picture area.
        """
        left = tile.left() + self.PADDING
        top = tile.top() + self.PADDING
        width = tile.width() - 2 * self.PADDING
        height = tile.height() - self.TEXT_HEIGHT - 2 * self.PADDING
        return QRect(left, top, width, height)

    def _paint_image(self, painter: QPainter, area: QRect, image: QImage | None) -> None:
        """Draw the thumbnail as large as fits, centered in the picture area.

        Args:
            painter: The painter.
            area: The picture area.
            image: The thumbnail, or None while the photo is being read.
        """
        background = self._style.color("image_back")
        painter.fillRect(area, background)
        if image is None or image.isNull():
            muted = self._style.color("muted")
            painter.setPen(muted)
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, "…")
            return
        area_width = area.width()
        area_height = area.height()
        image_width = image.width()
        image_height = image.height()
        scale = min(area_width / image_width, area_height / image_height)
        target_width = image_width * scale
        target_height = image_height * scale
        x = area.left() + (area_width - target_width) / 2
        y = area.top() + (area_height - target_height) / 2
        target = QRectF(x, y, target_width, target_height)
        painter.drawImage(target, image)

    def _paint_badge(self, painter: QPainter, area: QRect, decision: Decision) -> None:
        """Draw the round decision badge in the top right corner of the picture.

        Args:
            painter: The painter.
            area: The picture area.
            decision: The photo's filter decision.
        """
        size = self.BADGE_SIZE
        x = area.right() - size - 6
        y = area.top() + 6
        circle = QRectF(x, y, size, size)
        color_name = self.BADGE_COLOR[decision]
        color = self._style.color(color_name)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(circle)
        white = QColor("#FFFFFF")
        painter.setPen(white)
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        text = self.BADGE_TEXT[decision]
        painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_text(self, painter: QPainter, tile: QRect, area: QRect, name: str, summary: str) -> None:
        """Draw the file name and the summary line under the picture, shortened to fit.

        Args:
            painter: The painter.
            tile: The tile's rectangle.
            area: The picture area.
            name: The file name.
            summary: The check result or the user's decision.
        """
        left = tile.left() + self.PADDING
        width = tile.width() - 2 * self.PADDING
        name_top = area.bottom() + 4
        summary_top = name_top + 18
        name_rect = QRect(left, name_top, width, 18)
        summary_rect = QRect(left, summary_top, width, 18)
        font = painter.font()
        font.setBold(False)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        short_name = metrics.elidedText(name, Qt.TextElideMode.ElideMiddle, width)
        short_summary = metrics.elidedText(summary, Qt.TextElideMode.ElideRight, width)
        text_color = self._style.color("text")
        muted = self._style.color("muted")
        flags = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        painter.setPen(text_color)
        painter.drawText(name_rect, flags, short_name)
        painter.setPen(muted)
        painter.drawText(summary_rect, flags, short_summary)


class PhotoGrid(QListView):
    """A grid of photo tiles. One or more tiles can be selected.

    A right click on a tile offers to open the photo's file, or to show it in
    its folder in the file manager.
    """

    current_photo_changed = Signal(str)
    selection_changed = Signal()

    def __init__(self, model: PhotoListModel, style: AppStyle, parent: QWidget | None = None) -> None:
        """Create the grid.

        Args:
            model: The photos to show.
            style: Gives the theme colors.
            parent: Qt parent widget.
        """
        super().__init__(parent)
        self._model = model
        self.setModel(model)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setSpacing(4)
        self._delegate = PhotoTileDelegate(style, self)
        self.setItemDelegate(self._delegate)
        self.set_tile_width(210)
        selection = self.selectionModel()
        selection.currentChanged.connect(self._on_current_changed)
        selection.selectionChanged.connect(self._on_selection_changed)
        self._locations = FileLocations()
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_file_menu)

    def set_tile_width(self, width: int) -> None:
        """Change the size of the tiles.

        Args:
            width: Tile width in pixels.
        """
        self._delegate.set_tile_width(width)
        size = self._delegate.tile_size()
        self.setGridSize(size)
        viewport = self.viewport()
        viewport.update()

    def set_show_badges(self, show: bool) -> None:
        """Show or hide the decision badges.

        Args:
            show: True to show them.
        """
        self._delegate.set_show_badges(show)
        viewport = self.viewport()
        viewport.update()

    def current_photo_id(self) -> str | None:
        """The id of the photo with the keyboard focus.

        Returns:
            The id, or None when no tile is current.
        """
        index = self.currentIndex()
        if not index.isValid():
            return None
        return index.data(PhotoListModel.PHOTO_ID_ROLE)

    def selected_photo_ids(self) -> list[str]:
        """The ids of the selected photos.

        Returns:
            The ids, in grid order.
        """
        indexes = self.selectedIndexes()
        indexes.sort(key=self._row_of)
        return [index.data(PhotoListModel.PHOTO_ID_ROLE) for index in indexes]

    def select_row(self, row: int) -> None:
        """Make one tile current and selected, and scroll to it.

        Args:
            row: The row; it is moved into range when it is past the end.
        """
        count = self._model.rowCount()
        if count == 0:
            return
        last = count - 1
        chosen = min(row, last)
        index = self._model.index(chosen, 0)
        self.setCurrentIndex(index)
        self.scrollTo(index)

    def current_row(self) -> int:
        """The row of the current tile.

        Returns:
            The row, or -1 when no tile is current.
        """
        index = self.currentIndex()
        if not index.isValid():
            return -1
        return index.row()

    def _row_of(self, index: QModelIndex) -> int:
        """Sort key: the row of an index.

        Args:
            index: The index.

        Returns:
            Its row.
        """
        return index.row()

    def _on_current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        """Tell the page which photo is current now.

        Args:
            current: The new current index.
            _previous: The old one (not used).
        """
        photo_id = current.data(PhotoListModel.PHOTO_ID_ROLE) if current.isValid() else ""
        self.current_photo_changed.emit(photo_id or "")

    def _on_selection_changed(self, _selected: object, _deselected: object) -> None:
        """Tell the page that the selection changed.

        Args:
            _selected: Newly selected items (not used).
            _deselected: Newly unselected items (not used).
        """
        self.selection_changed.emit()

    def _show_file_menu(self, position: QPoint) -> None:
        """Offer to open the photo under the mouse, or to show it in its folder.

        Args:
            position: Where the user right-clicked, in the grid's own coordinates.
        """
        index = self.indexAt(position)
        if not index.isValid():
            return
        photo_id = index.data(PhotoListModel.PHOTO_ID_ROLE)
        path = Path(photo_id)
        menu = QMenu(self)
        open_action = menu.addAction("Open the file")
        show_action = menu.addAction("Show in folder")
        viewport = self.viewport()
        screen_position = viewport.mapToGlobal(position)
        chosen = menu.exec(screen_position)
        if chosen is open_action:
            self._locations.open_file(path)
        elif chosen is show_action:
            self._locations.show_in_folder(path)
