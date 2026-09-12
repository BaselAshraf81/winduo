"""Where the picture lands on the glass.

Ported from ``DepthOverlay.swift``'s ``DepthGeometry`` (Apache 2.0, Copyright
2026 Makito).

The picture is a sheet hinged to the bottom edge of the screen, turned back in
world space by the angle the lid has travelled. The eye stays where it is while
the glass rotates under it, so the projection takes both the current lid angle
and the eye position.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = ["DepthGeometry", "DEFAULT_NEUTRAL_ANGLE"]

# Where an uncalibrated lid is assumed to be resting, in degrees. Only the
# perspective placement of the eye depends on this, and it is forgiving: the
# effect itself is driven by travel from neutral, not by absolute angle.
DEFAULT_NEUTRAL_ANGLE = 100.0


@dataclass
class DepthGeometry:
    """Projects the hinged sheet's four corners onto the screen."""

    # Past 90 degrees the picture turns its face away from the glass, which
    # inverts it. Clamp short of that.
    max_separation_degrees: float = 88.0

    # The projection divides by depth. Never let it reach zero, however far the
    # eye ends up behind the glass.
    min_depth_fraction: float = 0.1

    def corners(
        self,
        start_angle: float,
        current_angle: float,
        viewing_distance_ratio: float,
        recession: float,
        screen_size: tuple[float, float],
    ) -> list[tuple[float, float]]:
        """Corner positions in screen points, y up, origin bottom-left.

        Returned bottom-left, bottom-right, top-right, top-left.

        ``start_angle`` is the lid angle at which the effect began, so travel is
        measured from there. ``recession`` is degrees the picture turns away
        from the glass per degree the lid closes; 1.0 holds the picture still in
        the room.
        """
        width, height = float(screen_size[0]), float(screen_size[1])
        if width <= 0 or height <= 0:
            raise ValueError("screen_size must be positive")

        start = math.radians(start_angle)
        current = math.radians(current_angle)
        travel = max(start_angle - current_angle, 0.0)
        separation = math.radians(min(recession * travel, self.max_separation_degrees))

        # The eye in world axes, hinge at the origin.
        reach = height * viewing_distance_ratio + height / 2 * math.cos(start)
        rise = height / 2 * math.sin(start)

        # The same eye, measured along the glass and away from it.
        along = reach * math.cos(current) + rise * math.sin(current)
        depth = max(
            reach * math.sin(current) - rise * math.cos(current),
            height * self.min_depth_fraction,
        )

        half = width / 2
        sin_sep = math.sin(separation)
        cos_sep = math.cos(separation)

        def project(x: float, y: float) -> tuple[float, float]:
            scale = depth / (depth + y * sin_sep)
            return (
                half + (x - half) * scale,
                along + (y * cos_sep - along) * scale,
            )

        return [
            project(0.0, 0.0),
            project(width, 0.0),
            project(width, height),
            project(0.0, height),
        ]
