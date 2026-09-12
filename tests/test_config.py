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
