"""The shift tracker, driven with synthetic frames so no camera is involved."""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from helpers import shifted, texture

from winduo.angle.tracker import TRACK_WIDTH, ShiftTracker, prepare


class TestPrepare:
    def test_downscales_to_the_tracking_width_and_keeps_aspect(self):
        out = prepare(texture(1280, 720))
        assert out.shape[1] == TRACK_WIDTH
        assert out.shape[0] == pytest.approx(TRACK_WIDTH * 720 / 1280, abs=1)
        assert out.dtype == np.float32

    def test_accepts_grayscale_as_well_as_colour(self):
        colour = texture()
        gray = cv2.cvtColor(colour, cv2.COLOR_BGR2GRAY)
        assert prepare(colour).shape == prepare(gray).shape


class TestShiftTracker:
    def test_first_frame_has_nothing_to_compare_against(self):
        assert ShiftTracker().feed(texture()) is None

    def test_a_still_camera_reports_no_shift(self):
        tracker = ShiftTracker()
        frame = texture()
        tracker.feed(frame)
        reading = tracker.feed(frame.copy())
        assert reading is not None
        assert reading.shift == pytest.approx(0.0, abs=0.05)
        assert reading.confidence > 0.5

    @pytest.mark.parametrize("content_dy", [-2.0, -6.0, -14.0, 3.0, 9.0])
    def test_recovers_the_shift_it_was_given(self, content_dy):
        # Closing the lid pitches the camera down, so content rises: negative
        # dy in image coordinates. The tracker flips the sign, so closing must
        # come back positive.
        tracker = ShiftTracker()
        frame = texture()
        tracker.feed(frame)
        reading = tracker.feed(shifted(frame, content_dy))
        assert reading is not None
        assert reading.shift == pytest.approx(-content_dy * TRACK_WIDTH / 640, abs=0.4)

    def test_closing_gives_a_positive_shift(self):
        tracker = ShiftTracker()
        frame = texture()
        tracker.feed(frame)
        # Content moving up the frame is what closing looks like.
        reading = tracker.feed(shifted(frame, -8.0))
        assert reading is not None
        assert reading.shift > 0

    def test_accumulates_over_a_sweep(self):
        tracker = ShiftTracker()
        frame = texture()
        tracker.feed(frame)
        for step in range(1, 11):
            reading = tracker.feed(shifted(frame, -4.0 * step))
            assert reading is not None
            tracker.accumulate(reading)
        expected = 40.0 * TRACK_WIDTH / 640
        assert tracker.total == pytest.approx(expected, rel=0.06)

    def test_a_dark_frame_is_reported_as_degenerate(self):
        tracker = ShiftTracker()
        dark = np.zeros((480, 640, 3), dtype=np.uint8)
        tracker.feed(dark)
        reading = tracker.feed(dark.copy())
        assert reading is not None
        assert reading.degenerate
        assert reading.confidence == 0.0
        assert not reading.usable

    def test_a_degenerate_reading_does_not_move_the_total(self):
        tracker = ShiftTracker()
        dark = np.zeros((480, 640, 3), dtype=np.uint8)
        tracker.feed(dark)
        reading = tracker.feed(dark.copy())
        assert reading is not None
        assert tracker.accumulate(reading) == 0.0

    def test_sideways_motion_is_distrusted(self):
        # The hinge cannot pan, so horizontal motion means the whole machine
        # moved and the reading should not be trusted to mean a lid angle.
        tracker = ShiftTracker()
        frame = texture()
        tracker.feed(frame)
        clean = tracker.feed(shifted(frame, -8.0))
        tracker.reset()
        tracker.feed(frame)
        panned = tracker.feed(shifted(frame, -8.0, dx_px=30.0))
        assert clean is not None and panned is not None
        assert panned.confidence < clean.confidence

    def test_rotation_is_distrusted(self):
        # Rolling the camera makes one half of the frame rise while the other
        # falls, which a single hinge axis cannot do.
        tracker = ShiftTracker()
        frame = texture()
        centre = (frame.shape[1] / 2, frame.shape[0] / 2)
        rotated = cv2.warpAffine(
            frame,
            cv2.getRotationMatrix2D(centre, 6.0, 1.0),
            (frame.shape[1], frame.shape[0]),
            borderMode=cv2.BORDER_REFLECT,
        )
        tracker.feed(frame)
        reading = tracker.feed(rotated)
        assert reading is not None
        assert reading.roll > 1.0
        assert reading.confidence < 0.4

    def test_an_implausibly_fast_shift_is_distrusted(self):
        # Nothing tracking a hinge moves a third of the frame in one 30 Hz
        # frame. That is a scene cut, an autoexposure jump, or the correlator
        # locking onto the wrong peak.
        tracker = ShiftTracker()
        frame = texture()
        tracker.feed(frame)
        modest = tracker.feed(shifted(frame, -8.0))
        tracker.reset()
        tracker.feed(frame)
        absurd = tracker.feed(shifted(frame, -280.0))
        assert modest is not None and absurd is not None
        assert absurd.confidence < modest.confidence * 0.6

    def test_an_unrelated_scene_is_distrusted(self):
        tracker = ShiftTracker()
        tracker.feed(texture(seed=1))
        reading = tracker.feed(texture(seed=99))
        assert reading is not None
        assert reading.confidence < 0.5

    def test_reset_clears_the_pairing_and_the_total(self):
        tracker = ShiftTracker()
        frame = texture()
        tracker.feed(frame)
        tracker.accumulate(tracker.feed(shifted(frame, -5.0)))
        assert tracker.total != 0.0
        tracker.reset()
        assert tracker.total == 0.0
        assert tracker.feed(frame) is None
