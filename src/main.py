#!/usr/bin/env python3
"""Chanel Agent — Autonomous Desktop Agent Runtime

An event-driven AI agent that observes the user's desktop context,
forms a behavioral profile, and proactively decides when to speak
or stay silent — without waiting for the user to ask first.

Usage:
    python -m src.main
"""

import sys
from pathlib import Path

# Ensure src is on the path when run as module
_src_dir = Path(__file__).resolve().parent
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

# Load .env BEFORE importing config (dataclass defaults are evaluated at import time)
from dotenv import load_dotenv
load_dotenv(override=True)

from config import get_config
from agent.event_loop import EventLoop


def main():
    """Entry point: load config, initialize event loop, start running."""
    config = get_config()

    loop = EventLoop(config)
    try:
        loop.start()
    except KeyboardInterrupt:
        print("\n[Shutdown] Interrupted. Goodbye.")


if __name__ == "__main__":
    main()