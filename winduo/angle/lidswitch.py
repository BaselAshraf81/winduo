"""The one piece of real hardware truth available: the operating system's lid switch.

Windows knows when the lid is shut, and broadcasts it through
``GUID_LIDSWITCH_STATE_CHANGE``. That is binary rather than an angle, so it
cannot drive the effect, but it is drift-free, instant, and free. Two uses:

- It ends the calibration sweep at exactly zero degrees.
- It ends the effect, because the display is about to go off anyway and a warped
  final frame should not be what comes back on wake.

Implemented as a message-only window on its own thread. Coupling this to the Qt
event loop would work, but a hidden window inside the widget hierarchy is one
more thing to keep alive across settings windows opening and closing.
"""

from __future__ import annotations

import ctypes
import sys
import threading
from collections.abc import Callable
from ctypes import wintypes

from winduo.log import get_logger

log = get_logger("lidswitch")

__all__ = ["LidSwitch", "is_supported"]

_WM_POWERBROADCAST = 0x0218
_PBT_POWERSETTINGCHANGE = 0x8013
_DEVICE_NOTIFY_WINDOW_HANDLE = 0x00000000
_WM_DESTROY = 0x0002
_WM_CLOSE = 0x0010

# {BA3E0F4D-B817-4094-A2D1-D56379E6A0F3}
_GUID_LIDSWITCH_STATE_CHANGE = (
    0xBA3E0F4D,
    0xB817,
    0x4094,
    (0xA2, 0xD1, 0xD5, 0x63, 0x79, 0xE6, 0xA0, 0xF3),
)


def is_supported() -> bool:
    return sys.platform == "win32"


if is_supported():

    class _GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    class _POWERBROADCAST_SETTING(ctypes.Structure):
        _fields_ = [
            ("PowerSetting", _GUID),
            ("DataLength", wintypes.DWORD),
            ("Data", ctypes.c_ubyte * 1),
        ]

    _WNDPROC = ctypes.WINFUNCTYPE(
        ctypes.c_longlong, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    )

    class _WNDCLASS(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", _WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]


class LidSwitch:
    """Reports lid open and shut transitions to a callback.

    The callback runs on this object's own thread, so anything it touches must
    tolerate that. Both consumers here take a lock, which is why it is safe.
    """

    def __init__(self, on_change: Callable[[bool], None]) -> None:
        self._on_change = on_change
        self._thread: threading.Thread | None = None
        self._hwnd = None
        self._ready = threading.Event()
        self._is_open = True
        self._lock = threading.Lock()
        self._available = False

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._is_open

    @property
    def is_available(self) -> bool:
        return self._available

    def start(self, timeout: float = 2.0) -> bool:
        if not is_supported():
            log.info("lid switch notifications need Windows")
            return False
        if self._thread and self._thread.is_alive():
            return self._available
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run, name="winduo-lidswitch", daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout)
        return self._available

    def stop(self) -> None:
        hwnd = self._hwnd
        if hwnd:
            ctypes.windll.user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)
        thread, self._thread = self._thread, None
        if thread:
            thread.join(timeout=2.0)

    # --- Thread ----------------------------------------------------------

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # Held on the instance so the trampoline is not collected while Windows
        # still holds a pointer to it. A garbage-collected window procedure is a
        # hard crash, not an exception.
        self._proc = _WNDPROC(self._window_proc)

        cls = _WNDCLASS()
        cls.lpfnWndProc = self._proc
        cls.hInstance = kernel32.GetModuleHandleW(None)
        cls.lpszClassName = "WinDuoLidSwitch"

        # Spelled out because the defaults guess wrong on 64-bit: handles are
        # pointer-sized, and ctypes narrows them to C int without this, which
        # overflows on any module handle above 2 GB.
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        user32.RegisterClassW.restype = wintypes.WORD
        user32.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASS)]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,     # dwExStyle
            wintypes.LPCWSTR,   # lpClassName
            wintypes.LPCWSTR,   # lpWindowName
            wintypes.DWORD,     # dwStyle
            ctypes.c_int,       # x
            ctypes.c_int,       # y
            ctypes.c_int,       # nWidth
            ctypes.c_int,       # nHeight
            wintypes.HWND,      # hWndParent
            wintypes.HMENU,     # hMenu
            wintypes.HINSTANCE, # hInstance
            wintypes.LPVOID,    # lpParam
        ]
        user32.RegisterPowerSettingNotification.restype = wintypes.HANDLE
        user32.RegisterPowerSettingNotification.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_GUID),
            wintypes.DWORD,
        ]
        user32.UnregisterPowerSettingNotification.restype = wintypes.BOOL
        user32.UnregisterPowerSettingNotification.argtypes = [wintypes.HANDLE]
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.PostMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.DefWindowProcW.restype = ctypes.c_longlong
        user32.DefWindowProcW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]

        registered = user32.RegisterClassW(ctypes.byref(cls))
        if not registered:
            # 1410 is "class already exists", which happens on a restart within
            # the same process and is not a problem.
            error = kernel32.GetLastError()
            if error != 1410:
                log.warning("could not register the lid switch window class (%d)", error)
                self._ready.set()
                return

        hwnd = user32.CreateWindowExW(
            0,
            "WinDuoLidSwitch",
            "WinDuo",
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            cls.hInstance,
            None,
        )
        if not hwnd:
            log.warning("could not create the lid switch window")
            self._ready.set()
            return
        self._hwnd = hwnd

        guid = _GUID(
            _GUID_LIDSWITCH_STATE_CHANGE[0],
            _GUID_LIDSWITCH_STATE_CHANGE[1],
            _GUID_LIDSWITCH_STATE_CHANGE[2],
            (ctypes.c_ubyte * 8)(*_GUID_LIDSWITCH_STATE_CHANGE[3]),
        )
        handle = user32.RegisterPowerSettingNotification(
            wintypes.HANDLE(hwnd), ctypes.byref(guid), _DEVICE_NOTIFY_WINDOW_HANDLE
        )
        if not handle:
            log.info("this machine does not report a lid switch")
            user32.DestroyWindow(hwnd)
            self._ready.set()
            return

        self._available = True
        self._ready.set()
        log.info("listening for lid switch changes")

        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))

        user32.UnregisterPowerSettingNotification(handle)
        self._hwnd = None
        self._available = False

    def _window_proc(self, hwnd, msg, wparam, lparam):
        user32 = ctypes.windll.user32
        if msg == _WM_POWERBROADCAST and wparam == _PBT_POWERSETTINGCHANGE:
            setting = ctypes.cast(
                lparam, ctypes.POINTER(_POWERBROADCAST_SETTING)
            ).contents
            if setting.DataLength >= 1:
                # The payload is 1 for open and 0 for shut.
                is_open = bool(setting.Data[0])
                with self._lock:
                    changed = is_open != self._is_open
                    self._is_open = is_open
                if changed:
                    log.debug("lid %s", "opened" if is_open else "closed")
                    try:
                        self._on_change(is_open)
                    except Exception:
                        log.exception("lid switch callback failed")
            return 1
        if msg == _WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if msg == _WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
