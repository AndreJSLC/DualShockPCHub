"""Run blocking calls (scans, downloads, installers) off the GUI thread."""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

log = logging.getLogger(__name__)


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(object)
    progress = Signal(int, int)


class Task(QRunnable):
    """``fn(report)`` runs on the pool; ``report(done, total)`` emits progress."""

    def __init__(self, fn: Callable, on_done: Callable | None = None, on_error: Callable | None = None,
                 on_progress: Callable[[int, int], None] | None = None) -> None:
        super().__init__()
        self.fn = fn
        self.signals = _Signals()
        if on_done:
            self.signals.done.connect(on_done)
        if on_error:
            self.signals.failed.connect(on_error)
        if on_progress:
            self.signals.progress.connect(on_progress)

    def run(self) -> None:
        try:
            try:
                result = self.fn(self.signals.progress.emit)
            except Exception as exc:  # noqa: BLE001 - surfaced to the UI
                log.debug("task failed\n%s", traceback.format_exc())
                self.signals.failed.emit(exc)
            else:
                self.signals.done.emit(result)
        except RuntimeError:
            pass  # the app quit while we were working; nobody is listening any more


_live: set[Task] = set()


def run(fn: Callable, on_done: Callable | None = None, on_error: Callable | None = None,
        on_progress: Callable[[int, int], None] | None = None) -> Task:
    task = Task(fn, on_done, on_error, on_progress)
    task.setAutoDelete(False)
    _live.add(task)  # keep the signal object alive until it fires
    task.signals.done.connect(lambda _r: _live.discard(task))
    task.signals.failed.connect(lambda _e: _live.discard(task))
    QThreadPool.globalInstance().start(task)
    return task
