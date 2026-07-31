"""Hook registry for the agent loop.

Design borrowed from s04_hooks:
- Hooks are registered externally and triggered at key points in the cycle.
- The loop stays clean: it only calls trigger_hooks(), not hard-coded checks.
- Supported events: UserPromptSubmit, PreToolUse, PostToolUse, Stop.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable


class HookRegistry:
    """Registry for agent lifecycle hooks."""

    SUPPORTED_EVENTS = {
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
        "Stop",
    }

    def __init__(self):
        self._hooks: dict[str, list[Callable]] = defaultdict(list)

    def register(self, event: str, callback: Callable) -> None:
        """Register a callback for an event.

        For PreToolUse, a non-None return value blocks the tool and becomes
        the tool result. For Stop, a non-None string forces the loop to
        continue with that message injected as user input.
        """
        if event not in self.SUPPORTED_EVENTS:
            raise ValueError(f"Unknown hook event: {event}. Supported: {self.SUPPORTED_EVENTS}")
        self._hooks[event].append(callback)

    def trigger(self, event: str, *args, **kwargs):
        """Run all callbacks for an event until one returns non-None.

        Returns the first non-None result, or None if all callbacks returned
        None (meaning "continue normally").
        """
        for callback in self._hooks.get(event, []):
            result = callback(*args, **kwargs)
            if result is not None:
                return result
        return None
