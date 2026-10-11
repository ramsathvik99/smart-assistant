"""
Dashboard Worker Threads
========================
QThread-based workers for executing service adapter functions
off the main GUI thread, keeping the dashboard responsive.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from PyQt6.QtCore import QThread, pyqtSignal, QObject


class DashboardWorker(QThread):
    """Generic worker that runs a callable in a background thread.

    Usage:
        worker = DashboardWorker(fn, arg1, kwarg1=val)
        worker.result_sig.connect(my_slot)
        worker.start()
    """

    result_sig = pyqtSignal(object)
    error_sig = pyqtSignal(str)

    _active_workers: set["DashboardWorker"] = set()

    def __init__(self, func: Callable[..., Any], *args, parent: Optional[QObject] = None, **kwargs):
        super().__init__(parent)
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def start(self, priority: QThread.Priority = QThread.Priority.InheritPriority):
        DashboardWorker._active_workers.add(self)
        try:
            self.finished.connect(self._on_worker_finished)
        except Exception:
            pass
        super().start(priority)

    def _on_worker_finished(self):
        DashboardWorker._active_workers.discard(self)

    def run(self):
        try:
            result = self._func(*self._args, **self._kwargs)
            self.result_sig.emit(result)
        except Exception as e:
            try:
                self.error_sig.emit(str(e))
            except Exception:
                pass


class DashboardPoller(QObject):
    """Timer-based poller for real-time state updates (assistant state, audio, etc.)."""

    tick_sig = pyqtSignal(object)

    def __init__(self, func: Callable[[], Any], interval_ms: int = 500, parent=None):
        super().__init__(parent)
        self._func = func
        self._interval = interval_ms
        self._timer_id: Optional[int] = None

    def start(self):
        if self._timer_id is None:
            self._timer_id = self.startTimer(self._interval)

    def stop(self):
        if self._timer_id is not None:
            self.killTimer(self._timer_id)
            self._timer_id = None

    def timerEvent(self, event):
        if event.timerId() == self._timer_id:
            try:
                data = self._func()
                self.tick_sig.emit(data)
            except Exception as e:
                pass
