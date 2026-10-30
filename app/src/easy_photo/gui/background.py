"""Running slow work on worker threads without freezing the window."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from functools import partial

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

LOGGER = logging.getLogger(__name__)


class TaskSignals(QObject):
    """Signals a background task sends to the window thread.

    The signals object is made on the window thread, so Qt delivers its
    signals there even when they are sent from a worker thread. The receivers
    can therefore safely update the project and the widgets.
    """

    progress = Signal(int, int)
    partial = Signal(object)
    finished = Signal(object)
    failed = Signal(str)


class TaskContext:
    """Given to a job so it can report progress, send partial results and see a stop request."""

    def __init__(self, signals: TaskSignals) -> None:
        """Create the context of one task.

        Args:
            signals: The task's signals.
        """
        self._signals = signals
        self._stop = threading.Event()

    @property
    def stop_requested(self) -> bool:
        """True when the user asked to stop; long jobs check this between items."""
        return self._stop.is_set()

    def request_stop(self) -> None:
        """Ask the job to stop at the next item."""
        self._stop.set()

    def report(self, done: int, total: int) -> None:
        """Tell the window how far the job is.

        Args:
            done: Items done.
            total: Items in total.
        """
        self._signals.progress.emit(done, total)

    def send(self, item: object) -> None:
        """Hand a partial result to the window, for example one measured photo.

        Args:
            item: The partial result.
        """
        self._signals.partial.emit(item)


Job = Callable[[TaskContext], object]
"""A function that does the work of a task and returns its result."""


class BackgroundTask(QRunnable):
    """Runs one job on a worker thread and reports through :class:`TaskSignals`."""

    def __init__(self, title: str, job: Job) -> None:
        """Create a task.

        Args:
            title: What the task does, shown in the status bar.
            job: The work; it gets a :class:`TaskContext` and returns the result.
        """
        super().__init__()
        # The runner keeps the task alive; Qt must not delete it.
        self.setAutoDelete(False)
        self._title = title
        self._job = job
        self._signals = TaskSignals()
        self._context = TaskContext(self._signals)

    @property
    def title(self) -> str:
        """What the task does."""
        return self._title

    @property
    def signals(self) -> TaskSignals:
        """The task's signals."""
        return self._signals

    def request_stop(self) -> None:
        """Ask the job to stop at the next item."""
        self._context.request_stop()

    def run(self) -> None:
        """Run the job. The thread pool calls this on a worker thread."""
        try:
            result = self._job(self._context)
        except Exception as error:  # Any failure must reach the window instead of ending the thread silently.
            LOGGER.exception("Background task %r failed", self._title)
            text = str(error)
            message = text or type(error).__name__
            self._signals.failed.emit(message)
            return
        self._signals.finished.emit(result)


class TaskRunner(QObject):
    """Starts background tasks on a small thread pool and tells the window what is running.

    The pool has two threads, so the computer stays usable during long jobs:
    in the manual runs, three exports at once froze the machine.
    """

    busy_changed = Signal(bool)
    status_changed = Signal(str)
    progress_changed = Signal(int, int)

    def __init__(self, max_threads: int = 2, parent: QObject | None = None) -> None:
        """Create the runner.

        Args:
            max_threads: Most tasks running at the same time.
            parent: Qt parent object.
        """
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max_threads)
        self._running: list[BackgroundTask] = []
        self._shown: list[BackgroundTask] = []
        self._finished: list[BackgroundTask] = []

    @property
    def is_busy(self) -> bool:
        """True while a task the status bar shows is running."""
        return bool(self._shown)

    def start(
        self,
        title: str,
        job: Job,
        on_finished: Callable[[object], None],
        on_failed: Callable[[str], None] | None = None,
        on_partial: Callable[[object], None] | None = None,
        quiet: bool = False,
    ) -> BackgroundTask:
        """Start a task.

        Args:
            title: What the task does, for the status bar.
            job: The work.
            on_finished: Gets the result, on the window thread.
            on_failed: Gets the error message, on the window thread.
            on_partial: Gets each partial result, on the window thread.
            quiet: Do not show the task in the status bar (for quick tasks such as loading a preview).

        Returns:
            The task, which can be asked to stop.
        """
        self._release_finished()
        task = BackgroundTask(title, job)
        signals = task.signals
        if on_partial is not None:
            signals.partial.connect(on_partial)
        signals.finished.connect(on_finished)
        if on_failed is not None:
            signals.failed.connect(on_failed)
        done_handler = partial(self._task_done, task)
        signals.finished.connect(done_handler)
        signals.failed.connect(done_handler)
        self._running.append(task)
        if not quiet:
            signals.progress.connect(self.progress_changed)
            self._shown.append(task)
            self.busy_changed.emit(True)
            self.status_changed.emit(title)
        self._pool.start(task)
        return task

    def stop_all(self) -> None:
        """Ask every running task to stop."""
        for task in self._running:
            task.request_stop()

    def wait(self, milliseconds: int) -> bool:
        """Wait until all tasks are done, for at most the given time.

        Args:
            milliseconds: Longest time to wait.

        Returns:
            True when all tasks are done.
        """
        return self._pool.waitForDone(milliseconds)

    def _task_done(self, task: BackgroundTask, _result: object) -> None:
        """Forget a task that finished or failed, and update the status bar.

        Args:
            task: The task.
            _result: Its result or error message (not used here).
        """
        if task in self._running:
            self._running.remove(task)
        # Kept until the pool is idle: the worker thread may still be returning from run().
        self._finished.append(task)
        if task in self._shown:
            self._shown.remove(task)
            if self._shown:
                latest = self._shown[-1]
                self.status_changed.emit(latest.title)
            else:
                self.busy_changed.emit(False)
                self.status_changed.emit("")
        self._release_finished()

    def _release_finished(self) -> None:
        """Drop finished tasks once no worker thread is running any more."""
        if self._pool.activeThreadCount() == 0:
            self._finished.clear()
