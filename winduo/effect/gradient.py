"""How far out of focus the picture is, and how much light it has lost.

Ported from ``BlurGradient.swift`` (Apache 2.0, Copyright 2026 Makito).

Height is 0 at the hinge edge and 1 at the far edge. Progress is 0 when the
effect starts and 1 at full strength.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["BlurGradient"]


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


#: Below this speed the estimator's own jitter would read as movement, so the
#: boost starts here rather than at zero. Numerically the same as the
#: controller's PREDICTION_SPEED_FLOOR and for the same reason, but not the same
#: test: the controller only cares about closing and compares a signed value,
#: while this compares speed in either direction.
_MOTION_DEAD_ZONE = 30.0

#: Speed at which the boost is fully in, in degrees per second. A slam shut
#: measures well above this; a deliberate close sits well below it.
_MOTION_SATURATION_SPEED = 220.0

#: Extra blur strength at full boost, added on top of the travel-driven curve.
#: Small on purpose: it is meant to read as the picture catching up to a fast
#: motion, not as a second effect layered over the first.
_MOTION_MAX_BOOST = 0.35


@dataclass(frozen=True)
class BlurGradient:
    # Exponent on the closing travel. Above 1 starts slowly.
    blur_curve: float = 1.6
    # Exponent on the closing travel, for the dimming.
    dim_curve: float = 0.7
    # Dimming at the hinge edge as a fraction of the dimming at the far edge.
    dim_hinge_floor: float = 0.2
    # Exponent on the closing travel, for the hinge and reflection light. Above
    # 1 so the light lags the turn rather than arriving with the dimming.
    turn_curve: float = 1.8

    def blur_strength(self, progress: float) -> float:
        return _clamp01(progress) ** self.blur_curve

    def dim_strength(self, progress: float) -> float:
        return _clamp01(progress) ** self.dim_curve

    def turn_strength(self, progress: float) -> float:
        """How far the picture reads as having turned, for the light terms.

        Separate from :meth:`dim_strength` on purpose. Dimming is deliberately
        front-loaded so the picture starts darkening decisively, and light
        borrowed from that curve appears almost as soon as the effect triggers.
        An exponent above 1 makes the hinge highlight and the reflection band
        lag the turn instead, which is what they are meant to be reporting.
        """
        return _clamp01(progress) ** self.turn_curve

    def motion_boost(self, velocity: float) -> float:
        """Extra blur strength while the lid is moving quickly.

        The idea, not the code, comes from macTilt's velocity-aware blur
        (github.com/lqSky7/iphone-duo-macos-animation, MIT): a lid slammed shut
        should look like it moved fast, the way a real camera would blur it,
        rather than running the same fixed ramp a slow deliberate close does.

        Dead-zoned below :data:`_MOTION_DEAD_ZONE` so camera jitter on an
        almost-still lid adds nothing, and saturates at
        :data:`_MOTION_SATURATION_SPEED` so an extreme slam does not blow the
        blur out past what the mip chain can resolve. Travel-driven blur and
        this are meant to add, not replace one another, which is why this
        returns a small increment rather than its own 0-to-1 curve: the result
        is added directly to :meth:`blur_strength`'s output before that reaches
        the shader.
        """
        speed = abs(velocity)
        if speed <= _MOTION_DEAD_ZONE:
            return 0.0
        span = _MOTION_SATURATION_SPEED - _MOTION_DEAD_ZONE
        eased = _clamp01((speed - _MOTION_DEAD_ZONE) / span)
        return eased * _MOTION_MAX_BOOST
