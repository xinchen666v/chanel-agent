"""Textual TUI for Chanel Agent — 3-panel layout with chat, status, and tool log."""

import threading
from datetime import datetime

from textual.app import App, ComposeResult
from textual.widgets import Header, Input, RichLog, Static
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive

from agent.event_loop import EventLoop
from config import Config
from ui.terminal import Terminal


class AgentTUI(App):
    """Main TUI application for Chanel Agent.

    Layout:
      ┌──────────────────────────────┬──────────────────────┐
      │  Chat (left, 2/3)            │ Status (right top)   │
      │  - user messages             │ - running state       │
      │  - agent replies             │ - next wake           │
      │  - tool output (dimmed)      │ - silent streak       │
      │                              │ - latest reasoning    │
      │                              ├──────────────────────┤
      │                              │ Tool Log (right btm) │
      │                              │ - recent tool calls   │
      ├──────────────────────────────┴──────────────────────┤
      │  Input bar (bottom)                                  │
      └─────────────────────────────────────────────────────┘
    """

    CSS = """
    Screen {
        layout: vertical;
    }

    #middle {
        height: 1fr;
        layout: horizontal;
    }

    #chat-panel {
        width: 2fr;
        min-width: 40;
        border: solid $primary;
        padding: 0 1;
    }

    #chat-panel RichLog {
        height: 100%;
    }

    #right-column {
        width: 1fr;
        min-width: 30;
        layout: vertical;
    }

    #status-panel {
        height: 1fr;
        border: solid $success;
        padding: 0 1;
    }

    #tool-panel {
        height: 1fr;
        border: solid $warning;
        padding: 0 1;
    }

    #tool-panel RichLog {
        height: 100%;
    }

    #input-bar {
        dock: bottom;
        margin: 0 1 1 1;
    }

    .chat-time {
        color: $text-disabled;
    }

    .chat-user {
        color: $text;
    }

    .chat-agent {
        color: $secondary;
    }
    """

    TITLE = "Chanel Agent — Autonomous Agent Runtime"

    def __init__(self, config: Config):
        super().__init__()
        self._config = config
        self._event_loop: EventLoop | None = None
        self._status_lines: list[str] = []

    def compose(self) -> ComposeResult:
        """Build layout."""
        yield Header(show_clock=True)
        with Horizontal(id="middle"):
            # Left: Chat panel
            with Vertical(id="chat-panel"):
                yield RichLog(id="chat", markup=True, highlight=True, wrap=True)
            # Right: Status + Tool panels
            with Vertical(id="right-column"):
                yield Static(id="status-panel", content="● Initializing...")
                with Vertical(id="tool-panel"):
                    yield RichLog(id="tool-log", markup=True, wrap=True)
        yield Input(id="input-bar", placeholder="Type a message... (Ctrl+Q to quit)")

    def on_mount(self) -> None:
        """Start the agent event loop in a worker thread."""
        Terminal.use_tui(self)
        # Show startup info in status
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_text = (
            f"● Starting...\n"
            f"Model: {self._config.model}\n"
            f"DB: {self._config.db_path.name}\n"
            f"Profile: user_profile.md\n"
            f"Started: {now}"
        )
        self._status_lines = status_text.split("\n")
        self.query_one("#status-panel").update(status_text)
        self._add_chat("system", f"Chanel Agent started — {now}")
        # Launch agent event loop in background thread
        self._event_loop = EventLoop(self._config, tui_mode=True)
        threading.Thread(target=self._run_agent, daemon=True).start()

    def _run_agent(self) -> None:
        """Run the agent event loop in a worker thread."""
        try:
            self._event_loop.start()
        except Exception:
            import traceback
            self.call_from_thread(
                self._add_chat, "system",
                f"Agent error:\n{traceback.format_exc()}",
            )

    def on_input_submitted(self, message: Input.Submitted) -> None:
        """Handle user text input."""
        text = message.value.strip()
        if not text:
            return
        # Clear input field
        self.query_one("#input-bar").value = ""
        # Check quit command
        if text.lower() in ("q", "exit"):
            self._shutdown_app()
            return
        # Show in chat and send to agent
        self._add_chat("user", text)
        self._event_loop.submit_user_input(text)

    # ── Public API called from Terminal / worker thread ──

    def add_chat(self, role: str, text: str) -> None:
        """Add a chat message (thread-safe, called from worker thread)."""
        self.call_from_thread(self._add_chat, role, text)

    def add_tool(self, text: str) -> None:
        """Add a tool log entry (thread-safe)."""
        self.call_from_thread(self._add_tool, text)

    def update_status(self, text: str) -> None:
        """Update the status panel (thread-safe)."""
        self.call_from_thread(self._update_status, text)

    # ── Internal widget updates ──

    def _add_chat(self, role: str, text: str) -> None:
        """Add message to chat panel."""
        chat = self.query_one("#chat", RichLog)
        time = datetime.now().strftime("%H:%M")
        if role == "user":
            chat.write(f"[bold cyan]你[/] [dim]{time}[/]")
            chat.write(f"{text}\n")
        elif role == "agent":
            chat.write(f"[bold magenta]Chanel[/] [dim]{time}[/]")
            chat.write(f"{text}\n")
        else:  # system
            chat.write(f"[dim]{text}[/]\n")
        chat.scroll_end()

    def _add_tool(self, text: str) -> None:
        """Add entry to tool log panel."""
        tool_log = self.query_one("#tool-log", RichLog)
        tool_log.write(f"[dim]{text}[/]")
        tool_log.scroll_end()

    def _update_status(self, text: str) -> None:
        """Update status panel content.

        Uses internal _status_lines list instead of reading back from the
        Static widget, since Textual 8.x does not expose a renderable attribute.
        """
        if not isinstance(text, str) or not text:
            return
        # Check if we already have a line with this key prefix
        key = text.split(":")[0].strip() if ":" in text else ""
        found = False
        for i, line in enumerate(self._status_lines):
            if key and line.startswith(key):
                self._status_lines[i] = text
                found = True
                break
        if not found:
            # Append new line, keep last 8
            self._status_lines.append(text)
            self._status_lines = self._status_lines[-8:]
        status = self.query_one("#status-panel", Static)
        status.update("\n".join(self._status_lines))

    def _shutdown_app(self) -> None:
        """Shut down agent and exit TUI."""
        if self._event_loop:
            self._event_loop._event_queue.put(("shutdown", None))
        self.exit()

    def action_quit(self) -> None:
        """Override default quit to do clean shutdown."""
        self._shutdown_app()