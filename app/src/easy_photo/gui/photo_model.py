"""The list of photos behind a photo grid."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, Qt

from easy_photo.gui.controller import ProjectController


class PhotoListModel(QAbstractListModel):
    """The photos shown in one grid, with their thumbnails and filter decisions.

    The model only holds photo ids; everything else comes from the controller
    and the open project, so all grids show the same, current data.
    """

    PHOTO_ID_ROLE = Qt.ItemDataRole.UserRole + 1
    DECISION_ROLE = Qt.ItemDataRole.UserRole + 2
    SUMMARY_ROLE = Qt.ItemDataRole.UserRole + 3

    def __init__(self, controller: ProjectController, parent: QObject | None = None) -> None:
        """Create an empty model.

        Args:
            controller: Gives the project and the thumbnails.
            parent: Qt parent object.
        """
        super().__init__(parent)
        self._controller = controller
        self._ids: list[str] = []
        self._rows: dict[str, int] = {}

    @property
    def photo_ids(self) -> list[str]:
        """Ids of the photos in the model, in order."""
        return list(self._ids)

    def set_photo_ids(self, photo_ids: Sequence[str]) -> None:
        """Show another list of photos.

        Args:
            photo_ids: Ids of the photos, in the order to show them.
        """
        self.beginResetModel()
        self._ids = list(photo_ids)
        self._rows = {photo_id: row for row, photo_id in enumerate(self._ids)}
        self.endResetModel()

    def row_of(self, photo_id: str) -> int | None:
        """The row of a photo.

        Args:
            photo_id: Id of the photo.

        Returns:
            The row, or None when the photo is not in the model.
        """
        return self._rows.get(photo_id)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008 - Qt's own default
        """Number of photos (Qt asks for this).

        Args:
            parent: Always the root for a list.

        Returns:
            The number of rows.
        """
        if parent.isValid():
            return 0
        return len(self._ids)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        """Give one piece of data about a photo (Qt asks for this when drawing).

        Args:
            index: Which photo.
            role: Which piece of data: the name, the thumbnail, the decision and so on.

        Returns:
            The data, or None.
        """
        project = self._controller.project
        if project is None or not index.isValid():
            return None
        row = index.row()
        if row >= len(self._ids):
            return None
        photo_id = self._ids[row]
        if role == Qt.ItemDataRole.DisplayRole:
            photo = project.photo(photo_id)
            return photo.name if photo is not None else ""
        if role == Qt.ItemDataRole.DecorationRole:
            return self._controller.thumbnail(photo_id)
        if role == self.PHOTO_ID_ROLE:
            return photo_id
        if role == self.DECISION_ROLE:
            return project.decision_of(photo_id)
        if role == self.SUMMARY_ROLE:
            return self._summary(photo_id)
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(photo_id)
        return None

    def refresh_photo(self, photo_id: str) -> None:
        """Redraw one photo after its data changed.

        Args:
            photo_id: Id of the photo.
        """
        row = self._rows.get(photo_id)
        if row is None:
            return
        index = self.index(row, 0)
        self.dataChanged.emit(index, index)

    def refresh_all(self) -> None:
        """Redraw every photo, for example after the limits of the checks changed."""
        if not self._ids:
            return
        last = len(self._ids) - 1
        top = self.index(0, 0)
        bottom = self.index(last, 0)
        self.dataChanged.emit(top, bottom)

    def _summary(self, photo_id: str) -> str:
        """The second line of a tile: the check result, or the user's own decision.

        Args:
            photo_id: Id of the photo.

        Returns:
            The text.
        """
        project = self._controller.project
        result = project.quality_of(photo_id)
        if result is None:
            return "Reading…"
        user_decision = project.user_decision_of(photo_id)
        if user_decision is not None:
            return f"{user_decision.value} (your choice)"
        return result.summary()

    def _tooltip(self, photo_id: str) -> str:
        """The tooltip of a tile: name, time, exposure and the check result.

        Args:
            photo_id: Id of the photo.

        Returns:
            The text.
        """
        project = self._controller.project
        photo = project.photo(photo_id)
        if photo is None:
            return ""
        lines = [photo.name]
        taken_at = photo.info.taken_at
        if taken_at is not None:
            time_text = taken_at.strftime("%d %b %Y, %H:%M:%S")
            lines.append(time_text)
        exposure = photo.info.exposure_text()
        if exposure:
            lines.append(exposure)
        summary = self._summary(photo_id)
        lines.append(summary)
        return "\n".join(lines)
