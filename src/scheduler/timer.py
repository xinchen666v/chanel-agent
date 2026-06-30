"""Timer-based autonomous wake scheduler."""

import threading
import queue
from ui.terminal import Terminal


class Scheduler:
    """Schedules next agent wake based on LLM decisions.

    Uses threading.Timer for non-blocking delayed execution.
    Supports cancel/override of pending wake.
    """

    def __init__(self, event_queue: queue.Queue, min_interval: int = 5):
        self._q = event_queue
        self._min_interval = min_interval
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def schedule(self, delay_seconds: int, reason: str):
        """Schedule the next wake. Overrides any pending wake."""
        with self._lock:
            self._cancel()
            delay_seconds = max(self._min_interval, delay_seconds)
            self._timer = threading.Timer(delay_seconds, self._on_fire, args=(reason,))
            self._timer.daemon = True
            self._timer.start()
            Terminal.info(f"[Scheduler] Next wake in {delay_seconds}s | {reason}")

    def cancel(self):
        """Cancel any pending wake."""
        with self._lock:
            self._cancel()

    def _cancel(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _on_fire(self, reason: str):
        """Called when the timer fires. Pushes a wake event."""
        self._q.put(("wake", reason))