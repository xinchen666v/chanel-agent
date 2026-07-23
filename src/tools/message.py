"""Message tool - allows the LLM to proactively send messages to the user."""

from ui.terminal import Terminal
from ui.notification import Notifier


class MessageTool:
    """Tool wrapper for sending proactive messages to the user.

    Sends to both terminal (for inline visibility) and platform notification
    (Windows toast / macOS Notification Center / Linux bubble) with optional
    quick replies routed via the callback server.
    """

    def __init__(self, notifier: Notifier):
        self._notifier = notifier

    def handle(self, content: str, quick_replies: list[str] | None = None) -> str:
        """Send a proactive message via terminal and system notification.

        Args:
            content: The message body.
            quick_replies: Optional list of 1-2 short reply strings. When provided,
                           the notification includes quick-reply options that route
                           the reply back to the agent via the callback server.
        """
        Terminal.agent_message(content)
        self._notifier.send_bubble(content, quick_replies=quick_replies)

        if quick_replies:
            replies_str = ", ".join(quick_replies)
            return f"Delivered (with quick replies: {replies_str})."
        return "Delivered."