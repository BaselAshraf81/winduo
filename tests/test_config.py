"""Settings defaults worth pinning down explicitly.

Not a general-purpose test of every field; those are exercised through the
controller and estimator tests that actually use them. This file exists for
values a user has directly asked to change, so a future edit that quietly
reverts one is caught here rather than discovered by someone closing a lid and
wondering why 8 degrees still triggers it.
"""

from __future__ import annotations

from winduo.config import Settings


class TestDefaults:
    def test_the_effect_starts_at_ten_degrees_of_travel(self):
        # Raised from 8. A lid resting slightly closed, or someone leaning on
        # the desk, could brush past 8 degrees; 10 gives a little more room
        # before anything happens.
        assert Settings().trigger_travel == 10.0

    def test_the_default_survives_a_clamp(self):
        # clamped() rebuilds the dataclass; a default that only lived in the
        # constructor's keyword argument would not survive that round trip.
        assert Settings().clamped().trigger_travel == 10.0


class TestTheLightSettings:
    """``hinge_glow`` and ``reflection_intensity``, added with the macTilt look.

    Here for the same reason as the trigger above: both are values someone can
    set to zero because they do not want the effect, and a clamp that quietly
    forced them back on would be found by a user rather than by a test.
    """

    def test_both_default_to_half(self):
        settings = Settings()
        assert settings.hinge_glow == 0.5
        assert settings.reflection_intensity == 0.5

    def test_zero_survives_the_clamp(self):
        # Zero is the "off" the sliders offer, so it has to be reachable rather
        # than clamped up to some minimum.
        settings = Settings(hinge_glow=0.0, reflection_intensity=0.0).clamped()
        assert settings.hinge_glow == 0.0
        assert settings.reflection_intensity == 0.0

    def test_out_of_range_is_pulled_back_in(self):
        settings = Settings(hinge_glow=5.0, reflection_intensity=-2.0).clamped()
        assert settings.hinge_glow == 1.0
        assert settings.reflection_intensity == 0.0

    def test_the_defaults_survive_a_clamp(self):
        settings = Settings().clamped()
        assert settings.hinge_glow == 0.5
        assert settings.reflection_intensity == 0.5
