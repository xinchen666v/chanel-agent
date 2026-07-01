"""User behavior profile - persisted as a markdown file.

Replaces the old SQLite key-value approach with a human-readable markdown file
that the LLM can also update via the update_profile tool.

Auto-tracked sections (app usage, active hours) are updated from perception data.
Semantic sections (about me, projects, preferences) are updated by the LLM.
"""

from pathlib import Path
from datetime import datetime


class UserProfile:
    """Builds and maintains a persistent user behavior profile.

    Stores data in data/user_profile.md:
      - App Usage: auto-tracked from perception snapshots
      - Active Hours: auto-tracked from perception snapshots
      - About Me / Projects / Preferences: updated by LLM via tool
    """

    def __init__(self, md_path: Path):
        self._md_path = md_path
        # In-memory data
        self._apps: dict[str, int] = {}
        self._hours: dict[int, int] = {}
        self._about_me = ""
        self._projects = ""
        self._preferences = ""
        self._load()

    # ── File I/O ──

    def _load(self):
        """Load profile from markdown file. Creates default if not exists."""
        if self._md_path.exists():
            self._parse(self._md_path.read_text(encoding="utf-8"))
        else:
            self._save()

    def _parse(self, content: str):
        """Parse markdown sections into in-memory data."""
        current_section = None
        for line in content.split("\n"):
            stripped = line.strip()

            if stripped.startswith("## App Usage"):
                current_section = "apps"
            elif stripped.startswith("## Active Hours"):
                current_section = "hours"
            elif stripped.startswith("## About Me"):
                current_section = "about"
            elif stripped.startswith("## Current Projects"):
                current_section = "projects"
            elif stripped.startswith("## Preferences"):
                current_section = "preferences"
            elif stripped.startswith("_Last updated"):
                continue

            # Skip table headers and separators
            if current_section in ("apps", "hours") and (
                stripped.startswith("|") and ("Application" in stripped or "Hour" in stripped or "---" in stripped)
            ):
                continue

            if current_section == "apps" and stripped.startswith("|"):
                parts = [p.strip() for p in stripped.split("|") if p.strip()]
                if len(parts) == 2 and parts[1].lstrip("-").isdigit():
                    self._apps[parts[0]] = int(parts[1])

            elif current_section == "hours" and stripped.startswith("|"):
                parts = [p.strip() for p in stripped.split("|") if p.strip()]
                if len(parts) == 2 and parts[1].lstrip("-").isdigit():
                    try:
                        hour = int(parts[0].replace(":00", ""))
                        self._hours[hour] = int(parts[1])
                    except ValueError:
                        pass

            elif current_section == "about" and stripped and not stripped.startswith("*No info"):
                self._about_me = stripped

            elif current_section == "projects" and stripped and not stripped.startswith("*No info"):
                self._projects = stripped

            elif current_section == "preferences" and stripped and not stripped.startswith("*No info"):
                self._preferences = stripped

    def _save(self):
        """Write in-memory data to markdown file."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        apps_rows = "\n".join(
            f"| {app} | {cnt} |" for app, cnt in
            sorted(self._apps.items(), key=lambda x: x[1], reverse=True)
        ) if self._apps else "| _(no data yet)_ | - |"

        hours_rows = "\n".join(
            f"| {h}:00 | {cnt} |" for h, cnt in
            sorted(self._hours.items())
        ) if self._hours else "| _(no data yet)_ | - |"

        content = (
            "# User Profile\n"
            f"\n_Last updated: {now}_\n"
            "\n## App Usage\n"
            "| Application | Times Observed |\n"
            "|------------|:--------------:|\n"
            f"{apps_rows}\n"
            "\n## Active Hours\n"
            "| Hour | Times Observed |\n"
            "|------|:--------------:|\n"
            f"{hours_rows}\n"
            "\n## About Me\n"
            f"{self._about_me or '*No info yet*'}\n"
            "\n## Current Projects\n"
            f"{self._projects or '*No info yet*'}\n"
            "\n## Preferences\n"
            f"{self._preferences or '*No info yet*'}\n"
        )
        self._md_path.parent.mkdir(parents=True, exist_ok=True)
        self._md_path.write_text(content, encoding="utf-8")

    # ── Auto-tracking from perception data ──

    def update_from_observation(self, observation: str, action: str, content: str):
        """Update auto-tracked fields from a perception observation."""
        changed = False

        if "ActiveApp:" in observation:
            app_line = [l for l in observation.split("\n") if "ActiveApp:" in l]
            if app_line:
                app_name = app_line[0].split("ActiveApp:")[-1].strip()
                if app_name and app_name != "(unknown)":
                    self._apps[app_name] = self._apps.get(app_name, 0) + 1
                    changed = True

        if "Time:" in observation:
            time_line = [l for l in observation.split("\n") if "Time:" in l]
            if time_line:
                hour_str = time_line[0].split("Time:")[-1].strip().split(":")[0]
                try:
                    hour = int(hour_str)
                    self._hours[hour] = self._hours.get(hour, 0) + 1
                    changed = True
                except ValueError:
                    pass

        if changed:
            self._save()

    # ── LLM-updated sections ──

    def set_about_me(self, text: str):
        """Update the 'About Me' section."""
        self._about_me = text
        self._save()

    def set_projects(self, text: str):
        """Update the 'Current Projects' section."""
        self._projects = text
        self._save()

    def set_preferences(self, text: str):
        """Update the 'Preferences' section."""
        self._preferences = text
        self._save()

    # ── Query helpers ──

    def get_about_me(self) -> str:
        return self._about_me

    def get_projects(self) -> str:
        return self._projects

    def get_preferences(self) -> str:
        return self._preferences

    def get_common_apps(self, top_n: int = 5) -> list[tuple[str, int]]:
        """Return the most frequently used applications."""
        apps = sorted(self._apps.items(), key=lambda x: x[1], reverse=True)
        return apps[:top_n]

    def get_peak_hours(self, top_n: int = 3) -> list[int]:
        """Return the most active hours of the day."""
        hours = sorted(self._hours.items(), key=lambda x: x[1], reverse=True)
        return [h for h, _ in hours[:top_n]]

    # ── Context for LLM ──

    def summarize(self) -> str:
        """Build the full profile as markdown for LLM prompt injection."""
        self._save()  # Ensure file is up to date
        return f"[User Profile]\n{self._md_path.read_text(encoding='utf-8')}"