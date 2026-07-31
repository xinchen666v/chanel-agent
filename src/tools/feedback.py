"""Feedback tools - let the agent record and retrieve task-level feedback.

These tools expose the FeedbackBank to the LLM so it can:
  - record_feedback: store user feedback tied to a task type and artifact
  - get_feedback: look up past feedback before doing a similar task again
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memory.feedback import FeedbackBank


class FeedbackTool:
    """Tool wrapper for task-level feedback storage."""

    def __init__(self, bank: "FeedbackBank"):
        self._bank = bank

    def handle_record(
        self,
        task_type: str,
        artifact: str,
        request_summary: str,
        feedback: str,
        rating: str = "neutral",
        style_notes: str = "",
    ) -> str:
        """Record feedback for a completed task.

        Args:
            task_type: Task category, e.g. 'write_readme', 'refactor_code'.
            artifact: Path or name of the produced artifact.
            request_summary: Short summary of what the user originally asked.
            feedback: The user's actual feedback text.
            rating: 'positive' | 'neutral' | 'negative'.
            style_notes: Extracted actionable style preference.
        """
        if not task_type or not feedback:
            return "Error: 'task_type' and 'feedback' are required."
        return self._bank.record(
            task_type=task_type,
            artifact=artifact,
            request_summary=request_summary,
            feedback=feedback,
            rating=rating,
            style_notes=style_notes,
        )

    def handle_get(self, task_type: str, top_k: int = 3) -> str:
        """Get recent feedback entries for a task type."""
        if not task_type:
            return "Error: 'task_type' is required."
        return self._bank.get(task_type, top_k=top_k)

    def handle_search(self, keyword: str, limit: int = 5) -> str:
        """Search feedback entries by keyword across all task types."""
        if not keyword:
            return "Error: 'keyword' is required."
        return self._bank.search(keyword, limit=limit)
