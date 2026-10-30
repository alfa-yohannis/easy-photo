"""The app window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from easy_photo import APP_NAME, APP_VERSION
from easy_photo.gui.controller import ProjectController
from easy_photo.gui.dialogs import AiSettingsDialog, NewProjectDialog
from easy_photo.gui.pages.base_page import WorkflowPage
from easy_photo.gui.pages.export_page import ExportPage
from easy_photo.gui.pages.filter_page import FilterPage
from easy_photo.gui.pages.group_page import GroupPage
from easy_photo.gui.pages.references_page import ReferencesPage
from easy_photo.gui.pages.refine_page import RefinePage
from easy_photo.gui.pages.source_page import SourcePage
from easy_photo.gui.pages.start_page import StartPage
from easy_photo.gui.style import AppStyle
from easy_photo.gui.widgets.step_list import StepList
from easy_photo.services.ai_words import AiWordsReader
from easy_photo.services.manifest import ProjectManifest


class MainWindow(QMainWindow):
    """The app window.

    Without an open project it shows the start screen. With a project it
    shows the sidebar with the six steps, the page of the current step, and
    Back and Continue buttons. The status bar shows what runs in the
    background, with a Stop button.
    """

    STEP_TITLES = ("Source", "Filter", "Group", "References", "Refine", "Export")
    NOTICE_MS = 6000

    def __init__(self, controller: ProjectController, style: AppStyle, parent: QWidget | None = None) -> None:
        """Create the window.

        Args:
            controller: Runs the work and holds the project.
            style: Gives the theme colors.
            parent: Qt parent widget.
        """
        super().__init__(parent)
        self._controller = controller
        self._style = style
        self.setWindowTitle(APP_NAME)
        self.resize(1440, 900)
        self.setMinimumSize(1024, 680)
        self._root = QStackedWidget(self)
        self.setCentralWidget(self._root)
        self._start_page = StartPage(self._root)
        self._start_page.new_requested.connect(self._new_project)
        self._start_page.open_requested.connect(self._open_project)
        self._start_page.recent_chosen.connect(controller.open_project)
        self._workspace = self._make_workspace()
        self._root.addWidget(self._start_page)
        self._root.addWidget(self._workspace)
        self._make_menus()
        self._make_status_bar()
        self._connect_controller()
        self._show_start()

    @property
    def pages(self) -> list[WorkflowPage]:
        """The six workflow pages, in order."""
        return list(self._pages)

    def go_to(self, index: int) -> None:
        """Show the page of a step.

        Args:
            index: Index of the step, from 0.
        """
        self._pages_stack.setCurrentIndex(index)
        self._steps.set_current(index)
        page = self._pages[index]
        page.on_shown()
        self._refresh_steps()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Stop background work and save the project before the window closes.

        Args:
            event: The close event.
        """
        self._controller.shutdown()
        event.accept()

    # ----------------------------------------------------------------- layout

    def _make_workspace(self) -> QWidget:
        """The sidebar, the page area and the Back and Continue buttons.

        Returns:
            The workspace widget.
        """
        workspace = QWidget(self._root)
        workspace.setObjectName("Workspace")
        self._steps = StepList(self.STEP_TITLES, workspace)
        self._steps.step_clicked.connect(self.go_to)
        self._pages_stack = QStackedWidget(workspace)
        self._pages_stack.setObjectName("Pages")
        controller = self._controller
        style = self._style
        references_page = ReferencesPage(controller, style, self._pages_stack)
        references_page.ai_settings_requested.connect(self._open_ai_settings)
        self._pages: list[WorkflowPage] = [
            SourcePage(controller, style, self._pages_stack),
            FilterPage(controller, style, self._pages_stack),
            GroupPage(controller, style, self._pages_stack),
            references_page,
            RefinePage(controller, style, self._pages_stack),
            ExportPage(controller, style, self._pages_stack),
        ]
        for page in self._pages:
            self._pages_stack.addWidget(page)
            page.readiness_changed.connect(self._refresh_steps)
        self._back_button = QPushButton("Back")
        self._back_button.clicked.connect(self._go_back)
        self._continue_button = QPushButton("Continue")
        self._continue_button.setProperty("primary", True)
        self._continue_button.clicked.connect(self._go_on)
        navigation = QHBoxLayout()
        navigation.setContentsMargins(28, 4, 28, 14)
        navigation.addWidget(self._back_button)
        navigation.addStretch(1)
        navigation.addWidget(self._continue_button)
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self._pages_stack, 1)
        right.addLayout(navigation)
        layout = QHBoxLayout(workspace)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._steps)
        layout.addLayout(right, 1)
        return workspace

    def _make_menus(self) -> None:
        """The Project and Help menus."""
        menu_bar = self.menuBar()
        project_menu = menu_bar.addMenu("&Project")
        new_action = self._make_action("&New project…", self._new_project, QKeySequence.StandardKey.New)
        open_action = self._make_action("&Open project…", self._open_project, QKeySequence.StandardKey.Open)
        self._save_action = self._make_action("&Save", self._controller.save_now, QKeySequence.StandardKey.Save)
        self._close_action = self._make_action("&Close project", self._controller.close_project)
        quit_action = self._make_action("&Quit", self.close, QKeySequence.StandardKey.Quit)
        project_menu.addAction(new_action)
        project_menu.addAction(open_action)
        self._recent_menu = QMenu("Open &recent", self)
        self._recent_menu.aboutToShow.connect(self._fill_recent_menu)
        project_menu.addMenu(self._recent_menu)
        project_menu.addSeparator()
        project_menu.addAction(self._save_action)
        project_menu.addAction(self._close_action)
        project_menu.addSeparator()
        project_menu.addAction(quit_action)
        settings_menu = menu_bar.addMenu("&Settings")
        ai_action = self._make_action("&AI for your own words…", self._open_ai_settings)
        settings_menu.addAction(ai_action)
        help_menu = menu_bar.addMenu("&Help")
        about_action = self._make_action(f"&About {APP_NAME}", self._show_about)
        help_menu.addAction(about_action)

    def _make_action(self, text: str, handler: object, shortcut: QKeySequence.StandardKey | None = None) -> QAction:
        """Make a menu action.

        Args:
            text: The menu text.
            handler: Called when the action is chosen.
            shortcut: Its keyboard shortcut, if any.

        Returns:
            The action.
        """
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.triggered.connect(handler)
        return action

    def _make_status_bar(self) -> None:
        """The status bar: what runs in the background, its progress, and a Stop button."""
        status_bar = self.statusBar()
        self._status_label = QLabel("")
        self._progress = QProgressBar()
        self._progress.setFixedWidth(380)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        self._stop_button = QPushButton("Stop")
        self._stop_button.setVisible(False)
        self._stop_button.clicked.connect(self._controller.tasks.stop_all)
        status_bar.addWidget(self._status_label, 1)
        status_bar.addPermanentWidget(self._progress)
        status_bar.addPermanentWidget(self._stop_button)

    def _connect_controller(self) -> None:
        """Listen to the controller and its background tasks."""
        controller = self._controller
        controller.project_opened.connect(self._show_workspace)
        controller.project_closed.connect(self._show_start)
        controller.notice.connect(self._show_notice)
        controller.problem.connect(self._show_problem)
        controller.claude_login_needed.connect(self._offer_claude_login)
        for signal in (
            controller.analysis_changed,
            controller.groups_changed,
            controller.choices_changed,
            controller.pipelines_changed,
            controller.photos_changed,
            controller.export_finished,
        ):
            signal.connect(self._refresh_steps)
        tasks = controller.tasks
        tasks.busy_changed.connect(self._on_busy_changed)
        tasks.status_changed.connect(self._status_label.setText)
        tasks.progress_changed.connect(self._on_progress)

    # --------------------------------------------------------------- showing

    def _show_start(self) -> None:
        """Show the start screen."""
        recent = self._controller.recent_projects
        self._start_page.set_recent(recent)
        self._root.setCurrentWidget(self._start_page)
        self.setWindowTitle(APP_NAME)
        self._save_action.setEnabled(False)
        self._close_action.setEnabled(False)

    def _show_workspace(self) -> None:
        """Show the open project at its first step."""
        project = self._controller.project
        self._steps.set_project_name(project.name)
        self.setWindowTitle(f"{project.name} - {APP_NAME}")
        self._root.setCurrentWidget(self._workspace)
        self._save_action.setEnabled(True)
        self._close_action.setEnabled(True)
        self.go_to(0)

    def _refresh_steps(self, *_ignored: object) -> None:
        """Update the status lines and check marks in the sidebar, and the Back and Continue buttons.

        Args:
            _ignored: Whatever the signal that called this carries (not used).
        """
        if self._controller.project is None:
            return
        for index, page in enumerate(self._pages):
            text = page.status_text()
            done = page.is_done()
            self._steps.set_status(index, text)
            self._steps.set_done(index, done)
        index = self._pages_stack.currentIndex()
        last = len(self._pages) - 1
        page = self._pages[index]
        ready = page.is_ready()
        self._back_button.setEnabled(index > 0)
        self._continue_button.setVisible(index < last)
        self._continue_button.setEnabled(ready)

    def _go_back(self) -> None:
        """Show the step before."""
        index = self._pages_stack.currentIndex()
        if index > 0:
            self.go_to(index - 1)

    def _go_on(self) -> None:
        """Show the next step."""
        index = self._pages_stack.currentIndex()
        last = len(self._pages) - 1
        if index < last:
            self.go_to(index + 1)

    # -------------------------------------------------------------- projects

    def _new_project(self) -> None:
        """Ask for the name and place of a new project, then make and open it."""
        default_parent = self._default_projects_folder()
        dialog = NewProjectDialog(default_parent, self)
        dialog.accepted.connect(self._create_from_dialog)
        self._new_dialog = dialog
        dialog.exec()

    def _create_from_dialog(self) -> None:
        """Make the project the user described in the new project dialog."""
        dialog = self._new_dialog
        self._controller.create_project(dialog.project_name, dialog.project_folder)

    def _open_project(self) -> None:
        """Let the user pick a project's manifest file and open it."""
        start = self._default_projects_folder()
        start_text = str(start)
        file_filter = f"easy-photo projects ({ProjectManifest.FILE_NAME});;All files (*)"
        name, _chosen_filter = QFileDialog.getOpenFileName(self, "Open a project", start_text, file_filter)
        if name:
            path = Path(name)
            self._controller.open_project(path)

    def _fill_recent_menu(self) -> None:
        """List the recent projects in the Open recent menu."""
        self._recent_menu.clear()
        recent = self._controller.recent_projects
        if not recent:
            empty = self._recent_menu.addAction("No recent projects")
            empty.setEnabled(False)
            return
        for manifest in recent:
            folder = manifest.parent
            action = self._recent_menu.addAction(folder.name)
            folder_text = str(folder)
            action.setToolTip(folder_text)
            action.setData(manifest)
            action.triggered.connect(self._open_recent_action)

    def _open_recent_action(self) -> None:
        """Open the project of the recent-projects menu entry that was chosen."""
        action = self.sender()
        manifest = action.data()
        self._controller.open_project(manifest)

    def _open_ai_settings(self) -> None:
        """Let the user switch Claude on or off for typed refinements, choose its model, and log in."""
        settings = self._controller.app_settings
        program = self._controller.claude_program
        status = self._controller.claude_login_status()
        dialog = AiSettingsDialog(settings, AiWordsReader.MODELS, program, status, self)
        dialog.accepted.connect(self._apply_ai_settings)
        dialog.login_requested.connect(self._controller.start_claude_login)
        self._ai_dialog = dialog
        dialog.exec()

    def _offer_claude_login(self) -> None:
        """Offer to open the Claude Code login, after Claude could not read words because nobody is logged in."""
        text = (
            "Claude Code is installed but not logged in, so Claude cannot read your words yet.\n\n"
            "Open a terminal window to log in now? Claude Code opens your browser to sign in to your Claude "
            "account. When you are done, the app reads your words."
        )
        buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        answer = QMessageBox.question(self, "Log in to Claude Code", text, buttons)
        if answer == QMessageBox.StandardButton.Yes:
            self._controller.start_claude_login()

    def _apply_ai_settings(self) -> None:
        """Store what the user chose in the AI settings dialog."""
        dialog = self._ai_dialog
        self._controller.update_ai_settings(dialog.ai_enabled, dialog.model)

    def _default_projects_folder(self) -> Path:
        """Where new projects go unless the user picks another folder.

        Returns:
            An "easy-photo" folder inside the user's Pictures folder.
        """
        pictures = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        pictures_folder = Path(pictures)
        return pictures_folder / APP_NAME

    # ------------------------------------------------------------- messages

    def _show_notice(self, text: str) -> None:
        """Show a short message in the status bar for a few seconds.

        Args:
            text: The message.
        """
        status_bar = self.statusBar()
        status_bar.showMessage(text, self.NOTICE_MS)

    def _show_problem(self, text: str) -> None:
        """Show an error in a message box.

        Args:
            text: The error message.
        """
        QMessageBox.warning(self, APP_NAME, text)

    def _show_about(self) -> None:
        """Show what the app is."""
        text = (
            f"<b>{APP_NAME} {APP_VERSION}</b><br><br>"
            "Filters, groups and refines photos, guided by your own picks, examples from the internet, "
            "and examples you give.<br><br>MIT License."
        )
        QMessageBox.about(self, APP_NAME, text)

    # ------------------------------------------------------------- progress

    def _on_busy_changed(self, busy: bool) -> None:
        """Show or hide the progress bar and the Stop button.

        Args:
            busy: True while a task runs.
        """
        self._progress.setVisible(busy)
        self._stop_button.setVisible(busy)
        if not busy:
            self._progress.reset()
            self._progress.setTextVisible(False)

    def _on_progress(self, done: int, total: int, item: str) -> None:
        """Move the progress bar, and name the item being worked on with its number, such as "P1188489.RW2  3 / 6".

        Args:
            done: Items done.
            total: Items in total.
            item: The item being worked on now (number ``done + 1``), or an empty text.
        """
        maximum = max(total, 1)
        self._progress.setMaximum(maximum)
        self._progress.setValue(done)
        if not item or total <= 0:
            self._progress.setTextVisible(False)
            return
        number = min(done + 1, total)
        text = f"{item}  {number} / {total}"
        # QProgressBar reads "%" as the start of a placeholder such as %p.
        escaped = text.replace("%", "%%")
        self._progress.setFormat(escaped)
        self._progress.setTextVisible(True)
