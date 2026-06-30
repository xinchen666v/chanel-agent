"""File operation tools: read, write, edit."""

from pathlib import Path


class FileOps:
    """File read/write/edit operations for the agent."""

    def __init__(self, workdir: Path):
        self._workdir = workdir

    def _safe_path(self, path: str) -> Path:
        """Resolve path and ensure it stays within the workspace."""
        resolved = (self._workdir / path).resolve()
        if not str(resolved).startswith(str(self._workdir.resolve())):
            raise ValueError(f"Path escapes workspace: {path}")
        return resolved

    def read(self, path: str, limit: int | None = None) -> str:
        """Read file contents."""
        try:
            text = self._safe_path(path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = self._safe_path(path).read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return f"Error: File not found: {path}"
        except Exception as e:
            return f"Error: {e}"

        lines = text.splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)[:50000]

    def write(self, path: str, content: str) -> str:
        """Write content to file."""
        try:
            fp = self._safe_path(path)
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
            return f"Wrote {len(content)} bytes to {path}"
        except Exception as e:
            return f"Error: {e}"

    def edit(self, path: str, old_text: str, new_text: str) -> str:
        """Replace exact text in file."""
        try:
            fp = self._safe_path(path)
            content = fp.read_text(encoding="utf-8")
            if old_text not in content:
                return f"Error: Text not found in {path}"
            fp.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
            return f"Edited {path}"
        except Exception as e:
            return f"Error: {e}"