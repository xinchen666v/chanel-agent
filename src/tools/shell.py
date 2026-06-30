"""Shell command execution tool."""

import subprocess
from pathlib import Path


class Shell:
    """Shell command execution for the agent."""

    DANGEROUS_COMMANDS = [
        "rm -rf /", "sudo", "shutdown", "reboot",
        "> /dev/", "format", "del /f /s",
    ]

    def __init__(self, workdir: Path):
        self._workdir = workdir

    def execute(self, command: str) -> str:
        """Run a shell command in the workspace directory."""
        cmd_lower = command.lower()
        for dangerous in self.DANGEROUS_COMMANDS:
            if dangerous in cmd_lower:
                raise ValueError(f"Command blocked: {dangerous}")

        try:
            r = subprocess.run(
                command,
                shell=True,
                cwd=self._workdir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
            out = (r.stdout + r.stderr).strip()
            return out[:50000] if out else "(no output)"
        except subprocess.TimeoutExpired:
            return "Error: Timeout (120s)"
        except Exception as e:
            return f"Error: {e}"