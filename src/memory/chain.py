"""Thought chain recording and retrieval - the structured memory of observation→inference→action→outcome cycles."""

import uuid
from .store import MemoryStore
from .profile import UserProfile


class ThoughtChain:
    """Manages the cognitive memory loop: Observation → Inference → Action → Outcome.

    Each agent wake cycle produces one thought chain. Chains are persisted
    to SQLite and can be retrieved for context injection into future prompts.
    """

    def __init__(self, store: MemoryStore, profile: UserProfile):
        self._store = store
        self._profile = profile
        self._session_id: str | None = None

    def ensure_session(self) -> str:
        """Get or create the current session ID."""
        if self._session_id is None:
            active = self._store.get_active_session_id()
            self._session_id = active or self._store.start_session()
        return self._session_id

    def record_observation(self, observation_text: str) -> str:
        """Record the observation step. Returns chain_id for later steps."""
        chain_id = uuid.uuid4().hex[:8]
        self._store.record_chain(
            chain_id=chain_id,
            session_id=self.ensure_session(),
            observation=observation_text,
        )
        return chain_id

    def record_cycle(
        self,
        observation: str,
        action: str,
        content: str = "",
        inference: str = "",
    ):
        """Record a complete observation→action cycle in one call."""
        chain_id = uuid.uuid4().hex[:8]
        self._store.record_chain(
            chain_id=chain_id,
            session_id=self.ensure_session(),
            observation=observation,
            inference=inference,
            action=action,
            content=content,
        )
        self._update_profile(observation, action, content)

    def get_context_for_llm(self, limit: int = 5) -> str:
        """Build a context string from recent thought chains for LLM prompt injection.

        Now includes the inference (reasoning) text for each entry, creating
        a complete observation → inference → action → outcome chain.
        """
        chains = self._store.get_recent_chains(self.ensure_session(), limit=limit)
        if not chains:
            return ""

        lines = ["[Previous Observations]"]
        for c in chains:
            time_str = c.get("timestamp", "unknown")
            action = c.get("action", "silent")
            content = c.get("content", "")
            inference = c.get("inference", "")

            line = f"  {time_str}: "
            if action == "send_message" and content:
                line += f"Spoke → \"{content}\""
            elif action == "silent":
                line += "Observed, stayed silent"
            else:
                line += f"Action: {action}"

            if inference:
                # Truncate long inference to keep context concise
                inf = inference[:120].replace("\n", " ")
                line += f"\n            ↳ 推理: {inf}"

            lines.append(line)
        return "\n".join(lines)

    def get_profile_context(self) -> str:
        """Build a profile summary for LLM prompt injection."""
        return self._profile.summarize()

    def get_silent_streak(self) -> int:
        """How many consecutive wake cycles have been silent (no send_message)."""
        return self._store.get_silent_streak(self.ensure_session())

    def end_session(self, summary: str = ""):
        """Close the current session."""
        if self._session_id:
            self._store.end_session(self._session_id, summary)
            self._session_id = None

    def _update_profile(self, observation: str, action: str, content: str):
        """Update user profile based on the latest observation."""
        self._profile.update_from_observation(observation, action, content)