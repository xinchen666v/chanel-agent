"""Perception snapshot data structure - contains all observed context at a point in time."""

from dataclasses import dataclass
from datetime import datetime
import json


@dataclass
class PerceptionSnapshot:
    """Complete snapshot of user's desktop context at wake time."""

    timestamp: datetime
    active_window_title: str
    active_app_name: str
    user_idle_seconds: int
    os: str
    is_fullscreen: bool
    hour_of_day: int
    day_of_week: int  # 0=Monday, 6=Sunday
    is_weekend: bool

    def to_json(self) -> str:
        """Serialize to JSON for persistent storage."""
        return json.dumps({
            "timestamp": self.timestamp.isoformat(),
            "active_window_title": self.active_window_title,
            "active_app_name": self.active_app_name,
            "user_idle_seconds": self.user_idle_seconds,
            "os": self.os,
            "is_fullscreen": self.is_fullscreen,
            "hour_of_day": self.hour_of_day,
            "day_of_week": self.day_of_week,
            "is_weekend": self.is_weekend,
        })

    @classmethod
    def from_json(cls, data: str) -> "PerceptionSnapshot":
        """Deserialize from JSON."""
        obj = json.loads(data)
        return cls(
            timestamp=datetime.fromisoformat(obj["timestamp"]),
            active_window_title=obj["active_window_title"],
            active_app_name=obj["active_app_name"],
            user_idle_seconds=obj["user_idle_seconds"],
            os=obj["os"],
            is_fullscreen=obj["is_fullscreen"],
            hour_of_day=obj["hour_of_day"],
            day_of_week=obj["day_of_week"],
            is_weekend=obj["is_weekend"],
        )

    def to_text_prompt(self) -> str:
        """Format for LLM prompt injection."""
        lines = [
            f"[Perception @ {self.timestamp.strftime('%H:%M:%S')}]",
            f"  ActiveWindow: {self.active_window_title or '(none)'}",
            f"  ActiveApp:    {self.active_app_name or '(unknown)'}",
            f"  UserIdle:     {self.user_idle_seconds}s",
            f"  Fullscreen:   {'Yes' if self.is_fullscreen else 'No'}",
            f"  Time:         {self.hour_of_day}:00",
            f"  Weekend:      {'Yes' if self.is_weekend else 'No'}",
            f"  OS:           {self.os}",
        ]
        return "\n".join(lines)