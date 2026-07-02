"""Terminal and TUI output management.

Supports two modes:
  - Terminal mode: standard print with ANSI colors (original behavior)
  - TUI mode: routes output to Textual TUI panels (chat / status / tool-log)

Switched via Terminal.use_tui(tui_app) before the event loop starts.
"""

from __future__ import annotations

import sys
from datetime import datetime

# Forward reference for the TUI app class (avoid circular import at module level)
TUI_APP = None


class Terminal:
    """Unified output routing — terminal or TUI depending on mode."""

    _tui_app: TUI_APP = None  # type: ignore
    _tui_mode = False

    @classmethod
    def use_tui(cls, app) -> None:
        """Switch to TUI mode. Call before the event loop starts."""
        cls._tui_app = app
        cls._tui_mode = True

    @classmethod
    def _ts(cls) -> str:
        """Timestamp prefix for terminal mode. Empty in TUI mode."""
        if cls._tui_mode:
            return ""
        return datetime.now().strftime("[%H:%M:%S] ")

    # ── Info / status messages → status panel (TUI) or yellow print (terminal) ──

    @classmethod
    def info(cls, text: str) -> None:
        """System-level info message."""
        if cls._tui_mode and cls._tui_app:
            cls._tui_app.update_status(text)
        else:
            print(f"\033[33m{text}\033[0m")

    # ── Agent messages → chat panel (TUI) or magenta print (terminal) ──

    @classmethod
    def agent_message(cls, text: str) -> None:
        """Agent proactive message (from send_message tool)."""
        if cls._tui_mode and cls._tui_app:
            cls._tui_app.add_chat("agent", text)
        else:
            print(f"\n{cls._ts()}\033[35m[Agent] {text}\033[0m\n")

    @classmethod
    def agent_response(cls, text: str) -> None:
        """Agent response text (non-proactive, direct reply to user input)."""
        if cls._tui_mode and cls._tui_app:
            cls._tui_app.add_chat("agent", text)
        else:
            print(text)

    # ── Tool debug output → tool-log panel (TUI) or grey print (terminal) ──

    @classmethod
    def tool_debug(cls, text: str) -> None:
        """Tool call debug output."""
        if cls._tui_mode and cls._tui_app:
            cls._tui_app.add_tool(text)
        else:
            print(f"\033[90m> {text}\033[0m")

    # ── Prompt (terminal only, TUI uses Input widget) ──

    @classmethod
    def prompt(cls, text: str = "") -> str:
        """Read user input. In TUI mode returns empty string (input handled by widget)."""
        if cls._tui_mode:
            return ""
        try:
            return input(f"\033[36m{text}\033[0m")
        except (EOFError, KeyboardInterrupt):
            return "q"

    # ── Banner ──

    @classmethod
    def banner(cls, text: str) -> None:
        """Banner / startup message. In TUI mode routes to status."""
        if cls._tui_mode and cls._tui_app:
            cls._tui_app.update_status(text)
        else:
            print(f"\033[36m{text}\033[0m")