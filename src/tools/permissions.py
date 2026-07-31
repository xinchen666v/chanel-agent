"""Permission gate for tool execution.

Design borrowed from s03_permission:
- Three-stage pipeline before any tool runs:
  1. Hard deny list (e.g. rm -rf /, sudo, shutdown)
  2. Rule matching (e.g. write outside workspace, destructive bash)
  3. User approval when a rule matched
- If none of the stages block, the tool is allowed.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Callable


class PermissionDecision(str, Enum):
    """Result of the permission check."""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class PermissionGate:
    """Decide whether a tool call should run, be blocked, or ask the user."""

    # Substring patterns that are always denied for bash.
    DENY_LIST = [
        "rm -rf /",
        "sudo",
        "shutdown",
        "reboot",
        "mkfs",
        "dd if=",
        "> /dev/sda",
        # Windows-specific destructive patterns
        "rd /s c:\\",
        "format c:",
        "del /f /s /q c:\\",
    ]

    def __init__(
        self,
        workdir: Path,
        prompt_func: Callable[[str], str] | None = None,
    ):
        self._workdir = workdir.resolve()
        self._prompt_func = prompt_func

    def check(self, tool_name: str, args: dict) -> tuple[PermissionDecision, str]:
        """Run the three-stage permission pipeline.

        Returns:
            (decision, reason). decision is ALLOW/DENY/ASK; reason is empty
            when ALLOW, a block message when DENY, and a question message
            when ASK.
        """
        # Gate 1: hard deny list (bash only in the basic setup)
        if tool_name == "bash":
            command = args.get("command", "")
            for pattern in self.DENY_LIST:
                if pattern in command:
                    return (
                        PermissionDecision.DENY,
                        f"Blocked: '{pattern}' is on the deny list",
                    )

        # Gate 2: rule matching
        reason = self._check_rules(tool_name, args)
        if reason:
            return PermissionDecision.ASK, reason

        return PermissionDecision.ALLOW, ""

    def _check_rules(self, tool_name: str, args: dict) -> str:
        """Return a human-readable reason if a rule matched, else empty."""
        # Files must stay inside the workspace.
        if tool_name in ("write_file", "edit_file"):
            path = args.get("path", "")
            try:
                target = (self._workdir / path).resolve()
                if not target.is_relative_to(self._workdir):
                    return f"Writing outside workspace: {path}"
            except Exception:
                return f"Invalid path: {path}"

        # Potentially destructive bash commands need confirmation.
        if tool_name == "bash":
            command = args.get("command", "")
            destructive_keywords = [
                "rm ",
                "> /etc/",
                "chmod 777",
                "rmdir ",
                "rd /s",
                "del /f",
                "format ",
            ]
            for kw in destructive_keywords:
                if kw in command:
                    return f"Potentially destructive command: {command.strip()}"

        return ""

    def pre_tool_use_hook(self, block) -> str | None:
        """Hook adapter: returns a denial message or None to allow.

        This lets the permission gate be registered as a PreToolUse hook
        without hard-coding permission logic into the agent loop.
        """
        decision, reason = self.check(block.name, block.input)
        if decision == PermissionDecision.DENY:
            return f"Permission denied: {reason}"
        if decision == PermissionDecision.ASK:
            if self.ask_user(block.name, block.input, reason):
                return None
            return "Permission denied by user."
        return None

    def ask_user(self, tool_name: str, args: dict, reason: str) -> bool:
        """Prompt the user to allow or deny a matched rule.

        If no prompt function is available (e.g. TUI mode where synchronous
        input is not supported), the operation is denied by default.
        """
        if self._prompt_func is None:
            return False

        print(f"\n⚠  {reason}")
        print(f"   Tool: {tool_name}({args})")
        choice = self._prompt_func("Allow? [y/N] ").strip().lower()
        return choice in ("y", "yes")
