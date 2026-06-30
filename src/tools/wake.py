"""Wake scheduling tool - allows the LLM to decide the next observation time."""

from scheduler.timer import Scheduler


class WakeTool:
    """Tool wrapper for scheduling the next autonomous wake."""

    def __init__(self, scheduler: Scheduler):
        self._scheduler = scheduler

    def handle(self, delay_seconds: int, reason: str) -> str:
        """Schedule the next wake."""
        self._scheduler.schedule(delay_seconds, reason)
        return f"OK: next wake in {delay_seconds}s. Reason: {reason}"