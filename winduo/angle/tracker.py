"""Measures how far the camera image shifted vertically between two frames.

The camera is bolted into the lid, so lid rotation is pure camera pitch: no yaw
and no roll. For scene points far enough away, pitching by ``dtheta`` translates
the whole image vertically by roughly ``f * dtheta`` pixels, where ``f`` is the
focal length in pixels. Closing the lid pitches the camera downward, so the
scene rises out of the top of the frame.

So the entire measurement is one number per frame pair: uniform vertical shift.
Phase correlation finds it in a couple of hundred microseconds at tracking
resolution, and it degrades gracefully instead of failing outright.

This module deliberately knows nothing about cameras, degrees, or lids. It takes
two grayscale images and returns pixels, which is what makes it testable against
synthetic shifts.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from winduo.log import get_logger

log = get_logger("tracker")

__all__ = ["ShiftReading", "ShiftTracker", "prepare"]

#: Width every frame is resampled to before correlating. Small enough to be
#: nearly free, large enough that one pixel is a fraction of a degree.
TRACK_WIDTH = 320


def prepare(frame: np.ndarray, width: int = TRACK_WIDTH) -> np.ndarray:
    """Grayscale, downscale, and convert to float32 for phase correlation.

    Downscaling is the cheapest noise filter available and it costs no
    sensitivity that matters: at 320 pixels wide, one pixel of shift is still
    only about a quarter of a degree.
    """
    if frame.ndim == 3:
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    height, source_width = frame.shape[:2]
    if source_width != width:
        scale = width / source_width
        frame = cv2.resize(
            frame,
            (width, max(int(round(height * scale)), 8)),
            interpolation=cv2.INTER_AREA,
        )
    return frame.astype(np.float32)


@dataclass(frozen=True)
class ShiftReading:
    """One frame pair's worth of measurement.

    ``shift`` is positive when the lid is closing. Phase correlation reports the
    translation from the previous frame to the current one in image coordinates,
    where y runs down, and closing moves content up, so the sign is flipped once
    here and never thought about again.
    """

    shift: float
    #: Horizontal shift in pixels. Should be near zero; the hinge cannot pan.
    drift: float
    #: Phase correlation's own peak sharpness, 0 to 1.
    response: float
    #: How much the left and right halves disagree, in pixels. A rolling camera
    #: makes one side rise while the other falls, and the hinge cannot roll.
    roll: float
    #: 0 to 1. Everything above, folded into one number.
    confidence: float
    #: True when the frame was too dark or too flat to measure at all.
    degenerate: bool = False

    @property
    def usable(self) -> bool:
        return not self.degenerate and self.confidence > 0.0


class ShiftTracker:
    """Accumulates vertical shift across a stream of frames.

    Holds the previous frame and a running total. The total's origin is
    arbitrary; the estimator subtracts a neutral reference from it, so only
    differences ever matter and the absolute value is free to drift.
    """

    def __init__(self, width: int = TRACK_WIDTH) -> None:
        self.width = width
        self.total = 0.0
        self._previous: np.ndarray | None = None
        self._window: np.ndarray | None = None
        self._half_window: np.ndarray | None = None

    def reset(self, total: float = 0.0) -> None:
        self.total = total
        self._previous = None

    def feed(self, frame: np.ndarray) -> ShiftReading | None:
        """Measure against the previous frame. Returns ``None`` for the first one."""
        current = prepare(frame, self.width)
        previous, self._previous = self._previous, current
        if previous is None or previous.shape != current.shape:
            return None

        contrast = float(current.std())
        # A lens cap, a dark room, or a blank wall gives nothing to correlate.
        # Reporting that honestly is much better than reporting a random peak.
        if contrast < 3.0:
            return ShiftReading(0.0, 0.0, 0.0, 0.0, 0.0, degenerate=True)

        window = self._hanning(current.shape)
        (drift, dy), response = cv2.phaseCorrelate(previous, current, window)
        shift = -float(dy)

        roll = self._roll(previous, current)
        confidence = self._confidence(
            shift=shift, drift=float(drift), response=float(response), roll=roll
        )
        return ShiftReading(
            shift=shift,
            drift=float(drift),
            response=float(response),
            roll=roll,
            confidence=confidence,
        )

    def accumulate(self, reading: ShiftReading) -> float:
        """Add a usable reading to the running total and return it."""
        if reading.usable:
            self.total += reading.shift
        return self.total

    # --- Internals -------------------------------------------------------

    def _hanning(self, shape: tuple[int, ...]) -> np.ndarray:
        if self._window is None or self._window.shape != shape:
            self._window = cv2.createHanningWindow(
                (shape[1], shape[0]), cv2.CV_32F
            )
        return self._window

    def _roll(self, previous: np.ndarray, current: np.ndarray) -> float:
        """Vertical shift difference between the left and right halves.

        The hinge is a single axis, so both halves of the image must rise or
        fall together. When they disagree the camera rolled, which means the
        whole laptop moved rather than the lid. Someone picking the machine up,
        or using it in a moving car, looks exactly like a lid close to a
        correlator that only measures the frame as a whole.
        """
        height, width = current.shape[:2]
        half = width // 2
        if half < 32 or height < 32:
            return 0.0
        shape = (height, half)
        if self._half_window is None or self._half_window.shape != shape:
            self._half_window = cv2.createHanningWindow((half, height), cv2.CV_32F)
        window = self._half_window
        try:
            (_, left), _ = cv2.phaseCorrelate(
                np.ascontiguousarray(previous[:, :half]),
                np.ascontiguousarray(current[:, :half]),
                window,
            )
            (_, right), _ = cv2.phaseCorrelate(
                np.ascontiguousarray(previous[:, half : half * 2]),
                np.ascontiguousarray(current[:, half : half * 2]),
                window,
            )
        except cv2.error:
            return 0.0
        return abs(float(left) - float(right))

    def _confidence(
        self, shift: float, drift: float, response: float, roll: float
    ) -> float:
        """Fold the quality signals into one number between 0 and 1.

        Four independent ways a reading can be wrong, each scored 0 to 1 and
        multiplied, so any single strong objection vetoes the reading.
        """
        magnitude = abs(shift)

        # 1. Phase correlation's peak sharpness. Textureless scenes and heavy
        #    motion blur both flatten it.
        peak = _ramp(response, 0.03, 0.25)

        # 2. Horizontal drift. The hinge cannot pan, so sideways motion means
        #    something else moved. Judged relative to the vertical motion,
        #    since a still camera has noise in both axes.
        allowance = max(magnitude * 0.6, 1.5)
        pan = 1.0 - _ramp(abs(drift), allowance, allowance * 3.0)

        # 3. Roll between the halves, on the same relative footing.
        tilt = 1.0 - _ramp(roll, max(magnitude * 0.5, 1.2), max(magnitude * 2.0, 5.0))

        # 4. Implausible speed. Above roughly 45 degrees per frame nothing is
        #    tracking a hinge; it is a scene cut, an autoexposure jump, or the
        #    correlator locking onto the wrong peak.
        plausible = 1.0 - _ramp(magnitude, self.width * 0.25, self.width * 0.5)

        return max(0.0, min(1.0, peak * pan * tilt * plausible))


def _ramp(value: float, low: float, high: float) -> float:
    """0 below ``low``, 1 above ``high``, linear between."""
    if high <= low:
        return 1.0 if value >= high else 0.0
    if value <= low:
        return 0.0
    if value >= high:
        return 1.0
    return (value - low) / (high - low)
