"""Shared test fixtures: a synthetic camera scene and an estimator driver."""

from __future__ import annotations

import cv2
import numpy as np

from winduo.angle.estimator import TravelEstimator
from winduo.angle.tracker import ShiftReading
from winduo.config import Calibration

FRAME = 1 / 30

#: A tenth of a degree per pixel keeps the arithmetic in the tests obvious.
CALIBRATION = Calibration(
    degrees_per_pixel=0.1, track_width=320, neutral_angle_estimate=100.0
)


def reading(shift: float, confidence: float = 0.9) -> ShiftReading:
    return ShiftReading(
        shift=shift, drift=0.0, response=0.3, roll=0.0, confidence=confidence
    )


def texture(width: int = 640, height: int = 480, seed: int = 7) -> np.ndarray:
    """A frame with plenty to correlate against, at a realistic scale of detail.

    Pure white noise correlates too well to be a fair test and a flat gradient
    not at all. Blurred noise plus a few hard edges stands in for a room. The
    landmarks are seeded too, so two different seeds are genuinely different
    scenes rather than the same furniture over different noise.
    """
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 255, size=(height, width), dtype=np.uint8)
    base = cv2.GaussianBlur(base, (0, 0), 3.0)
    for _ in range(3):
        x, y = rng.integers(0, width - 160), rng.integers(0, height - 160)
        w, h = rng.integers(60, 160), rng.integers(60, 160)
        cv2.rectangle(base, (x, y), (x + w, y + h), int(rng.integers(0, 255)), -1)
    y = int(rng.integers(40, height - 40))
    cv2.line(base, (0, y), (width, y - 20), 200, 5)
    return cv2.cvtColor(base, cv2.COLOR_GRAY2BGR)


def shifted(frame: np.ndarray, dy_px: float, dx_px: float = 0.0) -> np.ndarray:
    """Translate the frame, positive ``dy_px`` moving content down the image."""
    matrix = np.array([[1, 0, dx_px], [0, 1, dy_px]], dtype=np.float32)
    return cv2.warpAffine(
        frame,
        matrix,
        (frame.shape[1], frame.shape[0]),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT,
    )


class Driver:
    """An estimator plus a monotonic clock.

    The clock has to be shared across every step of a test. Feeding readings
    with timestamps that jump backwards is not something the estimator is meant
    to survive, and a helper that quietly did it would test nothing.
    """

    def __init__(self, calibration: Calibration = CALIBRATION, **kwargs) -> None:
        self.estimator = TravelEstimator(calibration, **kwargs)
        self.now = 0.0
        self.sample = None

    def feed(self, shifts, confidence: float = 0.9):
        """Feed per-frame shifts, one frame apart."""
        for shift in shifts:
            self.now += FRAME
            self.sample = self.estimator.feed_reading(
                reading(shift, confidence), self.now
            )
        return self.sample

    def feed_raw(self, readings):
        for item in readings:
            self.now += FRAME
            self.sample = self.estimator.feed_reading(item, self.now)
        return self.sample

    def settle(self, seconds: float = 1.0, confidence: float = 0.9):
        """Hold perfectly still long enough to establish neutral."""
        return self.feed([0.0] * int(seconds / FRAME), confidence=confidence)

    def drop(self, count: int = 1):
        for _ in range(count):
            self.now += FRAME
            self.sample = self.estimator.note_dropped_frame(self.now)
        return self.sample
