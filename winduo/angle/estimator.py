"""Turns vertical image shift into degrees of lid travel away from neutral.

Neutral is wherever the lid last held still. When the shift stops changing for
long enough, the current position becomes the new zero, and travel is measured
from there.

That one decision removes the hardest requirement in the project. Phase
correlation integrates, so an absolute angle built from it would drift without
bound. Travel from a reference that re-zeros on every rest never accumulates
error for longer than a single lid movement, which is a second or two. It also
means the app never needs to know the true hinge angle, so it works with the
laptop on a desk, on a lap, or held at any starting position.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import numpy as np

from winduo.angle.tracker import ShiftReading, ShiftTracker
from winduo.config import Calibration
from winduo.log import get_logger

log = get_logger("estimator")

__all__ = ["AngleSample", "TravelEstimator"]


@dataclass(frozen=True)
class AngleSample:
    """One published estimate."""

    #: Degrees of closing away from neutral. Negative means opened past neutral.
    travel: float
    #: Degrees per second. Positive while closing.
    velocity: float
    #: 0 to 1. Below the configured floor, the effect will not trigger.
    confidence: float
    #: Monotonic timestamp of the frame this came from.
    timestamp: float
    #: True while the lid is considered to be at rest.
    at_rest: bool
    #: Best guess at the absolute lid angle, for display only. The effect never
    #: reads this.
    absolute_angle: float = 0.0

    @property
    def is_closing(self) -> bool:
        return self.velocity > 0.0


@dataclass
class _Rest:
    """Tracks whether the lid has been holding still, and where."""

    shift: float = 0.0
    since: float = 0.0
    established: bool = False


class TravelEstimator:
    """Accumulates shift, decides where neutral is, and publishes travel.

    Not thread safe. The camera thread owns it and hands finished samples across.
    """

    #: Velocity samples kept for the least-squares fit. At 30 Hz this is a
    #: 165 ms window, short enough to react and long enough to reject noise.
    _VELOCITY_WINDOW = 5

    #: Confidence recovers no faster than this per second after a bad patch, so
    #: one lucky frame cannot re-arm the effect.
    _CONFIDENCE_RISE = 4.0
    #: And falls at least this fast, so one bad frame does stop it.
    _CONFIDENCE_FALL = 12.0

    def __init__(
        self,
        calibration: Calibration,
        settle_seconds: float = 0.4,
        settle_tolerance: float = 1.5,
        track_width: int | None = None,
    ) -> None:
        self.calibration = calibration
        self.settle_seconds = settle_seconds
        self.settle_tolerance = settle_tolerance
        self._tracker = ShiftTracker(track_width or _default_width(calibration))
        self._rest = _Rest()
        self._neutral_shift: float | None = None
        self._history: list[tuple[float, float]] = []
        self._rest_window: deque[tuple[float, float]] = deque()
        self._confidence = 0.0
        self._last_sample: AngleSample | None = None

    # --- Configuration ---------------------------------------------------

    @property
    def track_width(self) -> int:
        return self._tracker.width

    def retune(
        self,
        calibration: Calibration | None = None,
        settle_seconds: float | None = None,
        settle_tolerance: float | None = None,
    ) -> None:
        """Adopt new settings without losing the current neutral reference."""
        if calibration is not None:
            self.calibration = calibration
        if settle_seconds is not None:
            self.settle_seconds = settle_seconds
        if settle_tolerance is not None:
            self.settle_tolerance = settle_tolerance

    def reset(self) -> None:
        """Forget everything. Used on wake, on camera restart, and after calibration."""
        self._tracker.reset()
        self._rest = _Rest()
        self._neutral_shift = None
        self._history.clear()
        self._rest_window.clear()
        self._confidence = 0.0
        self._last_sample = None

    # --- Measurement -----------------------------------------------------

    def feed(self, frame: np.ndarray, now: float | None = None) -> AngleSample | None:
        """Measure one camera frame. Returns ``None`` until a pair exists."""
        now = time.monotonic() if now is None else now
        reading = self._tracker.feed(frame)
        if reading is None:
            return None
        return self.feed_reading(reading, now)

    def feed_reading(self, reading: ShiftReading, now: float) -> AngleSample:
        """The half of :meth:`feed` that needs no image, so tests can drive it."""
        self._blend_confidence(reading, now)
        total = self._tracker.accumulate(reading)

        if self._neutral_shift is None:
            self._neutral_shift = total
            self._rest = _Rest(shift=total, since=now, established=True)

        self._update_rest(total, now)
        travel = self._degrees(total - self._neutral_shift)
        velocity = self._velocity(travel, now)

        sample = AngleSample(
            travel=travel,
            velocity=velocity,
            confidence=self._confidence,
            timestamp=now,
            at_rest=self._rest.established,
            absolute_angle=self._absolute(travel),
        )
        self._last_sample = sample
        return sample

    def note_dropped_frame(self, now: float | None = None) -> AngleSample | None:
        """Called when the camera gave nothing. Bleeds confidence away.

        A stalled camera must not leave a stale high-confidence sample standing,
        or the effect can trigger on an angle from a second ago.
        """
        now = time.monotonic() if now is None else now
        self._confidence = max(0.0, self._confidence - 0.15)
        if self._last_sample is None:
            return None
        sample = AngleSample(
            travel=self._last_sample.travel,
            velocity=0.0,
            confidence=self._confidence,
            timestamp=now,
            at_rest=self._rest.established,
            absolute_angle=self._last_sample.absolute_angle,
        )
        self._last_sample = sample
        return sample

    # --- Internals -------------------------------------------------------

    def _degrees(self, shift: float) -> float:
        return self.calibration.travel_for_shift(shift, self._tracker.width)

    def _absolute(self, travel: float) -> float:
        neutral = self.calibration.neutral_angle_estimate or 100.0
        return max(0.0, min(180.0, neutral - travel))

    def _blend_confidence(self, reading: ShiftReading, now: float) -> None:
        target = 0.0 if reading.degenerate else reading.confidence
        last = self._last_sample.timestamp if self._last_sample else now
        dt = max(min(now - last, 0.5), 1e-3)
        rate = self._CONFIDENCE_RISE if target > self._confidence else self._CONFIDENCE_FALL
        step = rate * dt
        delta = target - self._confidence
        if abs(delta) <= step:
            self._confidence = target
        else:
            self._confidence += step if delta > 0 else -step

    def _update_rest(self, total: float, now: float) -> None:
        """Re-zero neutral once the lid has held still long enough.

        Rest is judged by how far the shift ranged over the whole settle window,
        not by how far it has wandered from a single reference point. The
        difference matters: a reference with a displacement budget resets that
        budget every time it trips, so a steady slow drift re-establishes rest
        over and over and drags the zero along behind it. A sustained close
        would then cancel itself out, on exactly the movement the app exists to
        catch. A window has no budget to reset, so any drift faster than
        ``settle_tolerance`` per ``settle_seconds`` can never look like rest,
        however long it goes on.

        Low confidence blocks rest outright. A dark stretch or a bumped laptop
        must not redefine neutral to somewhere the lid has never been.
        """
        window = self._rest_window
        window.append((now, total))
        horizon = now - self.settle_seconds
        while len(window) > 2 and window[0][0] < horizon:
            window.popleft()

        if self._confidence < 0.2:
            window.clear()
            window.append((now, total))
            self._rest = _Rest(shift=total, since=now, established=False)
            return

        spans_the_window = now - window[0][0] >= self.settle_seconds * 0.9
        if len(window) < 3 or not spans_the_window:
            self._rest = _Rest(shift=total, since=window[0][0], established=False)
            return

        values = [value for _, value in window]
        spread = max(values) - min(values)
        if spread > self._shift_for_degrees(self.settle_tolerance):
            self._rest = _Rest(shift=total, since=now, established=False)
            return

        # Averaging the window rather than taking the newest sample keeps the
        # zero from inheriting a frame's worth of correlation noise.
        centre = sum(values) / len(values)
        was_established = self._rest.established
        self._rest = _Rest(shift=centre, since=window[0][0], established=True)
        self._neutral_shift = centre
        if not was_established:
            log.debug("neutral re-zeroed at shift %.2f px", centre)

    def _shift_for_degrees(self, degrees: float) -> float:
        per_pixel = self.calibration.degrees_per_pixel or 0.269
        scale = self.calibration.track_width or self._tracker.width
        return degrees / per_pixel * (self._tracker.width / max(scale, 1))

    def _velocity(self, travel: float, now: float) -> float:
        """Least-squares slope over a short window, in degrees per second.

        A slope beats successive differences here: phase correlation noise is
        roughly a tenth of a pixel per frame, and differencing amplifies it
        while fitting averages it away.
        """
        self._history.append((now, travel))
        if len(self._history) > self._VELOCITY_WINDOW:
            del self._history[0]
        if len(self._history) < 3:
            return 0.0
        times = np.fromiter((t for t, _ in self._history), dtype=np.float64)
        values = np.fromiter((v for _, v in self._history), dtype=np.float64)
        times -= times[0]
        spread = float(((times - times.mean()) ** 2).sum())
        if spread < 1e-9:
            return 0.0
        slope = float(((times - times.mean()) * (values - values.mean())).sum() / spread)
        return slope


def _default_width(calibration: Calibration) -> int:
    from winduo.angle.tracker import TRACK_WIDTH

    return calibration.track_width or TRACK_WIDTH
