"""The calibration fit and the wizard's state machine."""

from __future__ import annotations

import pytest

from winduo.angle import calibration as cal
from winduo.angle.calibration import CalibrationSession, Stage, fit


class TestFit:
    def test_a_straight_sweep_gives_a_straight_line(self):
        # Halfway anchor exactly at half the shift means no curvature is needed,
        # and the solver should find none rather than fitting noise.
        result = fit(
            viewing_angle=100.0,
            shift_at_halfway=150.0,
            shift_at_closed=300.0,
            track_width=320,
        )
        assert result.curvature == pytest.approx(0.0, abs=1e-9)
        assert result.degrees_per_pixel == pytest.approx(100.0 / 300.0)
        assert result.travel_for_shift(300.0, 320) == pytest.approx(100.0)
        assert result.travel_for_shift(150.0, 320) == pytest.approx(50.0)

    def test_recovers_a_known_curved_relationship(self):
        # Build a sweep from known constants, then check the solver finds them.
        # k = 0.3 deg/px, c = 0.002, so 100 px maps to 36 degrees.
        k, c, closed = 0.3, 0.002, 100.0
        total = k * closed * (1 + c * closed)
        # The shift at which the model reads half that angle.
        halfway = (-1 + (1 + 4 * c * (total / 2) / k) ** 0.5) / (2 * c)

        result = fit(
            viewing_angle=total,
            shift_at_halfway=halfway,
            shift_at_closed=closed,
            track_width=320,
        )
        assert result.degrees_per_pixel == pytest.approx(k, rel=1e-6)
        assert result.curvature == pytest.approx(c, rel=1e-6)

    def test_the_ends_of_the_sweep_are_always_reproduced(self):
        result = fit(
            viewing_angle=95.0,
            shift_at_halfway=120.0,
            shift_at_closed=280.0,
            track_width=320,
        )
        assert result.travel_for_shift(280.0, 320) == pytest.approx(95.0, rel=1e-6)
        assert result.travel_for_shift(120.0, 320) == pytest.approx(47.5, rel=1e-6)

    def test_curvature_is_capped_rather_than_chasing_a_bad_anchor(self):
        # An anchor barely inside the usable band asks for a wild curve. Fitting
        # it would wreck the angles the sweep never visited.
        result = fit(
            viewing_angle=100.0,
            shift_at_halfway=45.0,
            shift_at_closed=280.0,
            track_width=320,
        )
        assert abs(result.curvature) <= cal._MAX_CURVATURE
        # The closed end still has to land, whatever the curve does.
        assert result.travel_for_shift(280.0, 320) == pytest.approx(100.0, rel=1e-6)

    @pytest.mark.parametrize("halfway", [0.0, 5.0, 275.0, 300.0])
    def test_a_useless_halfway_anchor_falls_back_to_a_straight_line(self, halfway):
        result = fit(
            viewing_angle=100.0,
            shift_at_halfway=halfway,
            shift_at_closed=300.0,
            track_width=320,
        )
        assert result.curvature == 0.0
        assert result.degrees_per_pixel == pytest.approx(100.0 / 300.0)

    def test_records_its_provenance(self):
        result = fit(90.0, 100.0, 200.0, 320, camera_name="Integrated Camera")
        assert result.is_calibrated
        assert result.track_width == 320
        assert result.measured_span == 200.0
        assert result.neutral_angle_estimate == 90.0
        assert result.camera_name == "Integrated Camera"
        assert result.captured_at

    @pytest.mark.parametrize(
        "angle,closed", [(100.0, 0.0), (100.0, -50.0), (0.0, 300.0), (-10.0, 300.0)]
    )
    def test_rejects_an_impossible_sweep(self, angle, closed):
        with pytest.raises(ValueError):
            fit(angle, closed / 2, closed, 320)


class TestSession:
    def drive(self, session: CalibrationSession, steps, now=0.0, confidence=0.9):
        for step in steps:
            now += 1 / 30
            session.feed(step, confidence, now)
        return now

    def test_walks_through_the_stages(self):
        session = CalibrationSession(track_width=320)
        assert session.stage is Stage.INTRO
        session.begin()
        assert session.stage is Stage.VIEWING
        session.confirm_viewing(105.0)
        assert session.stage is Stage.HALFWAY
        assert session.viewing_angle == 105.0
        session.confirm_halfway()
        assert session.stage is Stage.CLOSING

    def test_a_full_sweep_produces_a_calibration(self):
        session = CalibrationSession(track_width=320, camera_name="test")
        session.begin()
        now = self.drive(session, [0.0] * 20)
        session.confirm_viewing(100.0)
        now = self.drive(session, [6.0] * 25, now=now)
        session.confirm_halfway()
        now = self.drive(session, [6.0] * 25, now=now)
        session.finish()

        assert session.stage is Stage.DONE
        assert session.result is not None
        assert session.result.is_calibrated
        assert session.result.neutral_angle_estimate == 100.0
        assert session.result.travel_for_shift(session.shift, 320) == pytest.approx(
            100.0, rel=1e-6
        )

    def test_shift_resets_at_each_anchor(self):
        session = CalibrationSession(track_width=320)
        session.begin()
        self.drive(session, [4.0] * 5)
        assert session.shift == pytest.approx(20.0)
        session.confirm_viewing(100.0)
        assert session.shift == 0.0

    def test_the_lid_switch_ends_the_closing_stage(self):
        session = CalibrationSession(track_width=320)
        session.begin()
        session.confirm_viewing(100.0)
        now = self.drive(session, [8.0] * 20)
        session.confirm_halfway()
        self.drive(session, [8.0] * 20, now=now)
        session.lid_closed()
        assert session.stage is Stage.DONE
        assert session.result is not None

    def test_the_lid_switch_is_ignored_before_the_closing_stage(self):
        session = CalibrationSession(track_width=320)
        session.begin()
        session.lid_closed()
        assert session.stage is Stage.VIEWING

    def test_going_dark_while_closing_counts_as_arriving(self):
        # The camera looking straight at the keyboard from two centimetres away
        # is the end of the sweep, not a fault.
        session = CalibrationSession(track_width=320)
        session.begin()
        session.confirm_viewing(100.0)
        now = self.drive(session, [8.0] * 20)
        session.confirm_halfway()
        now = self.drive(session, [8.0] * 20, now=now)
        self.drive(session, [0.0] * 20, now=now, confidence=0.0)
        assert session.stage is Stage.DONE

    def test_going_dark_before_closing_is_a_failure(self):
        session = CalibrationSession(track_width=320)
        session.begin()
        self.drive(session, [0.0] * 20, confidence=0.0)
        assert session.stage is Stage.FAILED
        assert "covering it" in session.progress().message

    def test_a_sweep_with_no_movement_fails_with_an_explanation(self):
        session = CalibrationSession(track_width=320)
        session.begin()
        session.confirm_viewing(100.0)
        session.confirm_halfway()
        self.drive(session, [0.1] * 10)
        session.finish()
        assert session.stage is Stage.FAILED
        assert session.result is None
        assert "brighter room" in session.progress().message

    def test_holding_still_fills_the_hold_meter(self):
        session = CalibrationSession(track_width=320)
        session.begin()
        assert session.hold_progress == 0.0
        self.drive(session, [0.0] * 30)
        assert session.hold_progress == 1.0
        assert session.is_holding_steady

    def test_moving_empties_the_hold_meter(self):
        session = CalibrationSession(track_width=320)
        session.begin()
        now = self.drive(session, [0.0] * 30)
        assert session.is_holding_steady
        self.drive(session, [10.0] * 2, now=now)
        assert not session.is_holding_steady

    def test_the_viewing_angle_is_clamped_to_something_physical(self):
        session = CalibrationSession(track_width=320)
        session.begin()
        session.confirm_viewing(400.0)
        assert session.viewing_angle == 170.0
        session.cancel()
        session.begin()
        session.confirm_viewing(-20.0)
        assert session.viewing_angle == 30.0

    def test_cancel_returns_to_the_start(self):
        session = CalibrationSession(track_width=320)
        session.begin()
        session.confirm_viewing(100.0)
        session.cancel()
        assert session.stage is Stage.INTRO
        assert session.result is None

    def test_feeding_a_finished_session_changes_nothing(self):
        session = CalibrationSession(track_width=320)
        session.begin()
        session.confirm_viewing(100.0)
        now = self.drive(session, [8.0] * 20)
        session.confirm_halfway()
        self.drive(session, [8.0] * 20, now=now)
        session.finish()
        before = session.shift
        self.drive(session, [50.0] * 10)
        assert session.shift == before
        assert session.stage is Stage.DONE
