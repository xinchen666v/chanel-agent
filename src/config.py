"""Configuration management for Chanel Agent."""

import os
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class Config:
    """Application configuration loaded from environment variables."""

    model: str = os.getenv("MODEL_ID", "claude-sonnet-4-20250514")
    api_base_url: str = os.getenv("ANTHROPIC_BASE_URL", "")
    api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    workdir: Path = field(default_factory=Path.cwd)
    db_path: Path = field(
        default_factory=lambda: Path(os.getenv("CHANEL_DB_PATH", str(Path.cwd() / "data" / "chanel.db")))
    )
    min_wake_interval: int = 5
    max_tool_output_chars: int = 50000
    max_history_messages: int = 50
    memory_context_turns: int = 5

    @classmethod
    def from_env(cls) -> "Config":
        return cls()


# Singleton
_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config.from_env()
    return _config