"""Task-level feedback bank.

Associates user feedback with task types and artifacts, so the agent can
learn style preferences per task (e.g. "write README", "refactor code")
instead of losing feedback in generic conversation history.

Storage layout:
    data/memory/feedback/
    ├── write_readme.md
    ├── refactor_code.md
    └── ...

Each file is a markdown file with YAML frontmatter plus a list of feedback
entries grouped under `## <timestamp> | <artifact>` headings.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Literal


Rating = Literal["positive", "neutral", "negative"]

VALID_RATINGS: tuple[str, ...] = ("positive", "neutral", "negative")


class FeedbackEntry:
    """A single feedback record."""

    def __init__(
        self,
        timestamp: str,
        artifact: str,
        request_summary: str,
        feedback: str,
        rating: str,
        style_notes: str,
    ):
        self.timestamp = timestamp
        self.artifact = artifact
        self.request_summary = request_summary
        self.feedback = feedback
        self.rating = rating
        self.style_notes = style_notes

    def to_markdown(self) -> str:
        lines = [
            f"## {self.timestamp} | {self.artifact}",
            "",
            f"- 原始需求摘要：{self.request_summary}",
            f"- 用户反馈：{self.feedback}",
            f"- 评分：{self.rating}",
        ]
        if self.style_notes:
            lines.append(f"- 风格摘要：{self.style_notes}")
        return "\n".join(lines)


class FeedbackBank:
    """File-based task feedback storage."""

    def __init__(self, feedback_dir: Path):
        self._dir = feedback_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        task_type: str,
        artifact: str,
        request_summary: str,
        feedback: str,
        rating: str = "neutral",
        style_notes: str = "",
    ) -> str:
        """Record feedback for a task type, creating or updating its file."""
        task_type = self._safe_name(task_type)
        if rating not in VALID_RATINGS:
            return f"Error: invalid rating '{rating}'. Valid: {', '.join(VALID_RATINGS)}"

        path = self._dir / f"{task_type}.md"
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        entries = self._load_entries(path) if path.exists() else []
        entries.append(
            FeedbackEntry(
                timestamp=now,
                artifact=artifact,
                request_summary=request_summary,
                feedback=feedback,
                rating=rating,
                style_notes=style_notes,
            )
        )

        self._save(path, task_type, entries)
        return f"Recorded feedback for [{task_type}] ({rating})."

    def get(self, task_type: str, top_k: int = 3) -> str:
        """Return the most recent feedback entries for a task type."""
        task_type = self._safe_name(task_type)
        path = self._dir / f"{task_type}.md"
        if not path.exists():
            return f"No feedback recorded yet for task type '{task_type}'."

        entries = self._load_entries(path)
        if not entries:
            return f"Feedback file exists for '{task_type}' but contains no entries."

        recent = entries[-top_k:]
        lines = [
            f"Feedback history for '{task_type}' (last {len(recent)} entries):",
            "",
        ]
        for entry in recent:
            lines.append(entry.to_markdown())
            lines.append("")

        return "\n".join(lines).strip()

    def search(self, keyword: str, limit: int = 5) -> str:
        """Search feedback entries across all task types."""
        keyword_lower = keyword.lower()
        matches: list[tuple[str, FeedbackEntry]] = []

        for path in self._dir.glob("*.md"):
            task_type = path.stem
            for entry in self._load_entries(path):
                text = (
                    entry.artifact
                    + " "
                    + entry.request_summary
                    + " "
                    + entry.feedback
                    + " "
                    + entry.style_notes
                ).lower()
                if keyword_lower in text:
                    matches.append((task_type, entry))

        if not matches:
            return f"No feedback entries matched '{keyword}'."

        matches.sort(key=lambda m: m[1].timestamp, reverse=True)
        lines = [f"Feedback entries matching '{keyword}':"]
        for task_type, entry in matches[:limit]:
            lines.append(
                f"- [{task_type}] {entry.timestamp} | {entry.artifact}: "
                f"{entry.feedback[:80]}..."
            )
        return "\n".join(lines)

    # ── Internal helpers ──

    @staticmethod
    def _safe_name(name: str) -> str:
        """Make a filesystem-safe name from a task type."""
        safe = re.sub(r"[^\w\-]+", "_", name).strip("_").lower()
        return safe or "unknown"

    def _load_entries(self, path: Path) -> list[FeedbackEntry]:
        """Parse a feedback markdown file into entries."""
        text = path.read_text(encoding="utf-8")
        # Strip frontmatter
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                body = parts[2]
            else:
                body = text
        else:
            body = text

        entries: list[FeedbackEntry] = []
        current_lines: list[str] = []
        current_heading: str | None = None

        def _flush():
            if current_heading is None or not current_lines:
                return
            heading_parts = current_heading.split(" | ", 1)
            timestamp = heading_parts[0].strip()
            artifact = heading_parts[1].strip() if len(heading_parts) > 1 else ""

            fields = {
                "request_summary": "",
                "feedback": "",
                "rating": "neutral",
                "style_notes": "",
            }
            for line in current_lines:
                stripped = line.strip()
                for key in fields:
                    prefix = f"- {key_map(key)}："
                    if stripped.startswith(prefix):
                        fields[key] = stripped[len(prefix):].strip()

            entries.append(
                FeedbackEntry(
                    timestamp=timestamp,
                    artifact=artifact,
                    request_summary=fields["request_summary"],
                    feedback=fields["feedback"],
                    rating=fields["rating"],
                    style_notes=fields["style_notes"],
                )
            )

        for line in body.splitlines():
            if line.startswith("## "):
                _flush()
                current_heading = line[3:].strip()
                current_lines = []
            elif current_heading is not None:
                current_lines.append(line)

        _flush()
        return entries

    def _save(self, path: Path, task_type: str, entries: list[FeedbackEntry]) -> None:
        """Rewrite the feedback file with frontmatter and all entries."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [
            "---",
            f"task_type: {task_type}",
            f"count: {len(entries)}",
            f"last_updated: {now}",
            "---",
            "",
            f"# Feedback: {task_type}",
            "",
        ]
        for entry in entries:
            lines.append(entry.to_markdown())
            lines.append("")

        path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def key_map(internal_key: str) -> str:
    """Map internal field keys to the Chinese labels used in markdown."""
    return {
        "request_summary": "原始需求摘要",
        "feedback": "用户反馈",
        "rating": "评分",
        "style_notes": "风格摘要",
    }.get(internal_key, internal_key)
