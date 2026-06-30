"""User behavior profile - aggregates observation patterns into a persistent user model."""

from .store import MemoryStore


class UserProfile:
    """Builds and maintains a persistent user behavior profile.

    Tracks patterns like common work hours, frequently used applications,
    and interaction preferences to help the agent make better decisions.
    """

    def __init__(self, store: MemoryStore):
        self._store = store

    def update_from_observation(self, observation: str, action: str, content: str):
        """Update profile based on a new observation-action pair. Lightweight heuristic."""
        # Track common apps
        if "ActiveApp:" in observation:
            app_line = [l for l in observation.split("\n") if "ActiveApp:" in l]
            if app_line:
                app_name = app_line[0].split("ActiveApp:")[-1].strip()
                if app_name and app_name != "(unknown)":
                    self._increment_counter(f"app:{app_name}")

        # Track active hours
        if "Time:" in observation:
            time_line = [l for l in observation.split("\n") if "Time:" in l]
            if time_line:
                hour_str = time_line[0].split("Time:")[-1].strip().split(":")[0]
                try:
                    hour = int(hour_str)
                    self._increment_counter(f"active_hour:{hour}")
                except ValueError:
                    pass

        # Track interaction patterns
        if action == "send_message":
            self._increment_counter("total_messages_sent")
        elif action == "silent":
            self._increment_counter("total_silent_wakes")

    def _increment_counter(self, key: str):
        """Increment a counter stored in the profile."""
        current = self._store.get_profile(key)
        count = int(current) + 1 if current else 1
        self._store.set_profile(key, str(count))

    def get_common_apps(self, top_n: int = 5) -> list[tuple[str, int]]:
        """Return the most frequently used applications."""
        all_profile = self._store.get_all_profile()
        apps = [
            (k.replace("app:", ""), int(v))
            for k, v in all_profile.items()
            if k.startswith("app:")
        ]
        apps.sort(key=lambda x: x[1], reverse=True)
        return apps[:top_n]

    def get_peak_hours(self, top_n: int = 3) -> list[int]:
        """Return the most active hours of the day."""
        all_profile = self._store.get_all_profile()
        hours = [
            (int(k.replace("active_hour:", "")), int(v))
            for k, v in all_profile.items()
            if k.startswith("active_hour:")
        ]
        hours.sort(key=lambda x: x[1], reverse=True)
        return [h for h, _ in hours[:top_n]]

    def get_total_messages(self) -> int:
        """Total proactive messages sent."""
        val = self._store.get_profile("total_messages_sent")
        return int(val) if val else 0

    def get_total_silent_wakes(self) -> int:
        """Total silent observation wakes."""
        val = self._store.get_profile("total_silent_wakes")
        return int(val) if val else 0

    def summarize(self) -> str:
        """Build a human-readable profile summary for LLM prompt injection."""
        parts = []

        common_apps = self.get_common_apps(3)
        if common_apps:
            apps_str = ", ".join(f"{app}({cnt})" for app, cnt in common_apps)
            parts.append(f"Common apps: {apps_str}")

        peak_hours = self.get_peak_hours(3)
        if peak_hours:
            hours_str = ", ".join(f"{h}:00" for h in sorted(peak_hours))
            parts.append(f"Peak active hours: {hours_str}")

        total_msgs = self.get_total_messages()
        total_silent = self.get_total_silent_wakes()
        if total_msgs or total_silent:
            parts.append(f"Proactive messages: {total_msgs}, Silent wakes: {total_silent}")

        if not parts:
            return ""

        return "[User Profile] " + " | ".join(parts)