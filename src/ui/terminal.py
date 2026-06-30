"""Terminal output with ANSI color support for Windows."""

import os
import sys


class Terminal:
    """Colored terminal output utilities.

    Handles Windows console initialization for ANSI escape sequences.
    """

    _initialized = False

    @classmethod
    def _ensure_init(cls):
        if cls._initialized:
            return
        cls._initialized = True
        if sys.platform == "win32":
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
                mode = ctypes.c_uint32()
                kernel32.GetConsoleMode(handle, ctypes.byref(mode))
                mode.value |= 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
                kernel32.SetConsoleMode(handle, mode)
            except Exception:
                pass

    @classmethod
    def info(cls, text: str):
        """Yellow info message."""
        cls._ensure_init()
        print(f"\033[33m{text}\033[0m")

    @classmethod
    def agent_message(cls, text: str):
        """Magenta agent message."""
        cls._ensure_init()
        print(f"\n\033[35m[Agent] {text}\033[0m\n")

    @classmethod
    def tool_debug(cls, text: str):
        """Gray tool debug output."""
        cls._ensure_init()
        print(f"\033[90m> {text}\033[0m")

    @classmethod
    def prompt(cls, text: str = ""):
        """Cyan user prompt."""
        cls._ensure_init()
        return input(f"\033[36m{text}\033[0m")

    @classmethod
    def banner(cls, text: str):
        """Large banner output."""
        cls._ensure_init()
        print(f"\033[36m{text}\033[0m")