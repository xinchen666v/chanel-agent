"""Agent core - LLM conversation loop with tool use."""

from anthropic import Anthropic

from tools.registry import ToolRegistry
from memory.chain import ThoughtChain
from agent.prompt import PromptBuilder
from ui.terminal import Terminal


class AgentCore:
    """Core agent loop that handles LLM conversations with tool use.

    Manages the conversation history and orchestrates tool calls.
    """

    def __init__(
        self,
        client: Anthropic,
        model: str,
        system_prompt: str,
        tools: ToolRegistry,
        memory: ThoughtChain,
    ):
        self._client = client
        self._model = model
        self._system = system_prompt
        self._tools = tools
        self._memory = memory
        self._history: list = []

    @property
    def history(self) -> list:
        return self._history

    def run_turn(self, is_proactive: bool = False):
        """Run one agent turn - may include multiple tool-call loops."""
        while True:
            response = self._client.messages.create(
                model=self._model,
                system=self._system,
                messages=self._history,
                tools=self._tools.get_schemas(),
                max_tokens=8000,
            )
            self._history.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                text = self._extract_text(response.content).strip()
                if text and not is_proactive:
                    print(text)
                self._record_action_from_response(response, is_proactive)
                break

            results = []
            for block in response.content:
                if block.type == "tool_use":
                    output = self._tools.dispatch(block.name, **block.input)
                    Terminal.tool_debug(f"{block.name}: {str(output)[:200]}")
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                    })

            self._history.append({"role": "user", "content": results})

    def _record_action_from_response(self, response, is_proactive: bool):
        """Record the agent's action in the thought chain."""
        if not is_proactive:
            return  # Only record proactive turns

        # Determine what action was taken
        action = "silent"
        content = ""
        for block in response.content:
            if hasattr(block, "name") and block.name == "send_message":
                action = "send_message"
                content = block.input.get("content", "")
                break

        self._memory.record_cycle(
            observation="(see previous perception)",
            action=action,
            content=content,
        )

    def clear_history(self):
        """Clear conversation history."""
        self._history = []

    @staticmethod
    def _extract_text(content) -> str:
        """Extract text from Anthropic response content blocks."""
        texts = []
        for block in content:
            if hasattr(block, "text"):
                texts.append(block.text)
        return "\n".join(texts)