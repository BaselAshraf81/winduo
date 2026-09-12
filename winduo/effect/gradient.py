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


@dataclass(frozen=True)
class BlurGradient:
    # Exponent on the closing travel. Above 1 starts slowly.
    blur_curve: float = 1.6
    # Exponent on the closing travel, for the dimming.
    dim_curve: float = 0.7
    # Dimming at the hinge edge as a fraction of the dimming at the far edge.
    dim_hinge_floor: float = 0.2

    def blur_strength(self, progress: float) -> float:
        return _clamp01(progress) ** self.blur_curve

    def dim_strength(self, progress: float) -> float:
        return _clamp01(progress) ** self.dim_curve
