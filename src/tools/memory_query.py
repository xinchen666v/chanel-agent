"""Memory query tool - allows the LLM to inspect its own thought chains and user profile.

Query types:
  - recent_chains: Recent thought chains WITH observation details (window, app, idle, time)
  - search_observations: Search observations by keyword (e.g. "Trae", "VSCode")
  - timeline: Recent observations as a readable timeline
  - session_stats: Current session statistics
  - profile_get: Get a specific user profile key
  - profile_all: Get all user profile entries
  - chain_detail: Get full detail of a specific thought chain
"""

import json
from memory.store import MemoryStore


class MemoryQueryTool:
    """Tool wrapper for querying the agent's own SQLite memory store.

    This is the PREFERRED way to query agent memory. Do NOT use bash/sqlite3
    to query the database directly - always use this tool.
    """

    def __init__(self, store: MemoryStore):
        self._store = store

    def handle(self, query_type: str, key: str = "", keyword: str = "", limit: int = 10) -> str:
        """Query agent memory.

        Args:
            query_type: One of:
                - 'recent_chains': Recent chains with full observation details
                - 'search_observations': Search by keyword in window/app/message
                - 'timeline': Readable timeline of recent observations
                - 'session_stats': Current session statistics
                - 'profile_get': Get specific profile key (requires 'key')
                - 'profile_all': Get all profile entries
                - 'chain_detail': Get full chain by chain_id (requires 'key')
            key: Profile key (for profile_get) or chain_id (for chain_detail).
            keyword: Search keyword (for search_observations).
            limit: Max rows to return.
        """
        try:
            if query_type == "recent_chains":
                return self._recent_chains(limit)

            elif query_type == "search_observations":
                if not keyword:
                    return "Error: 'keyword' is required for search_observations. Example: keyword='Trae'"
                return self._search_observations(keyword, limit)

            elif query_type == "timeline":
                return self._timeline(limit)

            elif query_type == "session_stats":
                return self._session_stats()

            elif query_type == "profile_get":
                if not key:
                    return "Error: 'key' is required for profile_get."
                return self._profile_get(key)

            elif query_type == "profile_all":
                return self._profile_all()

            elif query_type == "chain_detail":
                if not key:
                    return "Error: 'key' (chain_id) is required for chain_detail."
                return self._chain_detail(key)

            else:
                return self._help()

        except Exception as e:
            return f"Memory query error: {e}"

    def _recent_chains(self, limit: int) -> str:
        """Recent chains with full observation details."""
        summaries = self._store.get_observation_field_summary()
        if not summaries:
            return "No thought chains recorded yet."
        summaries = summaries[-limit:]  # Most recent N
        lines = ["Recent thought chains (with observation details):"]
        for s in summaries:
            ts = s["timestamp"]
            win = s["window_title"]
            app = s["app_name"]
            idle = s["idle_seconds"]
            hour = s["hour_of_day"]
            action = s["action"]
            content = s["content"]
            if action == "send_message" and content:
                lines.append(f"  {ts} | {app} | idle={idle}s | hour={hour} | SPOKE: {content}")
            elif action:
                lines.append(f"  {ts} | {app} | idle={idle}s | hour={hour} | {action}")
            else:
                lines.append(f"  {ts} | {app} | idle={idle}s | hour={hour} | (no action)")
        return "\n".join(lines)

    def _search_observations(self, keyword: str, limit: int) -> str:
        """Search observations by keyword."""
        results = self._store.search_observations(keyword, limit=limit)
        if not results:
            return f"No observations found containing '{keyword}'."
        lines = [f"Found {len(results)} observations matching '{keyword}':"]
        for r in results:
            ts = r["timestamp"]
            action = r["action"] or "(no action)"
            content = r["content"] or ""
            try:
                obs = json.loads(r["observation"])
                win = obs.get("active_window_title", "?")
                app = obs.get("active_app_name", "?")
            except (json.JSONDecodeError, TypeError):
                win = "?"
                app = "?"
            line = f"  {ts} | {app} | {win} | {action}"
            if content:
                line += f" | msg: {content}"
            lines.append(line)
        return "\n".join(lines)

    def _timeline(self, limit: int) -> str:
        """Readable timeline of recent observations."""
        summaries = self._store.get_observation_field_summary()
        if not summaries:
            return "No observations recorded yet."
        summaries = summaries[-limit:]
        lines = [f"Observation timeline (last {len(summaries)} entries):"]
        for s in summaries:
            ts = s["timestamp"]
            app = s["app_name"]
            win = s["window_title"]
            idle = s["idle_seconds"]
            hour = s["hour_of_day"]
            action = s["action"] or "(observe)"
            content = s["content"]
            line = f"  [{ts}] {app}"
            if win and win != "?":
                line += f" ({win})"
            line += f" | idle={idle}s | {action}"
            if content:
                line += f": {content}"
            lines.append(line)
        return "\n".join(lines)

    def _session_stats(self) -> str:
        session_id = self._store.get_active_session_id()
        if not session_id:
            return "No active session."
        stats = self._store.get_session_stats(session_id)
        return (
            f"Session stats: "
            f"total_wakes={stats['total_wakes']}, "
            f"messages_sent={stats['messages_sent']}, "
            f"silent_wakes={stats['silent_wakes']}"
        )

    def _profile_get(self, key: str) -> str:
        value = self._store.get_profile(key)
        return f"{key}={value}" if value else f"No profile entry for '{key}'."

    def _profile_all(self) -> str:
        profile = self._store.get_all_profile()
        if not profile:
            return "No profile entries yet."
        lines = [f"  {k}={v}" for k, v in profile.items()]
        return "User profile:\n" + "\n".join(lines)

    def _chain_detail(self, chain_id: str) -> str:
        detail = self._store.get_chain_detail(chain_id)
        if not detail:
            return f"No chain found with id '{chain_id}'."
        lines = [f"Chain detail (id={detail['id']}):"]
        lines.append(f"  chain_id: {detail['chain_id']}")
        lines.append(f"  session_id: {detail['session_id']}")
        lines.append(f"  timestamp: {detail['timestamp']}")
        lines.append(f"  observation: {detail['observation']}")
        lines.append(f"  inference: {detail['inference']}")
        lines.append(f"  action: {detail['action']}")
        lines.append(f"  content: {detail['content']}")
        lines.append(f"  outcome: {detail['outcome']}")
        return "\n".join(lines)

    def _help(self) -> str:
        return (
            "Unknown query_type. Valid options:\n"
            "  - recent_chains: Recent chains with observation details\n"
            "  - search_observations: Search by keyword (pass 'keyword' param)\n"
            "  - timeline: Readable observation timeline\n"
            "  - session_stats: Current session statistics\n"
            "  - profile_get: Get specific profile key (pass 'key' param)\n"
            "  - profile_all: Get all profile entries\n"
            "  - chain_detail: Get full chain detail (pass 'key' param)"
        )