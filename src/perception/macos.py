"""macOS-specific desktop perception using AppleScript and CoreGraphics via ctypes."""

import ctypes
import ctypes.util
import platform
import re
import subprocess
from datetime import datetime

from .base import AbstractPerception
from .snapshot import PerceptionSnapshot


class MacOSPerception(AbstractPerception):
    """macOS desktop perception - reads active window, idle time, and fullscreen state."""

    def __init__(self):
        self._core_graphics = ctypes.cdll.LoadLibrary(
            ctypes.util.find_library("CoreGraphics")
        )

    def is_available(self) -> bool:
        return platform.system() == "Darwin" and self._core_graphics is not None

    @staticmethod
    def _run_osascript(script: str) -> tuple[int, str]:
        """Run AppleScript and return (returncode, stdout_stripped)."""
        try:
            r = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=3,
            )
            return r.returncode, r.stdout.strip()
        except Exception:
            return -1, ""

    def get_active_window_info(self) -> tuple[str, str]:
        """Get active window title and application name via AppleScript."""
        # Get name of frontmost application
        rc, app_name = self._run_osascript(
            'tell application "System Events" to get name of '
            "first application process whose frontmost is true"
        )
        if rc != 0 or not app_name:
            return "", "(unknown)"

        # Get window title from that application
        rc, title = self._run_osascript(
            f'tell application "{app_name}" to '
            "if (count of windows) > 0 then get name of front window"
        )
        if rc != 0 or not title:
            title = app_name

        return title, app_name

    def get_idle_seconds(self) -> int:
        """Get time since last user input in seconds using CoreGraphics."""
        try:
            # kCGAnyInputEventType = 0xFFFFFFFF (~0)
            # kCGEventSourceStateCombinedSessionState = 1
            func = self._core_graphics.CGEventSourceSecondsSinceLastEventType
            func.restype = ctypes.c_double
            func.argtypes = [ctypes.c_int32, ctypes.c_uint32]

            idle = func(1, 0xFFFFFFFF)
            return int(idle)
        except Exception:
            return 0

    def is_fullscreen(self) -> bool:
        """Detect if active window is fullscreen via AppleScript + heuristics."""
        rc, out = self._run_osascript(
            'tell application "System Events"\n'
            "  set fp to first application process whose frontmost is true\n"
            "  set {wx, wy} to position of first window of fp\n"
            "  set {ww, wh} to size of first window of fp\n"
            "  set {sw, sh} to size of desktop of fp\n"
            '  return wx & "," & wy & "," & ww & "," & wh & "," & sw & "," & sh\n'
            "end tell"
        )
        if rc != 0:
            return False

        nums = re.findall(r"\d+", out)
        if len(nums) < 6:
            return False

        wx, wy, ww, wh, sw, sh = map(int, nums[:6])
        tolerance = 2
        return (
            abs(wx) <= tolerance
            and abs(wy) <= tolerance
            and abs(ww - sw) <= tolerance
            and abs(wh - sh) <= tolerance
        )

    def get_snapshot(self) -> PerceptionSnapshot:
        """Capture complete perception snapshot for macOS."""
        now = datetime.now()
        title, app_name = self.get_active_window_info()
        idle_seconds = self.get_idle_seconds()
        is_full = self.is_fullscreen()
        weekday = now.weekday()

        return PerceptionSnapshot(
            timestamp=now,
            active_window_title=title,
            active_app_name=app_name,
            user_idle_seconds=idle_seconds,
            os="macOS",
            is_fullscreen=is_full,
            hour_of_day=now.hour,
            day_of_week=weekday,
            is_weekend=weekday >= 5,
        )