"""Agent core - LLM conversation loop with tool use."""

import sys
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
        """Run one agent turn - may include multiple tool-call loops.

        Tracks whether send_message was actually dispatched during tool calls
        to accurately record the action in the thought chain (fixes the bug
        where the final text-only response has no tool_use blocks to inspect).
        Also captures the LLM's reasoning text from the first response
        (before tool_use blocks) and stores it as inference in the thought chain.
        """
        spoke = False
        spoken_content = ""
        inference = ""

        while True:
            response = self._client.messages.create(
                model=self._model,
                system=self._system,
                messages=self._history,
                tools=self._tools.get_schemas(),
                max_tokens=8000,
            )
            self._history.append({"role": "assistant", "content": response.content})

            # Capture reasoning text from the first response (before tool_use)
            if is_proactive and not inference:
                inference = self._extract_text(response.content)
                if inference:
                    Terminal.info(f"[推理] {inference[:200].replace(chr(10), ' ')}")

            if response.stop_reason != "tool_use":
                text = self._extract_text(response.content).strip()
                if text and not is_proactive:
                    Terminal.agent_response(text)
                # Record action based on actual tool use during this turn,
                # not on the final text-only response (which lacks tool_use blocks)
                if is_proactive:
                    self._memory.record_cycle(
                        observation="(see previous perception)",
                        action="send_message" if spoke else "silent",
                        content=spoken_content,
                        inference=inference,
                    )
                break

            results = []
            for block in response.content:
                if block.type == "tool_use":
                    if block.name == "send_message":
                        spoke = True
                        spoken_content = block.input.get("content", "")
                    output = self._tools.dispatch(block.name, **block.input)
                    Terminal.tool_debug(f"{block.name}: {str(output)[:200]}")
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                    })

            self._history.append({"role": "user", "content": results})

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