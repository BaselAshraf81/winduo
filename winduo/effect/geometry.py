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

__all__ = ["DepthGeometry", "DEFAULT_NEUTRAL_ANGLE", "Profile", "PROFILE_SAMPLES"]

# Where an uncalibrated lid is assumed to be resting, in degrees. Only the
# perspective placement of the eye depends on this, and it is forgiving: the
# effect itself is driven by travel from neutral, not by absolute angle.
DEFAULT_NEUTRAL_ANGLE = 100.0

#: Lookup entries handed to the shader. 128 keeps the linear interpolation
#: between entries well under a pixel of error on a 4K panel.
PROFILE_SAMPLES = 128

#: Fraction of the height, measured up from the hinge, where the lean begins.
#: Below it the picture is the exact flat sheet held still in the room.
LEAN_START = 0.35


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

    def profile(
        self,
        start_angle: float,
        current_angle: float,
        viewing_distance_ratio: float,
        recession: float,
        top_lean: float,
        screen_size: tuple[float, float],
        samples: int = PROFILE_SAMPLES,
    ) -> Profile:
        """The curved-sheet projection, as a per-row lookup the shader can invert.

        ``corners`` treats the picture as one flat sheet held still in the room.
        That is exact, and at the end of a close it is also unkind: the glass has
        turned so far under a sheet that is still upright that the top half of
        the picture projects off the top of the screen, and what remains is a
        magnified strip of whatever sat just above the hinge.

        Here the sheet stays fixed in the room near the hinge and its upper part
        leans forward, curling back toward the glass. ``top_lean`` is how far:
        0 is the flat sheet exactly, 1 brings the top edge parallel to the
        glass. Content near the top of the screen then tips toward the viewer
        and stays visible, instead of sliding off the glass.

        A bent sheet is not a homography, so the result is a table. Entry ``i``
        describes screen row ``y = i / (samples - 1) * end``: which picture row
        lands there, as a fraction of the height, and the horizontal scale at
        that row. Rows above ``end`` continue the last entry at ``slope``
        picture rows per screen row, which is what lets the blur reach into the
        black margin past the top edge.
        """
        width, height = float(screen_size[0]), float(screen_size[1])
        if width <= 0 or height <= 0:
            raise ValueError("screen_size must be positive")
        samples = max(int(samples), 2)

        start = math.radians(start_angle)
        current = math.radians(current_angle)
        travel = max(start_angle - current_angle, 0.0)
        separation = math.radians(min(recession * travel, self.max_separation_degrees))
        lean = min(max(top_lean, 0.0), 1.0)

        reach = height * viewing_distance_ratio + height / 2 * math.cos(start)
        rise = height / 2 * math.sin(start)
        along = reach * math.cos(current) + rise * math.sin(current)
        depth = max(
            reach * math.sin(current) - rise * math.cos(current),
            height * self.min_depth_fraction,
        )

        # Walk up the sheet by arc length. Below LEAN_START it is the flat sheet;
        # above, its angle to the glass eases off smoothly toward zero.
        steps = samples * 4
        ds = height / steps
        u = b = 0.0
        arc = [0.0]
        rows = [0.0]
        scales = [1.0]
        for i in range(steps):
            mid = (i + 0.5) * ds / height
            ease = _smoothstep(LEAN_START, 1.0, mid)
            angle = separation * (1.0 - lean * ease)
            u += math.cos(angle) * ds
            b += math.sin(angle) * ds
            scale = depth / (depth + b)
            arc.append((i + 1) * ds / height)
            # Monotonic by construction for any eye in front of the glass; the
            # max() only guards the table against float noise at tiny angles.
            rows.append(max(along + (u - along) * scale, rows[-1]))
            scales.append(scale)

        end = rows[-1]
        if end <= 0.0:
            raise ValueError("the sheet projects to nothing")

        table: list[tuple[float, float]] = []
        j = 0
        for i in range(samples):
            target = end * i / (samples - 1)
            while j < steps - 1 and rows[j + 1] < target:
                j += 1
            span = rows[j + 1] - rows[j]
            t = 0.0 if span <= 1e-12 else (target - rows[j]) / span
            t = min(max(t, 0.0), 1.0)
            table.append(
                (
                    arc[j] + (arc[j + 1] - arc[j]) * t,
                    scales[j] + (scales[j + 1] - scales[j]) * t,
                )
            )

        last = rows[-1] - rows[-2]
        slope = (arc[-1] - arc[-2]) / last if last > 1e-12 else 0.0
        return Profile(table=table, end=end, slope=slope, width=width, height=height)



def _smoothstep(edge0: float, edge1: float, x: float) -> float:
    t = min(max((x - edge0) / (edge1 - edge0), 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


@dataclass
class Profile:
    """Screen row to picture row, for the shader. See ``DepthGeometry.profile``."""

    table: list[tuple[float, float]]
    #: Screen row, in points, where the top edge of the picture lands.
    end: float
    #: Picture rows (as a fraction of the height) per screen point above ``end``.
    slope: float
    width: float
    height: float

    def picture_point(self, x: float, y: float) -> tuple[float, float]:
        """Where screen point ``(x, y)`` samples the picture, in picture points.

        The same interpolation the shader does, so tests can check the table
        without a GPU.
        """
        if y >= self.end:
            row, scale = self.table[-1]
            row += (y - self.end) * self.slope
        else:
            position = max(y, 0.0) / self.end * (len(self.table) - 1)
            i = min(int(position), len(self.table) - 2)
            t = position - i
            (r0, s0), (r1, s1) = self.table[i], self.table[i + 1]
            row, scale = r0 + (r1 - r0) * t, s0 + (s1 - s0) * t
        half = self.width / 2
        return (half + (x - half) / scale, row * self.height)

    def flat(self) -> list[float]:
        """The table as a flat float list, for ``glUniform2fv``."""
        return [value for entry in self.table for value in entry]
