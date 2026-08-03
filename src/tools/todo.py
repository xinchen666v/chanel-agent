"""TodoWrite tool — in-memory task list with nag reminder.

Design ported from learn-claude-code/s05_todo_write:
- todo_write itself does NO actual work. It cannot read files, run commands,
  or modify anything. Its only job is to help the agent PLAN before acting.
- A rounds_since_todo counter tracks how many turns have passed without a
  todo_write call. After 3 consecutive turns, the event loop injects a
  reminder message into the conversation history.
"""

from __future__ import annotations

from ui.terminal import Terminal


class TodoTool:
    """In-memory task list manager for agent planning.

    State is stored in process memory and cleared on exit. This is the
    V1 / simple version — no file persistence, no dependency graph, no
    concurrent safety. For complex task orchestration, consider a file-
    backed V2 (see s12 of learn-claude-code).
    """

    def __init__(self):
        self._todos: list[dict] = []
        self._rounds_since_todo: int = 0

    # ── Public API (called from tool handler) ──

    def handle(self, todos: list[dict]) -> str:
        """Handle a todo_write tool call.

        Args:
            todos: List of dicts with keys "content" (str) and "status"
                   (one of "pending", "in_progress", "completed").

        Returns:
            A summary string for the tool result.
        """
        self._todos = todos
        self._rounds_since_todo = 0  # Reset nag counter

        output = self._format_todos()
        Terminal.info(output)
        return f"Updated {len(todos)} tasks"

    def handle_merge(self, todos: list[dict]) -> str:
        """Merge-style update: only update matching items by id.

        This allows the agent to update individual task statuses without
        re-sending the entire list every time.

        Each item in todos may have an "id" field. If the id matches an
        existing task, that task is updated (other fields are retained).
        If no matching id exists, the item is appended as a new task.

        Args:
            todos: List of partial dicts. Each item may have "id", "content",
                   "status", and optionally "priority".

        Returns:
            A summary string for the tool result.
        """
        for incoming in todos:
            incoming_id = incoming.get("id")
            if incoming_id is not None:
                # Try to find and update existing
                found = False
                for existing in self._todos:
                    if existing.get("id") == incoming_id:
                        if "content" in incoming:
                            existing["content"] = incoming["content"]
                        if "status" in incoming:
                            existing["status"] = incoming["status"]
                        if "priority" in incoming:
                            existing["priority"] = incoming["priority"]
                        found = True
                        break
                if not found:
                    # New item with explicit id
                    self._todos.append(incoming)
            else:
                # No id — append as new
                self._todos.append(incoming)

        self._rounds_since_todo = 0
        output = self._format_todos()
        Terminal.info(output)
        return f"Updated {len(self._todos)} tasks (merge mode)"

    # ── Nag reminder (called from event loop) ──

    @property
    def rounds_since_todo(self) -> int:
        """Number of consecutive turns without a todo_write call."""
        return self._rounds_since_todo

    def increment_rounds(self):
        """Called after each agent turn to track the nag counter."""
        self._rounds_since_todo += 1

    def reset_rounds(self):
        """Reset the nag counter (e.g. after injecting a reminder)."""
        self._rounds_since_todo = 0

    def get_reminder_message(self) -> str:
        """Return the reminder message to inject into conversation history."""
        return "<reminder>Update your todos.</reminder>"

    # ── Internal helpers ──

    def _format_todos(self) -> str:
        """Format the current todo list for terminal display."""
        if not self._todos:
            return "\n## Current Tasks\n  (empty)"

        lines = ["\n## Current Tasks"]
        icons = {"pending": " ", "in_progress": "▸", "completed": "✓"}

        for t in self._todos:
            status = t.get("status", "pending")
            icon = icons.get(status, "?")
            priority = t.get("priority", "")
            prio_mark = f" [{priority}]" if priority else ""
            lines.append(f"  [{icon}]{prio_mark} {t['content']}")

        # Summary counts
        counts = {"pending": 0, "in_progress": 0, "completed": 0}
        for t in self._todos:
            s = t.get("status", "pending")
            if s in counts:
                counts[s] += 1

        summary_parts = []
        if counts["completed"]:
            summary_parts.append(f"{counts['completed']} done")
        if counts["in_progress"]:
            summary_parts.append(f"{counts['in_progress']} active")
        if counts["pending"]:
            summary_parts.append(f"{counts['pending']} pending")
        if summary_parts:
            lines.append(f"  ---\n  {', '.join(summary_parts)}")

        return "\n".join(lines)