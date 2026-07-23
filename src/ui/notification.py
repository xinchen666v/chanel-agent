"""Notification sender - platform-appropriate implementation.

On Windows/Linux: tkinter-based bubble popup (borderless, topmost, auto-dismiss).
On macOS: native Notification Center via osascript (tkinter requires main thread).

Supports clickable quick-reply buttons (tkinter) or text-embedded actions (macOS).
"""

import sys
import threading
import queue as queue_module
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import queue

logger = logging.getLogger(__name__)


class Notifier:
    """Platform-appropriate notification sender.

    On Windows/Linux runs a dedicated tkinter daemon thread for bubble popups.
    On macOS uses osascript display notification (runs as separate process).
    """

    def __init__(self, event_queue: "queue.Queue | None" = None, callback_port: int | None = None):
        self._event_queue = event_queue
        self._callback_port = callback_port
        self._is_mac = sys.platform == "darwin"
        self._is_win = sys.platform == "win32"

        # macOS: only osascript, no tkinter (NSWindow requires main thread)
        if self._is_mac:
            self._available = True
            self._tk_available = False
            self._tk_queue: queue_module.Queue | None = None
            self._tk_thread: threading.Thread | None = None
            self._tk_root = None
        else:
            self._tk_available = True
            self._available = True
            self._tk_queue: queue_module.Queue = queue_module.Queue()
            self._tk_thread: threading.Thread | None = None
            self._tk_root = None
            self._start_tk_thread()

    def _start_tk_thread(self):
        """Start the dedicated tkinter thread (non-macOS only)."""
        self._tk_thread = threading.Thread(target=self._tk_mainloop, daemon=True)
        self._tk_thread.start()

    def _tk_mainloop(self):
        """Run tkinter mainloop in a dedicated thread."""
        try:
            import tkinter as tk

            self._tk_root = tk.Tk()
            self._tk_root.withdraw()

            def poll():
                try:
                    while True:
                        notif_data = self._tk_queue.get_nowait()
                        self._show_bubble(notif_data)
                except queue_module.Empty:
                    pass
                self._tk_root.after(200, poll)

            self._tk_root.after(200, poll)
            self._tk_root.mainloop()
        except Exception as e:
            logger.error(f"Tkinter thread crashed: {e}")

    def _show_bubble(self, data: dict):
        """Create and show a bubble notification window. Called from tkinter thread."""
        import tkinter as tk

        title = data.get("title", "Chanel Agent")
        message = data.get("message", "")
        quick_replies = data.get("quick_replies", [])
        timeout_ms = data.get("timeout_ms", 60000)

        root = self._tk_root
        if root is None:
            return

        bubble = tk.Toplevel(root)
        bubble.overrideredirect(True)
        bubble.attributes("-topmost", True)

        bg_color = "#1E1E2E"
        accent_color = "#D8B56D"
        text_color = "#F5F1E8"
        button_bg = "#2A3146"
        button_active = "#3A4156"

        bubble.configure(bg=bg_color)

        frame = tk.Frame(bubble, bg=bg_color, padx=16, pady=14)
        frame.pack(fill="both", expand=True)

        title_label = tk.Label(
            frame, text=title, bg=bg_color, fg=accent_color,
            font=("Segoe UI", 11, "bold"), anchor="w",
        )
        title_label.pack(fill="x", pady=(0, 6))

        msg_label = tk.Label(
            frame, text=message, bg=bg_color, fg=text_color,
            font=("Segoe UI", 10), anchor="w", wraplength=320, justify="left",
        )
        msg_label.pack(fill="x", pady=(0, 8))

        if quick_replies:
            btn_frame = tk.Frame(frame, bg=bg_color)
            btn_frame.pack(fill="x", pady=(4, 0))

            for reply_text in quick_replies[:2]:
                def make_callback(rt):
                    def callback():
                        if self._event_queue is not None:
                            self._event_queue.put(("user", f"[bubble-reply] {rt}"))
                        bubble.destroy()
                    return callback

                btn = tk.Button(
                    btn_frame, text=reply_text, bg=button_bg, fg=text_color,
                    activebackground=button_active, activeforeground=text_color,
                    font=("Segoe UI", 9), relief="flat", padx=12, pady=4,
                    cursor="hand2", command=make_callback(reply_text),
                )
                btn.pack(side="left", padx=(0, 8))

        close_btn = tk.Button(
            bubble, text="x", bg=bg_color, fg="#888",
            font=("Segoe UI", 8), relief="flat", bd=0,
            cursor="hand2", command=bubble.destroy,
            activebackground=bg_color, activeforeground=accent_color,
        )
        close_btn.place(x=0, y=0, width=20, height=20)

        bubble.update_idletasks()
        win_width = max(bubble.winfo_reqwidth(), 340)
        win_height = bubble.winfo_reqheight()
        screen_width = bubble.winfo_screenwidth()
        x = screen_width - win_width - 20
        y = 20
        bubble.geometry(f"{win_width}x{win_height}+{x}+{y}")

        # Auto-dismiss after timeout (cancelled on mouse hover)
        close_timer = [None]

        def auto_close():
            try:
                bubble.destroy()
            except Exception:
                pass

        def schedule_close():
            if close_timer[0] is not None:
                bubble.after_cancel(close_timer[0])
            close_timer[0] = bubble.after(timeout_ms, auto_close)

        def pause_close(_event=None):
            if close_timer[0] is not None:
                bubble.after_cancel(close_timer[0])
                close_timer[0] = None

        schedule_close()
        bubble.bind("<Enter>", pause_close)
        bubble.bind("<Leave>", lambda _e: schedule_close())

        try:
            bubble.attributes("-alpha", 0.0)
            for i in range(1, 11):
                bubble.after(i * 20, lambda a=i / 10.0: bubble.attributes("-alpha", a))
        except Exception:
            pass

    def _send_macos(self, title: str, message: str) -> bool:
        """Send macOS native notification via osascript (plain text only)."""
        try:
            import subprocess
            safe_title = title.replace('"', '\\"')
            safe_msg = message.replace('"', '\\"')
            script = f'display notification "{safe_msg}" with title "{safe_title}"'
            subprocess.Popen(
                ["osascript", "-e", script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:
            return False

    def send(
        self,
        title: str,
        message: str,
        duration: str = "long",
        actions: list[dict] | None = None,
    ) -> bool:
        """Send a notification. Non-blocking.

        Args:
            title: Notification title.
            message: Notification body text.
            duration: 'short' (~30s) or 'long' (~60s). Default is long so
                      proactive messages don't disappear before the user notices.
            actions: Optional list of {"label": str, "response": str} dicts.

        Returns:
            True if notification was sent/queued successfully.
        """

        if not self._available:
            return False

        quick_replies = []
        if actions:
            quick_replies = [a.get("label", a.get("response", "")) for a in actions[:2]]

        # macOS: native notification only
        if self._is_mac:
            return self._send_macos(title, message)

        # Windows/Linux: tkinter bubble popup
        if not self._tk_available:
            return False

        timeout_ms = 60000 if duration == "long" else 30000
        self._tk_queue.put({
            "title": title,
            "message": message,
            "quick_replies": quick_replies,
            "timeout_ms": timeout_ms,
        })
        return True

    def send_bubble(self, message: str, quick_replies: list[str] | None = None) -> bool:
        """Send a proactive bubble message with optional quick reply buttons."""
        actions = None
        if quick_replies:
            actions = [{"label": qr, "response": qr} for qr in quick_replies[:2]]
        return self.send("Chanel Agent", message, actions=actions)

    def is_available(self) -> bool:
        return self._available

    def stop(self):
        """Shutdown the notification system."""
        if self._tk_root is not None:
            try:
                self._tk_root.quit()
            except Exception:
                pass