"""Memory management tool - allows the LLM to create/update/delete long-term memories.

Memories are stored as markdown files in data/memory/ with YAML frontmatter.
This gives the agent a persistent, human-readable, LLM-writable memory layer
that survives context compression and cross-session resets.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memory.bank import MemoryBank


class MemoryManageTool:
    """Tool wrapper for managing long-term memory files."""

    def __init__(self, memory_bank: MemoryBank):
        self._bank = memory_bank

    def handle(
        self,
        action: str,
        name: str = "",
        description: str = "",
        content: str = "",
        type: str = "reference",
        tags: list[str] | None = None,
        mode: str = "replace",
    ) -> str:
        """Manage long-term memories.

        Args:
            action: 'create', 'update', 'delete', or 'load'.
            name: Memory identifier (used as filename). Keep it short and kebab-case.
            description: Short summary shown in MEMORY.md index.
            content: Full memory body (markdown).
            type: One of user/feedback/project/reference/agent.
            tags: Optional list of tags.
            mode: For update: 'replace' or 'append'.

        Returns:
            Status message with the result.
        """
        action = action.lower()
        tags = tags or []

        try:
            if action == "create":
                if not name:
                    return "Error: 'name' is required for create."
                if not content:
                    return "Error: 'content' is required for create."
                return self._bank.create(
                    name=name,
                    description=description or name,
                    content=content,
                    type=type,
                    tags=tags,
                )

            elif action == "update":
                if not name:
                    return "Error: 'name' is required for update."
                if not content:
                    return "Error: 'content' is required for update."
                return self._bank.update(name, content, mode=mode)

            elif action == "delete":
                if not name:
                    return "Error: 'name' is required for delete."
                return self._bank.delete(name)

            elif action == "load":
                if not name:
                    return "Error: 'name' is required for load."
                return self._bank.load(name)

            else:
                return (
                    f"Unknown action '{action}'. Valid: create, update, delete, load.\n"
                    "Example: manage_memory(action='create', name='project-chanel', "
                    "description='Chanel Agent project context', "
                    "content='User is building...', type='project')"
                )
        except Exception as e:
            return f"Memory manage error: {e}"
