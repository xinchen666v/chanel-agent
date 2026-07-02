#!/usr/bin/env python3
"""Chanel Agent — Autonomous Desktop Agent Runtime

An event-driven AI agent that observes the user's desktop context,
forms a behavioral profile, and proactively decides when to speak
or stay silent — without waiting for the user to ask first.

Usage:
    python -m src.main               # TUI mode (default)
    python -m src.main --terminal    # Terminal mode (plain print, good for log capture)
"""

import argparse
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chanel Agent — Autonomous Desktop Agent Runtime",
    )
    parser.add_argument(
        "--terminal", "-t",
        action="store_true",
        help="Run in terminal mode (plain text output, useful for log capture).",
    )
    return parser.parse_args()


def main():
    """Entry point: start TUI mode (default) or terminal mode."""
    args = _parse_args()
    config = get_config()

    # Terminal mode: explicit flag or TUI unavailable
    if args.terminal:
        loop = EventLoop(config)
        try:
            loop.start()
        except KeyboardInterrupt:
            print("\n[Shutdown] Interrupted. Goodbye.")
        return

    # TUI mode (default)
    try:
        from ui.tui_app import AgentTUI

        app = AgentTUI(config)
        app.run()
        return
    except ImportError:
        # textual not installed — fall back to terminal
        loop = EventLoop(config)
        try:
            loop.start()
        except KeyboardInterrupt:
            print("\n[Shutdown] Interrupted. Goodbye.")


if __name__ == "__main__":
    main()