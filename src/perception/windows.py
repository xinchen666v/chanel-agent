"""Windows-specific desktop perception using Windows API via ctypes."""

import ctypes
from ctypes import wintypes
from datetime import datetime

from .base import AbstractPerception
from .snapshot import PerceptionSnapshot


class WindowsPerception(AbstractPerception):
    """Windows desktop perception - reads active window, idle time, and fullscreen state."""

    user32: "ctypes.WinDLL"
    kernel32: "ctypes.WinDLL"

    def __init__(self):
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32

    def is_available(self) -> bool:
        """Check if we're running on Windows."""
        import platform
        return platform.system() == "Windows"

    def get_active_window_info(self) -> tuple[str, str]:
        """Get active window title and application name."""
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return "", ""

        length = self.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return "", ""

        buf = ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value

        # Try to get process name (for app name)
        try:
            pid = wintypes.DWORD()
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            app_name = self._get_process_name(pid.value)
        except Exception:
            # If we can't get process name, extract from title heuristics
            app_name = title.split(" - ")[-1] if " - " in title else title

        return title, app_name

    def _get_process_name(self, pid: int) -> str:
        """Get process name from PID using CreateToolhelp32Snapshot."""
        try:
            from ctypes import wintypes as _w

            TH32CS_SNAPPROCESS = 0x00000002

            class PROCESSENTRY32W(ctypes.Structure):
                _fields_ = [
                    ("dwSize", _w.DWORD),
                    ("cntUsage", _w.DWORD),
                    ("th32ProcessID", _w.DWORD),
                    ("th32DefaultHeapID", ctypes.POINTER(_w.ULONG)),
                    ("th32ModuleID", _w.DWORD),
                    ("cntThreads", _w.DWORD),
                    ("th32ParentProcessID", _w.DWORD),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", _w.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260),
                ]

            snapshot = self.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            if snapshot == -1:
                return "(unknown)"

            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)

            if self.kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
                while True:
                    if entry.th32ProcessID == pid:
                        self.kernel32.CloseHandle(snapshot)
                        return entry.szExeFile
                    if not self.kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                        break

            self.kernel32.CloseHandle(snapshot)
            return "(unknown)"
        except Exception:
            return "(unknown)"

    def get_idle_seconds(self) -> int:
        """Get time since last user input in seconds."""
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("dwTime", wintypes.DWORD),
            ]

        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        self.user32.GetLastInputInfo(ctypes.byref(lii))
        tick = self.kernel32.GetTickCount()
        idle_ms = tick - lii.dwTime
        return int(idle_ms // 1000)

    def is_fullscreen(self) -> bool:
        """Detect if active window is fullscreen."""
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return False

        # Get screen rect and window rect
        screen_rect = wintypes.RECT()
        window_rect = wintypes.RECT()

        # Get primary screen dimensions
        h_monitor = self.user32.MonitorFromWindow(hwnd, 0)  # MONITOR_DEFAULTTOPRIMARY
        if not h_monitor:
            screen_left = self.user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
            screen_top = self.user32.GetSystemMetrics(77)    # SM_YVIRTUALSCREEN
            screen_width = self.user32.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
            screen_height = self.user32.GetSystemMetrics(79) # SM_CYVIRTUALSCREEN
        else:
            # We could use GetMonitorInfo, but this heuristic works for MVP
            screen_left = self.user32.GetSystemMetrics(76)
            screen_top = self.user32.GetSystemMetrics(77)
            screen_width = self.user32.GetSystemMetrics(78)
            screen_height = self.user32.GetSystemMetrics(79)

        screen_rect.left = screen_left
        screen_rect.top = screen_top
        screen_rect.right = screen_left + screen_width
        screen_rect.bottom = screen_top + screen_height

        self.user32.GetWindowRect(hwnd, ctypes.byref(window_rect))

        # If window covers entire screen, consider it fullscreen (heuristic)
        tolerance = 2  # Allow a couple pixels for border
        is_full = (
            abs(window_rect.left - screen_rect.left) <= tolerance and
            abs(window_rect.top - screen_rect.top) <= tolerance and
            abs(window_rect.right - screen_rect.right) <= tolerance and
            abs(window_rect.bottom - screen_rect.bottom) <= tolerance
        )
        return is_full

    def get_snapshot(self) -> PerceptionSnapshot:
        """Capture complete perception snapshot for Windows."""
        now = datetime.now()
        title, app_name = self.get_active_window_info()
        idle_seconds = self.get_idle_seconds()
        is_full = self.is_fullscreen()

        weekday = now.weekday()  # 0=Monday, 6=Sunday

        return PerceptionSnapshot(
            timestamp=now,
            active_window_title=title,
            active_app_name=app_name,
            user_idle_seconds=idle_seconds,
            os="Windows",
            is_fullscreen=is_full,
            hour_of_day=now.hour,
            day_of_week=weekday,
            is_weekend=weekday >= 5,
        )