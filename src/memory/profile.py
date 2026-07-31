"""User behavior profile - persisted as a special memory file.

This file is managed by MemoryBank as `data/memory/user_profile.md`.
It contains both:
  - Auto-tracked behavioral data (app usage, active hours)
  - Semantic sections updated by the LLM (about me, projects, preferences)

The frontmatter makes it a first-class citizen of the memory bank index.
"""

from __future__ import annotations

import re
from pathlib import Path
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .bank import MemoryBank


class UserProfile:
    """Builds and maintains a persistent user behavior profile.

    The profile lives at data/memory/user_profile.md and is indexed by MEMORY.md.
    It keeps backward-compatible APIs (set_about_me, set_projects, set_preferences)
    while integrating with the file-based memory bank.
    """

    FILENAME = "user_profile"

    def __init__(self, memory_bank: MemoryBank):
        self._bank = memory_bank
        # In-memory data for fast access
        self._apps: dict[str, int] = {}
        self._hours: dict[int, int] = {}
        self._about_me = ""
        self._projects = ""
        self._preferences = ""
        self._load()

    # ── File I/O ──

    def _load(self):
        """Load profile from the memory bank file. Creates default if not exists."""
        existing = self._bank.load(self.FILENAME)
        if existing.startswith("Error:"):
            self._save()
            return
        self._parse(existing)

    def _parse(self, content: str):
        """Parse the markdown body into in-memory data."""
        # Remove frontmatter
        body = content
        if body.startswith("---"):
            parts = body.split("---", 2)
            if len(parts) >= 3:
                body = parts[2]

        current_section = None
        section_lines: dict[str, list[str]] = {
            "about": [],
            "projects": [],
            "preferences": [],
        }

        for line in body.split("\n"):
            stripped = line.strip()

            if stripped.startswith("## App Usage"):
                current_section = "apps"
                continue
            elif stripped.startswith("## Active Hours"):
                current_section = "hours"
                continue
            elif stripped.startswith("## About Me"):
                current_section = "about"
                continue
            elif stripped.startswith("## Current Projects"):
                current_section = "projects"
                continue
            elif stripped.startswith("## Preferences"):
                current_section = "preferences"
                continue
            elif stripped.startswith("_Last updated"):
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

            elif current_section in section_lines:
                if stripped and not stripped.startswith("*No info"):
                    section_lines[current_section].append(line)

        self._about_me = "\n".join(section_lines["about"]).strip()
        self._projects = "\n".join(section_lines["projects"]).strip()
        self._preferences = "\n".join(section_lines["preferences"]).strip()

    def _save(self):
        """Write in-memory data to the memory bank file."""
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
            f"_Last updated: {now}_\n"
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

        # Use memory bank create/update to keep index in sync
        existing = self._bank.load(self.FILENAME)
        if existing.startswith("Error:"):
            self._bank.create(
                name=self.FILENAME,
                description="Aggregated user behavior profile and semantic notes",
                content=content,
                type="user",
                tags=["auto-tracked", "profile"],
            )
        else:
            self._bank.update(self.FILENAME, content, mode="replace")

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
        return f"[User Profile]\n{self._bank.load(self.FILENAME)}"
