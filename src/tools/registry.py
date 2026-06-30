"""Tool registry - manages tool definitions, schemas, and dispatch."""

from dataclasses import dataclass, field
from typing import Callable, Any


@dataclass
class Tool:
    """A tool that the LLM agent can invoke."""

    name: str
    description: str
    input_schema: dict
    handler: Callable[..., str]


class ToolRegistry:
    """Registry of all available tools.

    Provides Anthropic-compatible tool schemas and dispatches
    tool calls to the appropriate handler.
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        """Register a new tool."""
        self._tools[tool.name] = tool

    def get_schemas(self) -> list[dict]:
        """Return Anthropic-compatible tool schemas."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in self._tools.values()
        ]

    def dispatch(self, name: str, **kwargs) -> str:
        """Dispatch a tool call to the appropriate handler."""
        tool = self._tools.get(name)
        if tool is None:
            return f"Unknown tool: {name}"
        try:
            return tool.handler(**kwargs)
        except Exception as e:
            return f"Tool error ({name}): {e}"

    def get_tool_names(self) -> list[str]:
        """Return all registered tool names."""
        return list(self._tools.keys())