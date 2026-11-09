"""The PySide6 window: the start screen, the six workflow pages, and the controller behind them."""

# QtWidgets is loaded before any module of this package loads QtGui. With
# PySide6 6.12 on X11, taking a QtGui class such as QIcon before QtWidgets is
# loaded makes the later QApplication crash while it connects to the screen.
import PySide6.QtWidgets  # noqa: F401
