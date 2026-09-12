"""Behaviour of the travel estimator, all driven through the shared clock."""

from __future__ import annotations

import pytest
from helpers import CALIBRATION, Driver

from winduo.angle.estimator import TravelEstimator
from winduo.angle.tracker import ShiftReading
from winduo.config import Calibration


class TestNeutral:
    def test_a_still_lid_reads_no_travel(self):
        driver = Driver()
        sample = driver.settle()
        assert sample is not None
        assert sample.travel == pytest.approx(0.0, abs=1e-9)
        assert sample.at_rest

    def test_rest_needs_the_settle_time_to_pass(self):
        driver = Driver(settle_seconds=0.4)
        early = driver.feed([0.0] * 3)
        assert early is not None and not early.at_rest
        late = driver.feed([0.0] * 15)
        assert late is not None and late.at_rest

    def test_a_new_resting_position_becomes_the_new_zero(self):
        # The point of the whole design. Park the lid somewhere else, wait, and
        # travel goes back to zero there instead of remembering the old spot.
        driver = Driver(settle_seconds=0.4)
        driver.settle()
        moved = driver.feed([8.0] * 10)
        assert moved is not None
        assert moved.travel == pytest.approx(8.0, rel=0.01)

        rested = driver.feed([0.0] * 30)
        assert rested is not None
        assert rested.at_rest
        assert rested.travel == pytest.approx(0.0, abs=1e-6)

    def test_a_slow_close_is_not_swallowed_by_the_neutral_tracker(self):
        # The re-zeroing must not creep along with a deliberate close, or the
        # effect would cancel itself out on exactly the movement it exists for.
        # 5 px per frame is 150 px/s, or 15 degrees per second here: about as
        # slowly as anyone actually closes a lid.
        driver = Driver(settle_seconds=0.4, settle_tolerance=1.5)
        driver.settle()
        sample = driver.feed([5.0] * 30)
        assert sample is not None
        assert sample.travel == pytest.approx(15.0, rel=0.02)
        assert not sample.at_rest

    def test_a_sustained_drift_never_re_zeros_however_long_it_runs(self):
        # The failure this guards against is a sawtooth: a reference with a
        # displacement budget resets that budget every time it trips, so a
        # steady drift re-establishes rest repeatedly and drags the zero with
        # it. Travel then plateaus near the tolerance instead of growing.
        # Tolerance 1.5 degrees over a 0.4 s window rejects anything above
        # 3.75 degrees per second; 2 px per frame is 6 degrees per second.
        driver = Driver(settle_seconds=0.4, settle_tolerance=1.5)
        driver.settle()
        sample = driver.feed([2.0] * 300)
        assert sample is not None
        assert sample.travel == pytest.approx(60.0, rel=0.02)
        assert not sample.at_rest

    def test_motion_slower_than_the_rest_threshold_counts_as_rest(self):
        # The other side of the same threshold. Thermal creep and a settling
        # hinge are not a lid close, and treating them as one would leave the
        # zero permanently unestablished.
        driver = Driver(settle_seconds=0.4, settle_tolerance=1.5)
        driver.settle()
        sample = driver.feed([0.4] * 200)
        assert sample is not None
        assert sample.at_rest
        assert abs(sample.travel) < 1.5

    def test_a_movement_inside_the_tolerance_is_absorbed_into_neutral(self):
        # Deliberate, and the reason the scaling tests below use a tight
        # tolerance. Nudging the lid by less than the tolerance moves the zero
        # rather than producing travel, which is what stops the effect firing
        # every time someone leans on the desk.
        driver = Driver(settle_seconds=0.4, settle_tolerance=1.5)
        driver.settle()
        sample = driver.feed([1.0] * 3)
        assert sample is not None
        assert sample.at_rest
        assert abs(sample.travel) < 0.3

    def test_drift_inside_the_tolerance_does_not_break_rest(self):
        driver = Driver(settle_seconds=0.4, settle_tolerance=2.0)
        driver.settle()
        sample = driver.feed([0.05, -0.05, 0.05, -0.05] * 10)
        assert sample is not None
        assert sample.at_rest


class TestTravel:
    """The shift-to-degrees arithmetic.

    These use a deliberately tight rest tolerance. With the default, a movement
    smaller than the tolerance is absorbed into neutral by design, which is
    correct behaviour but would blur the scaling being checked here. Absorption
    itself is covered in :class:`TestNeutral`.
    """

    def test_closing_accumulates_positive_travel(self):
        driver = Driver(settle_tolerance=0.2)
        driver.settle()
        sample = driver.feed([5.0] * 12)
        assert sample is not None
        assert sample.travel == pytest.approx(6.0, rel=0.01)
        assert sample.is_closing

    def test_opening_past_neutral_gives_negative_travel(self):
        driver = Driver()
        driver.settle()
        sample = driver.feed([-4.0] * 5)
        assert sample is not None
        assert sample.travel < 0
        assert not sample.is_closing

    def test_velocity_matches_the_rate_it_was_fed(self):
        driver = Driver()
        driver.settle()
        # 6 px per frame at 30 Hz is 180 px/s, which at 0.1 deg/px is 18 deg/s.
        sample = driver.feed([6.0] * 12)
        assert sample is not None
        assert sample.velocity == pytest.approx(18.0, rel=0.05)

    def test_a_still_lid_has_no_velocity(self):
        driver = Driver()
        sample = driver.settle()
        assert sample is not None
        assert sample.velocity == pytest.approx(0.0, abs=1e-9)

    def test_curvature_is_applied(self):
        driver = Driver(
            Calibration(
                degrees_per_pixel=0.1,
                track_width=320,
                curvature=0.01,
                neutral_angle_estimate=100.0,
            ),
            settle_tolerance=0.2,
        )
        driver.settle()
        sample = driver.feed([10.0] * 5)
        assert sample is not None
        # 50 px at 0.1 deg/px, times (1 + 0.01 * 50).
        assert sample.travel == pytest.approx(50 * 0.1 * 1.5, rel=0.01)

    def test_a_calibration_from_another_width_is_rescaled(self):
        driver = Driver(
            Calibration(
                degrees_per_pixel=0.05, track_width=640, neutral_angle_estimate=100.0
            ),
            track_width=320,
            settle_tolerance=0.2,
        )
        driver.settle()
        sample = driver.feed([10.0])
        assert sample is not None
        # 10 px at 320 wide is 20 px at the 640 the calibration was taken at.
        assert sample.travel == pytest.approx(20 * 0.05, rel=0.01)

    def test_absolute_angle_is_reported_for_display(self):
        driver = Driver()
        driver.settle()
        sample = driver.feed([50.0])
        assert sample is not None
        assert sample.absolute_angle == pytest.approx(95.0, rel=0.01)

    def test_absolute_angle_never_goes_negative(self):
        driver = Driver()
        driver.settle()
        sample = driver.feed([400.0] * 10)
        assert sample is not None
        assert sample.absolute_angle == 0.0


class TestConfidence:
    def test_builds_up_over_several_good_frames(self):
        driver = Driver()
        first = driver.feed([0.0])
        later = driver.feed([0.0] * 20)
        assert first is not None and later is not None
        assert later.confidence > first.confidence
        assert later.confidence == pytest.approx(0.9, abs=0.05)

    def test_collapses_faster_than_it_recovers(self):
        # One bad frame should stop the effect; one good frame should not start
        # it. The asymmetry is deliberate.
        driver = Driver()
        driver.settle()
        before = driver.estimator._confidence
        bad = driver.feed([0.0] * 2, confidence=0.0)
        assert bad is not None
        dropped = before - bad.confidence
        good = driver.feed([0.0] * 2, confidence=0.9)
        assert good is not None
        assert dropped > (good.confidence - bad.confidence)

    def test_a_degenerate_reading_pulls_confidence_to_nothing(self):
        driver = Driver()
        driver.settle()
        sample = driver.feed_raw(
            [ShiftReading(0.0, 0.0, 0.0, 0.0, 0.0, degenerate=True)] * 10
        )
        assert sample is not None
        assert sample.confidence == 0.0

    def test_low_confidence_blocks_a_new_neutral(self):
        # A dark or bumped stretch must not redefine neutral to somewhere the
        # lid has never been.
        driver = Driver(settle_seconds=0.2)
        driver.settle()
        sample = driver.feed([0.0] * 30, confidence=0.05)
        assert sample is not None
        assert not sample.at_rest

    def test_dropped_frames_bleed_confidence_away(self):
        driver = Driver()
        settled = driver.settle()
        assert settled is not None and settled.confidence > 0.5
        sample = driver.drop(6)
        assert sample is not None
        assert sample.confidence == 0.0
        assert sample.velocity == 0.0

    def test_a_dropped_frame_before_any_reading_reports_nothing(self):
        assert TravelEstimator(CALIBRATION).note_dropped_frame(0.0) is None


class TestLifecycle:
    def test_reset_forgets_the_neutral_reference(self):
        driver = Driver()
        driver.settle()
        moved = driver.feed([20.0] * 3)
        assert moved is not None and moved.travel > 0
        driver.estimator.reset()
        fresh = driver.feed([0.0] * 3)
        assert fresh is not None
        assert fresh.travel == pytest.approx(0.0, abs=1e-9)

    def test_retune_keeps_the_reference(self):
        driver = Driver(settle_tolerance=0.2)
        driver.settle()
        driver.feed([10.0] * 3)
        driver.estimator.retune(settle_seconds=1.2)
        assert driver.estimator.settle_seconds == 1.2
        sample = driver.feed([0.0])
        assert sample is not None
        assert sample.travel == pytest.approx(3.0, rel=0.01)

    def test_an_uncalibrated_record_reports_no_travel(self):
        driver = Driver(Calibration())
        driver.settle()
        sample = driver.feed([50.0] * 5)
        assert sample is not None
        assert sample.travel == 0.0
