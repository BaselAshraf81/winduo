"""The Win32 calls that make an overlay window behave like an overlay.

Qt can produce a frameless always-on-top translucent window on its own, but
three things it has no API for decide whether this effect works at all:

- **Excluding the window from screen capture.** Without it the overlay is
  captured, drawn into itself, and recurses. This is the Windows equivalent of
  ScreenCaptureKit's application exclusion, and Mac Duo needs the same thing.
- **Click-through.** ``WS_EX_TRANSPARENT`` sends hit-testing straight past the
  window, so the applications underneath keep working normally.
- **Staying above full-screen windows.** ``HWND_TOPMOST`` without activation.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from winduo.log import get_logger

log = get_logger("win32")

__all__ = [
    "exclude_from_capture",
    "make_click_through",
    "raise_topmost",
    "is_windows",
    "MIN_BUILD_FOR_CAPTURE_EXCLUSION",
]

_GWL_EXSTYLE = -20
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_LAYERED = 0x00080000
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_TOOLWINDOW = 0x00000080

_HWND_TOPMOST = -1
_SWP_NOMOVE = 0x0002
_SWP_NOSIZE = 0x0001
_SWP_NOACTIVATE = 0x0010
_SWP_SHOWWINDOW = 0x0040

_WDA_NONE = 0x00000000
_WDA_EXCLUDEFROMCAPTURE = 0x00000011

#: ``WDA_EXCLUDEFROMCAPTURE`` arrived in Windows 10 version 2004. On older
#: builds the call succeeds but behaves like ``WDA_MONITOR``, which blanks the
#: window in captures instead of removing it. There is no workaround.
MIN_BUILD_FOR_CAPTURE_EXCLUSION = 19041


def is_windows() -> bool:
    return sys.platform == "win32"


def _hwnd(window) -> int | None:
    """Pull an HWND out of a Qt window handle."""
    try:
        handle = int(window.winId())
    except (AttributeError, TypeError, ValueError):
        return None
    return handle or None


def exclude_from_capture(window, enabled: bool = True) -> bool:
    """Hide the window from every screen capture API while leaving it on screen.

    Returns ``False`` when the platform cannot do it, which the caller should
    treat as a reason to fall back to a held frame rather than a live one:
    capturing a live screen that contains this window feeds it back into itself.
    """
    if not is_windows():
        return False
    handle = _hwnd(window)
    if handle is None:
        return False
    affinity = _WDA_EXCLUDEFROMCAPTURE if enabled else _WDA_NONE
    ok = bool(ctypes.windll.user32.SetWindowDisplayAffinity(
        wintypes.HWND(handle), wintypes.DWORD(affinity)
    ))
    if not ok:
        log.warning(
            "could not exclude the overlay from capture (%d)",
            ctypes.windll.kernel32.GetLastError(),
        )
    return ok


def make_click_through(window) -> bool:
    """Pass mouse input straight through, and keep the window out of Alt-Tab."""
    if not is_windows():
        return False
    handle = _hwnd(window)
    if handle is None:
        return False
    user32 = ctypes.windll.user32
    user32.GetWindowLongW.restype = ctypes.c_long
    current = user32.GetWindowLongW(wintypes.HWND(handle), _GWL_EXSTYLE)
    wanted = (
        current
        | _WS_EX_TRANSPARENT
        | _WS_EX_LAYERED
        | _WS_EX_NOACTIVATE
        | _WS_EX_TOOLWINDOW
    )
    if wanted != current:
        user32.SetWindowLongW(wintypes.HWND(handle), _GWL_EXSTYLE, wanted)
    return True


def raise_topmost(window) -> bool:
    """Above everything, including full-screen windows, without taking focus."""
    if not is_windows():
        return False
    handle = _hwnd(window)
    if handle is None:
        return False
    return bool(
        ctypes.windll.user32.SetWindowPos(
            wintypes.HWND(handle),
            wintypes.HWND(_HWND_TOPMOST),
            0,
            0,
            0,
            0,
            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE | _SWP_SHOWWINDOW,
        )
    )


def windows_build() -> int:
    """The current build number, or 0 when it cannot be read."""
    if not is_windows():
        return 0
    try:
        return sys.getwindowsversion().build
    except Exception:
        return 0


def supports_capture_exclusion() -> bool:
    return windows_build() >= MIN_BUILD_FOR_CAPTURE_EXCLUSION
