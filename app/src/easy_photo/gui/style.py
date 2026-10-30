"""Colors and the style sheet of the window, in a light and a dark theme."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from string import Template

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QWidget


@dataclass(frozen=True)
class ThemeColors:
    """The colors of one theme, as hex strings."""

    window: str
    panel: str
    sidebar: str
    hover: str
    text: str
    muted: str
    border: str
    accent: str
    accent_hover: str
    accent_soft: str
    accent_strong: str
    accent_text: str
    keep: str
    unsure: str
    set_aside: str
    tile: str
    image_back: str


LIGHT_COLORS = ThemeColors(
    window="#F4F5F7",
    panel="#FFFFFF",
    sidebar="#ECEEF2",
    hover="#E3E7ED",
    text="#1E2329",
    muted="#5E6875",
    border="#D5DAE1",
    accent="#2563EB",
    accent_hover="#1D4FD7",
    accent_soft="#DCE7FD",
    accent_strong="#1A44B8",
    accent_text="#FFFFFF",
    keep="#1A7F37",
    unsure="#B26B00",
    set_aside="#C93434",
    tile="#F7F8FA",
    image_back="#E6E9EE",
)

DARK_COLORS = ThemeColors(
    window="#15171B",
    panel="#1E2127",
    sidebar="#111317",
    hover="#2A2E36",
    text="#E5E8EC",
    muted="#98A2AF",
    border="#30353E",
    accent="#4F8CFF",
    accent_hover="#6A9EFF",
    accent_soft="#1F2F4D",
    accent_strong="#A9C6FF",
    accent_text="#0B1220",
    keep="#3FB950",
    unsure="#E3A008",
    set_aside="#F26464",
    tile="#23262D",
    image_back="#101216",
)

STYLE_TEMPLATE = """
QWidget {
    color: $text;
    font-size: 10pt;
}
QMainWindow, QDialog, #Workspace, #StartPage, #Pages {
    background: $window;
}
#Sidebar {
    background: $sidebar;
    border-right: 1px solid $border;
}
#AppTitle {
    font-size: 16pt;
    font-weight: 700;
}
#StartTitle {
    font-size: 30pt;
    font-weight: 700;
}
#ProjectName, #Muted {
    color: $muted;
}
#ErrorText {
    color: $set_aside;
}
#PageTitle {
    font-size: 17pt;
    font-weight: 700;
}
#PageHint {
    color: $muted;
}
#CardTitle, #SectionTitle {
    font-size: 11pt;
    font-weight: 600;
}
#StepButton {
    text-align: left;
    padding: 9px 12px;
    border: none;
    border-radius: 8px;
    background: transparent;
}
#StepButton:hover {
    background: $hover;
}
#StepButton:checked {
    background: $accent_soft;
    color: $accent_strong;
    font-weight: 600;
}
QPushButton {
    padding: 6px 14px;
    border: 1px solid $border;
    border-radius: 6px;
    background: $panel;
}
QPushButton:hover {
    border-color: $accent;
}
QPushButton:pressed {
    background: $hover;
}
QPushButton:disabled {
    color: $muted;
    background: $window;
}
QPushButton[primary="true"] {
    background: $accent;
    color: $accent_text;
    border: 1px solid $accent;
    font-weight: 600;
}
QPushButton[primary="true"]:hover {
    background: $accent_hover;
}
QPushButton[primary="true"]:disabled {
    background: $border;
    border-color: $border;
    color: $muted;
}
QPushButton#Segment {
    border-radius: 13px;
    padding: 4px 14px;
}
QPushButton#Segment:checked {
    background: $accent_soft;
    border-color: $accent;
    color: $accent_strong;
    font-weight: 600;
}
#Card, #Inspector, #VersionCard, #Panel {
    background: $panel;
    border: 1px solid $border;
    border-radius: 10px;
}
#VersionCard[selected="true"] {
    border: 2px solid $accent;
    background: $accent_soft;
}
#DropZone {
    background: $panel;
    border: 2px dashed $border;
    border-radius: 12px;
}
#DropZone[hover="true"] {
    border-color: $accent;
    background: $accent_soft;
}
QListView, QListWidget {
    background: $panel;
    border: 1px solid $border;
    border-radius: 8px;
    outline: none;
}
QListWidget::item {
    padding: 6px;
    border-radius: 6px;
}
QListWidget::item:hover {
    background: $hover;
}
QListWidget::item:selected {
    background: $accent_soft;
    color: $text;
}
QLineEdit, QSpinBox, QDoubleSpinBox {
    padding: 5px 8px;
    border: 1px solid $border;
    border-radius: 6px;
    background: $panel;
    selection-background-color: $accent;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: $accent;
}
QProgressBar {
    border: 1px solid $border;
    border-radius: 5px;
    background: $panel;
    text-align: center;
    max-height: 12px;
}
QProgressBar::chunk {
    background: $accent;
    border-radius: 4px;
}
QStatusBar {
    background: $sidebar;
    border-top: 1px solid $border;
}
QScrollArea {
    border: none;
    background: transparent;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}
QSplitter::handle {
    background: transparent;
}
QToolTip {
    background: $panel;
    color: $text;
    border: 1px solid $border;
    padding: 4px;
}
QMenuBar {
    background: $sidebar;
}
QMenu {
    background: $panel;
    border: 1px solid $border;
}
QMenu::item:selected {
    background: $accent_soft;
    color: $text;
}
"""
"""The style sheet, with ``$name`` where a theme color goes."""


class AppStyle:
    """Picks the light or dark theme to match the system, and styles the whole app."""

    def __init__(self) -> None:
        """Start with the light theme; :meth:`apply_to` picks the one the system uses."""
        self._colors = LIGHT_COLORS

    @property
    def colors(self) -> ThemeColors:
        """The colors of the theme in use."""
        return self._colors

    def apply_to(self, app: QApplication) -> None:
        """Give the application the Fusion style, the theme's palette and the style sheet.

        Args:
            app: The Qt application.
        """
        app.setStyle("Fusion")
        dark = self._system_prefers_dark()
        self._colors = DARK_COLORS if dark else LIGHT_COLORS
        palette = self._make_palette()
        app.setPalette(palette)
        sheet = self._make_style_sheet()
        app.setStyleSheet(sheet)

    def color(self, name: str) -> QColor:
        """One theme color as a QColor.

        Args:
            name: Name of the color, such as "accent" or "keep".

        Returns:
            The color.
        """
        value = getattr(self._colors, name)
        return QColor(value)

    def refresh(self, widget: QWidget) -> None:
        """Apply the style sheet again after a widget property used by it changed.

        Args:
            widget: The widget whose property changed.
        """
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)

    def _system_prefers_dark(self) -> bool:
        """Ask the system whether it uses a dark color scheme.

        Returns:
            True for a dark scheme.
        """
        hints = QGuiApplication.styleHints()
        scheme = hints.colorScheme()
        return scheme == Qt.ColorScheme.Dark

    def _make_palette(self) -> QPalette:
        """Build the Qt palette from the theme colors.

        Returns:
            The palette.
        """
        colors = self._colors
        roles = [
            (QPalette.ColorRole.Window, colors.window),
            (QPalette.ColorRole.WindowText, colors.text),
            (QPalette.ColorRole.Base, colors.panel),
            (QPalette.ColorRole.AlternateBase, colors.tile),
            (QPalette.ColorRole.Text, colors.text),
            (QPalette.ColorRole.Button, colors.panel),
            (QPalette.ColorRole.ButtonText, colors.text),
            (QPalette.ColorRole.Highlight, colors.accent),
            (QPalette.ColorRole.HighlightedText, colors.accent_text),
            (QPalette.ColorRole.ToolTipBase, colors.panel),
            (QPalette.ColorRole.ToolTipText, colors.text),
            (QPalette.ColorRole.PlaceholderText, colors.muted),
            (QPalette.ColorRole.Link, colors.accent),
        ]
        palette = QPalette()
        for role, value in roles:
            color = QColor(value)
            palette.setColor(role, color)
        muted = QColor(colors.muted)
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
            palette.setColor(QPalette.ColorGroup.Disabled, role, muted)
        return palette

    def _make_style_sheet(self) -> str:
        """Fill the theme colors into the style sheet.

        Returns:
            The style sheet.
        """
        values = asdict(self._colors)
        template = Template(STYLE_TEMPLATE)
        return template.substitute(values)
