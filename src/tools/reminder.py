"""Reminder tool - allows the LLM to set timed reminders that fire independently of wake cycles.

Reminders use threading.Timer and push events into the main event queue when expired.
This means reminders fire at the exact scheduled time, not dependent on the agent's
wake cycle. The EventLoop handles "reminder" events by sending a toast notification.

Supported actions:
    - set:    Schedule a new reminder at a specific time
    - list:   List all pending reminders
    - cancel: Cancel a specific reminder by ID
"""

import threading
import uuid
import queue
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ui.notification import Notifier


class Reminder:
    """A single reminder with a timer."""

    def __init__(self, reminder_id: str, content: str, target_time: datetime,
                 repeat: bool, event_queue: queue.Queue, notifier: "Notifier"):
        self.id = reminder_id
        self.content = content
        self.target_time = target_time
        self.repeat = repeat
        self._event_queue = event_queue
        self._notifier = notifier
        self._timer: threading.Timer | None = None
        self._cancelled = False

    def schedule(self):
        """Start the timer. Called from the ReminderTool."""
        delay = (self.target_time - datetime.now()).total_seconds()
        if delay <= 0:
            # Already past — fire immediately
            self._fire()
            return
        self._timer = threading.Timer(delay, self._fire)
        self._timer.daemon = True
        self._timer.start()

    def cancel(self):
        """Cancel this reminder's timer."""
        self._cancelled = True
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _fire(self):
        """Called when the timer expires."""
        if self._cancelled:
            return
        # Send notification immediately via the notifier
        try:
            self._notifier.send_bubble(
                f"⏰ 提醒：{self.content}",
                quick_replies=["收到", "5分钟后提醒"]
            )
        except Exception:
            pass
        # Push a reminder event into the main event queue so the agent knows
        try:
            self._event_queue.put_nowait(("reminder", {
                "content": self.content,
                "reminder_id": self.id,
            }))
        except queue.Full:
            pass

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "target_time": self.target_time.strftime("%Y-%m-%d %H:%M:%S"),
            "repeat": self.repeat,
        }


class ReminderTool:
    """Tool wrapper for managing reminders.

    Reminders fire independently of the agent's wake cycle — when the target
    time arrives, a notification is sent immediately via toast + terminal.
    The agent is also notified so it can follow up if needed.
    """

    def __init__(self, event_queue: queue.Queue, notifier: "Notifier"):
        self._event_queue = event_queue
        self._notifier = notifier
        self._reminders: dict[str, Reminder] = {}
        self._lock = threading.Lock()

    def handle(
        self,
        action: str,
        time: str = "",
        content: str = "",
        repeat: bool = False,
        reminder_id: str = "",
    ) -> str:
        """Manage reminders.

        Args:
            action: 'set', 'list', or 'cancel'.
            time: Target time string, e.g. '2026-07-16 09:00' or '17:30' (today).
                  Required for 'set'.
            content: Reminder message. Required for 'set'.
            repeat: Whether to repeat (currently not supported — ignored).
            reminder_id: The ID of the reminder to cancel. Required for 'cancel'.

        Returns:
            Status message.
        """
        try:
            if action == "set":
                return self._set_reminder(time, content, repeat)
            elif action == "list":
                return self._list_reminders()
            elif action == "cancel":
                return self._cancel_reminder(reminder_id)
            else:
                return (
                    f"Unknown action '{action}'. Valid actions: set, list, cancel.\n"
                    "Example: set_reminder(action='set', time='2026-07-16 09:00', content='Trae初赛截稿！')"
                )
        except Exception as e:
            return f"Reminder error: {e}"

    def _set_reminder(self, time_str: str, content: str, repeat: bool) -> str:
        """Schedule a new reminder."""
        if not time_str:
            return "Error: 'time' is required for set action. Example: time='2026-07-16 09:00'"
        if not content:
            return "Error: 'content' is required for set action."

        target_time = self._parse_time(time_str)
        if target_time is None:
            return (
                f"Error: Cannot parse time '{time_str}'. "
                "Use format 'YYYY-MM-DD HH:MM' (e.g. '2026-07-16 09:00') "
                "or 'HH:MM' for today (e.g. '17:30')."
            )

        if target_time <= datetime.now():
            return f"Error: Target time {target_time.strftime('%Y-%m-%d %H:%M')} is in the past."

        reminder_id = uuid.uuid4().hex[:8]
        reminder = Reminder(
            reminder_id=reminder_id,
            content=content,
            target_time=target_time,
            repeat=repeat,
            event_queue=self._event_queue,
            notifier=self._notifier,
        )
        reminder.schedule()

        with self._lock:
            self._reminders[reminder_id] = reminder

        return (
            f"已设置提醒 (id={reminder_id}): "
            f"{target_time.strftime('%Y-%m-%d %H:%M')} — {content}"
        )

    def _list_reminders(self) -> str:
        """List all pending reminders."""
        with self._lock:
            if not self._reminders:
                return "当前没有待处理的提醒。"
            lines = ["待处理的提醒："]
            for r in self._reminders.values():
                d = r.to_dict()
                lines.append(f"  [{d['id']}] {d['target_time']} — {d['content']}")
            return "\n".join(lines)

    def _cancel_reminder(self, reminder_id: str) -> str:
        """Cancel a specific reminder."""
        if not reminder_id:
            return "Error: 'reminder_id' is required for cancel action."

        with self._lock:
            if reminder_id not in self._reminders:
                return f"未找到 reminder_id='{reminder_id}'。用 list 查看所有提醒。"
            r = self._reminders.pop(reminder_id)
            r.cancel()
            return f"已取消提醒 [{reminder_id}]: {r.content}"

    def cancel_all(self):
        """Cancel all pending reminders (called on shutdown)."""
        with self._lock:
            for r in self._reminders.values():
                r.cancel()
            self._reminders.clear()

    @staticmethod
    def _parse_time(time_str: str) -> datetime | None:
        """Parse a time string into a datetime object.

        Supports:
            - 'YYYY-MM-DD HH:MM' (full date + time)
            - 'YYYY-MM-DD HH:MM:SS' (with seconds)
            - 'HH:MM' (today at that time)
            - 'HH:MM:SS' (today at that time with seconds)
        """
        time_str = time_str.strip()
        formats = [
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(time_str, fmt)
            except ValueError:
                continue

        # Try HH:MM (today)
        time_only_formats = ["%H:%M", "%H:%M:%S"]
        for fmt in time_only_formats:
            try:
                t = datetime.strptime(time_str, fmt).time()
                now = datetime.now()
                result = datetime.combine(now.date(), t)
                # If the time is already past today, assume tomorrow
                if result <= now:
                    from datetime import timedelta
                    result += timedelta(days=1)
                return result
            except ValueError:
                continue

        return None