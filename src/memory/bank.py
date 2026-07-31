"""Memory bank - file-based long-term memory inspired by s09_memory.

Core idea: "压缩会丢细节，要有一层不丢的".
- Each memory is a standalone .md file with YAML frontmatter.
- MEMORY.md serves as an index, kept small enough to live in SYSTEM prompt.
- Full memory content is loaded on demand into the current user turn.

Memory types:
    user      - 用户是谁、偏好、身份、稳定特征
    feedback  - 怎么做事、用户的反馈、纠正
    project   - 正在发生什么、项目上下文
    reference - 东西在哪找、参考信息
    agent     - Agent 自己的配置、经验、学到的策略
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal


MemoryType = Literal["user", "feedback", "project", "reference", "agent"]

VALID_TYPES: tuple[str, ...] = ("user", "feedback", "project", "reference", "agent")


@dataclass
class Memory:
    """A single memory entry backed by a markdown file."""

    name: str
    description: str
    type: MemoryType
    tags: list[str]
    updated_at: str
    content: str

    def to_frontmatter(self) -> str:
        """Serialize metadata to YAML frontmatter."""
        tags_line = ", ".join(self.tags) if self.tags else ""
        return (
            "---\n"
            f"name: {self.name}\n"
            f"description: {self.description}\n"
            f"type: {self.type}\n"
            f"tags: {tags_line}\n"
            f"updated_at: {self.updated_at}\n"
            "---\n"
        )

    def to_file_text(self) -> str:
        """Full file content: frontmatter + body."""
        return self.to_frontmatter() + "\n" + self.content.lstrip("\n")


class MemoryBank:
    """File-based memory bank.

    Directory layout:
        data/memory/
        ├── MEMORY.md          (index, injected into SYSTEM prompt)
        ├── user_profile.md    (aggregated user behavior + semantic sections)
        ├── user-preference-tabs.md
        ├── project-chanel-agent.md
        └── ...
    """

    def __init__(self, memory_dir: Path):
        self._dir = memory_dir
        self._index_path = self._dir / "MEMORY.md"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ensure_index()

    # ── Public API ──

    def create(
        self,
        name: str,
        description: str,
        content: str,
        type: str,
        tags: list[str] | None = None,
        append_if_exists: bool = False,
    ) -> str:
        """Create a new memory file. Optionally append if it already exists."""
        safe_name = self._safe_name(name)
        if type not in VALID_TYPES:
            return f"Error: invalid type '{type}'. Valid: {', '.join(VALID_TYPES)}"

        file_path = self._dir / f"{safe_name}.md"
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        if file_path.exists() and append_if_exists:
            return self.update(safe_name, content, mode="append")

        if file_path.exists():
            return (
                f"Error: memory '{safe_name}' already exists. "
                f"Use update(name='{safe_name}', ...) to modify it."
            )

        memory = Memory(
            name=safe_name,
            description=description,
            type=type,  # type: ignore[arg-type]
            tags=tags or [],
            updated_at=now,
            content=content,
        )
        file_path.write_text(memory.to_file_text(), encoding="utf-8")
        self._rebuild_index()
        return f"Created memory [{safe_name}] ({type})."

    def update(self, name: str, content: str, mode: str = "replace") -> str:
        """Update an existing memory.

        mode:
            replace - overwrite the content body
            append  - append to the content body with a timestamp header
        """
        safe_name = self._safe_name(name)
        file_path = self._dir / f"{safe_name}.md"
        if not file_path.exists():
            return f"Error: memory '{safe_name}' not found. Use create(...) first."

        memory = self._load_memory(file_path)
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        memory.updated_at = now

        if mode == "append":
            memory.content = (
                memory.content.rstrip("\n")
                + f"\n\n## Update @ {now}\n\n"
                + content.lstrip("\n")
            )
        else:
            memory.content = content

        file_path.write_text(memory.to_file_text(), encoding="utf-8")
        self._rebuild_index()
        return f"Updated memory [{safe_name}] ({mode})."

    def delete(self, name: str) -> str:
        """Delete a memory file."""
        safe_name = self._safe_name(name)
        file_path = self._dir / f"{safe_name}.md"
        if not file_path.exists():
            return f"Error: memory '{safe_name}' not found."
        file_path.unlink()
        self._rebuild_index()
        return f"Deleted memory [{safe_name}]."

    def load(self, name: str) -> str:
        """Load full content of a memory (frontmatter + body)."""
        safe_name = self._safe_name(name)
        file_path = self._dir / f"{safe_name}.md"
        if not file_path.exists():
            return f"Error: memory '{safe_name}' not found."
        memory = self._load_memory(file_path)
        return memory.to_file_text()

    def list_index(self) -> str:
        """Return the MEMORY.md index content (for SYSTEM prompt injection)."""
        if not self._index_path.exists():
            self._rebuild_index()
        return self._index_path.read_text(encoding="utf-8")

    def search(self, keyword: str, limit: int = 5) -> str:
        """Search memories by keyword in name/description/content."""
        keyword_lower = keyword.lower()
        matches: list[tuple[Path, int]] = []

        for path in self._dir.glob("*.md"):
            if path.name == "MEMORY.md":
                continue
            text = path.read_text(encoding="utf-8").lower()
            score = text.count(keyword_lower)
            if score > 0 or keyword_lower in path.stem.lower():
                matches.append((path, max(score, 1)))

        matches.sort(key=lambda x: x[1], reverse=True)
        if not matches:
            return f"No memories matched '{keyword}'."

        lines = [f"Memories matching '{keyword}':"]
        for path, _ in matches[:limit]:
            memory = self._load_memory(path)
            lines.append(
                f"- [{memory.name}] ({memory.type}): {memory.description}"
            )
        return "\n".join(lines)

    def get_relevant_memories(
        self,
        query: str,
        perception_text: str = "",
        top_k: int = 3,
    ) -> str:
        """Return the full text of the most relevant memories for the current turn.

        Simple keyword overlap ranking. Future: embedding-based retrieval.
        """
        query_lower = query.lower()
        perception_lower = perception_text.lower()

        candidates: list[tuple[Path, int]] = []
        for path in self._dir.glob("*.md"):
            if path.name == "MEMORY.md":
                continue
            text = path.read_text(encoding="utf-8").lower()
            # Simple scoring: count occurrences of query words in memory
            score = 0
            for word in re.findall(r"\b\w+\b", query_lower):
                if len(word) > 2:
                    score += text.count(word)
            for word in re.findall(r"\b\w+\b", perception_lower):
                if len(word) > 2:
                    score += text.count(word)
            if score > 0:
                candidates.append((path, score))

        candidates.sort(key=lambda x: x[1], reverse=True)
        if not candidates:
            return ""

        parts = []
        for path, _ in candidates[:top_k]:
            memory = self._load_memory(path)
            parts.append(
                f"<!-- memory: {memory.name} -->\n{memory.to_file_text()}"
            )
        return "\n\n---\n\n".join(parts)

    # ── Internal helpers ──

    def _ensure_index(self):
        """Create MEMORY.md if it doesn't exist."""
        if not self._index_path.exists():
            self._rebuild_index()

    def _rebuild_index(self):
        """Regenerate MEMORY.md from all memory files."""
        lines = [
            "# Memory Index",
            "",
            "This file lists all long-term memories. It is kept compact for prompt injection.",
            "Full memory content is loaded on demand into the current conversation.",
            "",
            "| Name | Type | Description | Updated |",
            "|------|------|-------------|---------|",
        ]

        for path in sorted(self._dir.glob("*.md")):
            if path.name == "MEMORY.md":
                continue
            memory = self._load_memory(path)
            lines.append(
                f"| {memory.name} | {memory.type} | {memory.description} | {memory.updated_at} |"
            )

        if len(lines) <= 6:
            lines.append("| _(no memories yet)_ | - | - | - |")

        self._index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _load_memory(self, path: Path) -> Memory:
        """Parse a memory markdown file."""
        text = path.read_text(encoding="utf-8")

        # Parse YAML frontmatter between --- markers
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                fm = parts[1]
                body = parts[2]
            else:
                fm = ""
                body = text
        else:
            fm = ""
            body = text

        def get(key: str, default: str = "") -> str:
            match = re.search(rf"^{key}\s*:\s*(.*)$", fm, re.MULTILINE)
            return match.group(1).strip() if match else default

        name = get("name", path.stem)
        description = get("description", "")
        type_str = get("type", "reference")
        if type_str not in VALID_TYPES:
            type_str = "reference"

        tags_str = get("tags", "").strip()
        # Tolerate both "a, b" and "[a, b]" from older files
        if tags_str.startswith("[") and tags_str.endswith("]"):
            tags_str = tags_str[1:-1]
        tags = [t.strip() for t in tags_str.split(",") if t.strip()]

        updated_at = get("updated_at", "")

        return Memory(
            name=name,
            description=description,
            type=type_str,  # type: ignore[arg-type]
            tags=tags,
            updated_at=updated_at,
            content=body.strip(),
        )

    @staticmethod
    def _safe_name(name: str) -> str:
        """Make a filesystem-safe name."""
        safe = re.sub(r"[^\w\-]", "-", name).strip("-")
        safe = re.sub(r"-+", "-", safe)
        return safe or "memory"
