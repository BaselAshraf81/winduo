"""Screen capture, behind one interface with two backends.

DXGI Desktop Duplication is the one that matters. It hands over frames the
compositor already has in video memory, so a 1080p desktop streams at 60 frames
per second without measurably loading the CPU. GDI copying, which is what the
fallback does, costs 15 to 25 ms per frame and misses content drawn through
hardware overlays.

The fallback exists because Desktop Duplication is refused in a few real
situations: some multi-GPU laptops hand out the wrong adapter, and a few remote
desktop and virtual display drivers do not implement it. A slow effect beats no
effect.
"""

from __future__ import annotations

import contextlib
import threading
import time
from abc import ABC, abstractmethod

import cv2
import numpy as np

from winduo.log import get_logger

log = get_logger("capture")

__all__ = ["ScreenCapture", "CaptureError", "open_capture"]


class CaptureError(RuntimeError):
    """No backend could capture the screen."""


class Backend(ABC):
    name = "none"

    @abstractmethod
    def start(self, fps: int) -> tuple[int, int]: ...

    @abstractmethod
    def grab(self) -> np.ndarray | None:
        """Newest frame as BGRA, or ``None`` when nothing is new."""

    @abstractmethod
    def stop(self) -> None: ...


#: One duplication object per output, kept for the life of the process.
#:
#: dxcam treats its cameras as singletons: asking for one that already exists
#: hands back the existing object and ignores the new arguments, and the only
#: documented way to get a fresh one is to drop every reference and let the
#: finaliser run. Creating and destroying them around each run of the effect
#: therefore ends up reusing a half-torn-down object. Holding one and starting
#: or stopping it is both simpler and what the library actually supports.
_CAMERAS: dict[int, object] = {}


class _DxcamBackend(Backend):
    name = "Desktop Duplication"

    def __init__(self, monitor: int) -> None:
        self._monitor = monitor
        self._camera = None

    def start(self, fps: int) -> tuple[int, int]:
        import dxcam

        camera = _CAMERAS.get(self._monitor)
        if camera is None:
            camera = dxcam.create(output_idx=self._monitor, output_color="BGRA")
            if camera is None:
                raise CaptureError("Desktop Duplication offered no output")
            _CAMERAS[self._monitor] = camera
        elif getattr(camera, "is_capturing", False):
            # Already streaming from a previous run; take it as it is.
            frame = camera.get_latest_frame()
            if frame is not None:
                height, width = frame.shape[:2]
                self._camera = camera
                return width, height
        # video_mode keeps the newest frame available even when the desktop is
        # not changing. Without it a still screen returns None and the effect
        # would render whatever was last on screen before the user stopped
        # moving the mouse.
        camera.start(target_fps=fps, video_mode=True)
        self._camera = camera

        # Generous, because this is not just driver startup. Bringing the overlay
        # up counts as a desktop change, and duplication answers an access-loss
        # recovery before it hands over a first frame. Two seconds was not enough
        # on Intel integrated graphics.
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            frame = camera.get_latest_frame()
            if frame is not None:
                height, width = frame.shape[:2]
                return width, height
            time.sleep(0.02)
        raise CaptureError("Desktop Duplication started but sent no frames")

    def grab(self) -> np.ndarray | None:
        if self._camera is None:
            return None
        return self._camera.get_latest_frame()

    def stop(self) -> None:
        # The object stays in the cache on purpose; only the stream stops.
        camera, self._camera = self._camera, None
        if camera is not None:
            with contextlib.suppress(Exception):
                camera.stop()


class _MssBackend(Backend):
    name = "GDI copy"

    def __init__(self, monitor: int) -> None:
        self._index = monitor + 1  # mss counts the virtual screen as 0
        self._sct = None
        self._region = None

    def start(self, fps: int) -> tuple[int, int]:
        import mss

        self._sct = mss.mss()
        monitors = self._sct.monitors
        if self._index >= len(monitors):
            self._index = 1
        self._region = monitors[self._index]
        return self._region["width"], self._region["height"]

    def grab(self) -> np.ndarray | None:
        if self._sct is None or self._region is None:
            return None
        raw = self._sct.grab(self._region)
        return np.asarray(raw, dtype=np.uint8)  # already BGRA

    def stop(self) -> None:
        sct, self._sct = self._sct, None
        if sct is not None:
            sct.close()


class ScreenCapture:
    """A capture thread that keeps exactly one frame ready to be uploaded.

    Deliberately drops frames rather than queueing them. The renderer only ever
    wants the newest one, and a queue would trade latency for frames nobody
    draws. Mac Duo takes the same position for the same reason.
    """

    def __init__(self, monitor: int = 0, fps: int = 60, width_cap: int = 0) -> None:
        self.monitor = monitor
        self.fps = fps
        self.width_cap = width_cap
        self.backend_name = ""
        #: Size frames are delivered at, after any downscale.
        self.size: tuple[int, int] = (0, 0)
        #: Size of the display itself, before the downscale.
        self.native_size: tuple[int, int] = (0, 0)
        self._backend: Backend | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._serial = 0
        self._taken = 0

    # --- Lifecycle -------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._backend, self.native_size = _first_working_backend(self.monitor, self.fps)
        self.backend_name = self._backend.name
        self.size = _capped(self.native_size, self.width_cap)
        log.info(
            "capturing %dx%d via %s, rendering at %dx%d",
            *self.native_size,
            self.backend_name,
            *self.size,
        )
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="winduo-capture", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread:
            thread.join(timeout=2.0)
        backend, self._backend = self._backend, None
        if backend:
            backend.stop()
        with self._lock:
            self._frame = None
            self._serial = 0
            self._taken = 0

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # --- Reading ---------------------------------------------------------

    def take(self) -> np.ndarray | None:
        """The newest frame if it has not been taken yet, otherwise ``None``.

        Returning ``None`` for an already-seen frame lets the renderer skip the
        upload and the mipmap rebuild, which is most of the per-frame cost.
        """
        with self._lock:
            if self._frame is None or self._serial == self._taken:
                return None
            self._taken = self._serial
            return self._frame

    def peek(self) -> np.ndarray | None:
        """The newest frame whether or not it has been taken."""
        with self._lock:
            return self._frame

    # --- Thread ----------------------------------------------------------

    def _run(self) -> None:
        assert self._backend is not None
        interval = 1.0 / max(self.fps, 1)
        target = _capped(self.native_size, self.width_cap)
        needs_resize = target != self.native_size
        failures = 0

        while not self._stop.is_set():
            started = time.monotonic()
            try:
                frame = self._backend.grab()
            except Exception:
                failures += 1
                log.debug("capture grab failed", exc_info=True)
                frame = None
                if failures > 60:
                    log.warning("capture backend gave up")
                    return

            if frame is not None:
                failures = 0
                if needs_resize:
                    frame = cv2.resize(frame, target, interpolation=cv2.INTER_AREA)
                # Contiguous because the GL upload reads it as a flat buffer.
                if not frame.flags["C_CONTIGUOUS"]:
                    frame = np.ascontiguousarray(frame)
                with self._lock:
                    self._frame = frame
                    self._serial += 1

            elapsed = time.monotonic() - started
            remaining = interval - elapsed
            if remaining > 0:
                time.sleep(remaining)


def open_capture(monitor: int = 0, fps: int = 60, width_cap: int = 0) -> ScreenCapture:
    capture = ScreenCapture(monitor=monitor, fps=fps, width_cap=width_cap)
    capture.start()
    return capture


def _capped(size: tuple[int, int], width_cap: int) -> tuple[int, int]:
    """Shrink to the width cap, keeping the aspect ratio and even dimensions.

    The picture is receding and blurring while the effect runs, so full
    resolution buys very little. A 4K frame is 33 MB, and moving 60 of those per
    second through system memory to reach the GPU costs 2 GB/s for detail the
    blur immediately discards.
    """
    width, height = size
    if width_cap <= 0 or width <= width_cap or width <= 0:
        return size
    scale = width_cap / width
    return (width_cap, max(2, int(round(height * scale)) // 2 * 2))


def _first_working_backend(monitor: int, fps: int) -> tuple[Backend, tuple[int, int]]:
    problems: list[str] = []
    for build in (_DxcamBackend, _MssBackend):
        backend = build(monitor)
        try:
            size = backend.start(fps)
        except Exception as error:
            problems.append(f"{backend.name}: {error}")
            log.info("%s unavailable: %s", backend.name, error)
            # A backend that failed to start may still hold resources, and it may
            # equally fail to release them. Either way the next one gets a turn.
            with contextlib.suppress(Exception):
                backend.stop()
            continue
        if size[0] > 0 and size[1] > 0:
            return backend, size
        backend.stop()
        problems.append(f"{backend.name}: reported a zero-sized screen")
    raise CaptureError("Could not capture the screen. " + "; ".join(problems))
