"""The webcam, on a background thread, feeding the estimator.

Exposure is the thing worth caring about here. A lid that closes 90 degrees in
half a second is travelling 180 degrees per second, which at 30 frames per
second is 6 degrees of rotation inside a single frame. At default auto exposure
in indoor light that smears the image by 80-odd pixels and destroys every
feature the correlator needs, exactly during the motion we are trying to
measure. Forcing a short shutter and letting gain deal with the darkness costs
image quality nobody sees and buys a signal that survives fast movement.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import cv2

from winduo.angle.estimator import AngleSample, TravelEstimator
from winduo.config import Calibration, Settings
from winduo.log import get_logger

log = get_logger("camera")

__all__ = ["CameraAngleSource", "CameraStatus", "list_cameras"]


@dataclass(frozen=True)
class CameraStatus:
    """Why the estimator is or is not producing anything."""

    running: bool = False
    #: Set when the camera could not be opened or was taken away.
    problem: str = ""
    frames: int = 0
    #: Measured frame rate, so the interface can say the camera is struggling.
    fps: float = 0.0
    name: str = ""

    @property
    def is_healthy(self) -> bool:
        return self.running and not self.problem


#: Frames per second requested. More would help the correlator and cost battery;
#: 30 is what almost every laptop camera actually delivers.
TARGET_FPS = 30
#: Capture resolution. The tracker downscales to 320 anyway, so anything larger
#: is wasted bandwidth, but very small modes are often unsupported or cropped.
CAPTURE_WIDTH = 640
CAPTURE_HEIGHT = 480

#: DirectShow reports exposure on a log2-seconds scale, so -6 is about 1/64 s
#: and -8 about 1/256 s. Short enough to survive a fast close, long enough that
#: an ordinary room is not pitch black.
MANUAL_EXPOSURE = -7.0
#: DirectShow's magic values for the auto exposure property.
_DSHOW_MANUAL_EXPOSURE = 0.25
_DSHOW_AUTO_EXPOSURE = 0.75


def list_cameras(limit: int = 6) -> list[int]:
    """Indices that open. Slow enough to belong in a settings window, not a hot path."""
    found: list[int] = []
    for index in range(limit):
        capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        try:
            if capture.isOpened() and capture.read()[0]:
                found.append(index)
        finally:
            capture.release()
    return found


class CameraAngleSource:
    """Owns the camera thread and publishes the newest :class:`AngleSample`.

    The controller polls :meth:`latest` rather than receiving callbacks, which
    keeps every consumer on its own clock and matches how the reference
    implementation polls its hardware sensor.
    """

    def __init__(self, settings: Settings, calibration: Calibration) -> None:
        self._estimator = TravelEstimator(
            calibration,
            settle_seconds=settings.neutral_settle_seconds,
            settle_tolerance=settings.neutral_settle_tolerance,
        )
        self._camera_index = settings.camera_index
        self._lock = threading.Lock()
        self._sample: AngleSample | None = None
        self._status = CameraStatus()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        #: Set while an external consumer wants raw frames, for the calibration
        #: wizard and the recorder.
        self._tap = None

    # --- Lifecycle -------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="winduo-camera", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread:
            thread.join(timeout=timeout)
        with self._lock:
            self._status = CameraStatus()
            self._sample = None

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def retune(
        self, settings: Settings | None = None, calibration: Calibration | None = None
    ) -> None:
        restart = (
            settings is not None
            and settings.camera_index != self._camera_index
            and self.is_running
        )
        if settings is not None:
            self._camera_index = settings.camera_index
            self._estimator.retune(
                settle_seconds=settings.neutral_settle_seconds,
                settle_tolerance=settings.neutral_settle_tolerance,
            )
        if calibration is not None:
            self._estimator.retune(calibration=calibration)
        if restart:
            self.stop()
            self.start()

    # --- Reading ---------------------------------------------------------

    def latest(self, max_age: float = 0.4) -> AngleSample | None:
        """The newest sample, or ``None`` when it is too old to act on.

        Staleness matters more than it looks. A sample from 300 ms ago describes
        a lid that has since moved 50 degrees, and acting on it triggers the
        effect at the wrong moment or not at all.
        """
        with self._lock:
            sample = self._sample
        if sample is None:
            return None
        if time.monotonic() - sample.timestamp > max_age:
            return None
        return sample

    def status(self) -> CameraStatus:
        with self._lock:
            return self._status

    def reset(self) -> None:
        """Drop the neutral reference and the accumulated shift."""
        self._estimator.reset()
        with self._lock:
            self._sample = None

    def set_tap(self, tap) -> None:
        """Route raw frames to ``tap`` as well, or ``None`` to stop.

        Used by the calibration wizard and the clip recorder. Deliberately a
        single slot: two consumers of a 30 Hz camera is a design smell, not a
        feature.
        """
        with self._lock:
            self._tap = tap

    # --- Thread ----------------------------------------------------------

    def _run(self) -> None:
        capture = self._open()
        if capture is None:
            with self._lock:
                self._status = CameraStatus(
                    problem="No camera answered. Another app may be using it."
                )
            return

        name = f"camera {self._camera_index}"
        with self._lock:
            self._status = CameraStatus(running=True, name=name)

        frames = 0
        misses = 0
        window_started = time.monotonic()
        window_frames = 0
        fps = 0.0

        try:
            while not self._stop.is_set():
                ok, frame = capture.read()
                now = time.monotonic()
                if not ok or frame is None:
                    misses += 1
                    self._publish(self._estimator.note_dropped_frame(now))
                    if misses > TARGET_FPS * 2:
                        with self._lock:
                            self._status = CameraStatus(
                                running=False,
                                problem="The camera stopped sending frames.",
                                frames=frames,
                                name=name,
                            )
                        return
                    time.sleep(0.02)
                    continue

                misses = 0
                frames += 1
                window_frames += 1
                if now - window_started >= 1.0:
                    fps = window_frames / (now - window_started)
                    window_started, window_frames = now, 0

                with self._lock:
                    tap = self._tap
                if tap is not None:
                    try:
                        tap(frame, now)
                    except Exception:
                        log.exception("frame tap failed")

                self._publish(self._estimator.feed(frame, now))
                with self._lock:
                    self._status = CameraStatus(
                        running=True, frames=frames, fps=fps, name=name
                    )
        finally:
            capture.release()
            log.info("camera closed after %d frames", frames)

    def _publish(self, sample: AngleSample | None) -> None:
        if sample is None:
            return
        with self._lock:
            self._sample = sample

    def _open(self):
        """Open the camera, preferring the backend that lets us set exposure.

        DirectShow first: Media Foundation is the modern backend but takes over a
        second to open on many machines and refuses manual exposure on more of
        them. Media Foundation is the fallback because some newer cameras ship no
        DirectShow filter at all.
        """
        for backend, label in (
            (cv2.CAP_DSHOW, "DirectShow"),
            (cv2.CAP_MSMF, "Media Foundation"),
        ):
            capture = cv2.VideoCapture(self._camera_index, backend)
            if not capture.isOpened():
                capture.release()
                continue
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_WIDTH)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
            capture.set(cv2.CAP_PROP_FPS, TARGET_FPS)
            # One frame of buffer, so a read returns what the camera sees now
            # rather than what it saw three frames ago.
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self._force_short_exposure(capture, backend)
            ok, _ = capture.read()
            if ok:
                log.info("camera %d opened via %s", self._camera_index, label)
                return capture
            capture.release()
        return None

    def _force_short_exposure(self, capture, backend) -> None:
        try:
            if backend == cv2.CAP_DSHOW:
                capture.set(cv2.CAP_PROP_AUTO_EXPOSURE, _DSHOW_MANUAL_EXPOSURE)
            else:
                capture.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0)
            capture.set(cv2.CAP_PROP_EXPOSURE, MANUAL_EXPOSURE)
            capture.set(cv2.CAP_PROP_GAIN, 255)
        except cv2.error:
            # Plenty of cameras simply refuse. Auto exposure still works, it
            # just smears during fast movement, and the tracker's confidence
            # score already notices when that happens.
            log.info("camera would not accept a manual exposure")
