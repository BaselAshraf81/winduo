"""BlurGradient: the travel-driven curves, and the velocity-aware boost."""

from __future__ import annotations

import pytest

from winduo.effect.gradient import BlurGradient


class TestBlurStrength:
    def test_zero_at_the_start(self):
        assert BlurGradient().blur_strength(0.0) == 0.0

    def test_full_at_the_end(self):
        assert BlurGradient().blur_strength(1.0) == 1.0

    def test_monotonic_in_between(self):
        gradient = BlurGradient()
        values = [gradient.blur_strength(p / 10) for p in range(11)]
        assert values == sorted(values)


class TestMotionBoost:
    def test_nothing_below_the_dead_zone(self):
        gradient = BlurGradient()
        assert gradient.motion_boost(0.0) == 0.0
        assert gradient.motion_boost(29.9) == 0.0

    def test_symmetric_in_direction(self):
        # Only speed matters; a fast reopen should boost the same as a fast
        # close, since both are motion the picture has to keep up with.
        gradient = BlurGradient()
        assert gradient.motion_boost(-150.0) == pytest.approx(
            gradient.motion_boost(150.0)
        )

    def test_grows_with_speed_then_saturates(self):
        gradient = BlurGradient()
        low = gradient.motion_boost(60.0)
        high = gradient.motion_boost(200.0)
        maxed = gradient.motion_boost(400.0)
        assert 0.0 < low < high
        assert high <= maxed
        assert maxed == gradient.motion_boost(220.0)

    def test_never_exceeds_its_own_ceiling(self):
        gradient = BlurGradient()
        for speed in (0, 30, 60, 120, 220, 1000):
            assert 0.0 <= gradient.motion_boost(float(speed)) <= 0.35


class TestTurnStrength:
    def test_lags_the_dimming(self):
        # The whole reason turn_strength exists. Dimming is front-loaded on
        # purpose, and the light terms borrowed that curve at first, which made
        # them arrive almost at the trigger instead of growing with the turn.
        gradient = BlurGradient()
        for progress in (0.05, 0.25, 0.5, 0.75):
            assert gradient.turn_strength(progress) < gradient.dim_strength(progress)

    def test_spans_zero_to_one(self):
        gradient = BlurGradient()
        assert gradient.turn_strength(0.0) == 0.0
        assert gradient.turn_strength(1.0) == 1.0

    def test_clamps_outside_the_range(self):
        gradient = BlurGradient()
        assert gradient.turn_strength(-1.0) == 0.0
        assert gradient.turn_strength(2.0) == 1.0


class TestTheBlurTheShaderActuallyReceives:
    """The sum-and-clamp in ``Engine._draw``, which is where these meet.

    Worth testing here rather than through the engine, which needs a screen, a
    camera, and a GL context. The arithmetic is the part that can be wrong.
    """

    @staticmethod
    def _blur(gradient: BlurGradient, progress: float, velocity: float) -> float:
        boost = gradient.motion_boost(velocity) * progress
        return min(gradient.blur_strength(progress) + boost, 1.0)

    def test_a_fast_close_blurs_more_than_a_slow_one(self):
        gradient = BlurGradient()
        slow = self._blur(gradient, 0.5, 10.0)
        fast = self._blur(gradient, 0.5, 200.0)
        assert fast > slow

    def test_never_exceeds_full(self):
        gradient = BlurGradient()
        assert self._blur(gradient, 1.0, 5000.0) == 1.0

    def test_no_boost_survives_the_ease_back_to_flat(self):
        # Velocity is large while the lid is being opened quickly and progress
        # is collapsing at the same time. Without the progress scaling, the last
        # frame before the overlay fades would be the blurriest of the run.
        gradient = BlurGradient()
        assert self._blur(gradient, 0.0, -400.0) == 0.0

    def test_boost_fades_as_the_effect_releases(self):
        gradient = BlurGradient()
        blurs = [self._blur(gradient, p / 10, -400.0) for p in range(11)]
        assert blurs == sorted(blurs)
