"""The geometry and easing ports, checked against properties rather than snapshots."""

from __future__ import annotations

import math

import numpy as np
import pytest

from winduo.effect import (
    BlurGradient,
    CriticallyDampedSpring,
    DepthGeometry,
    screen_to_picture,
    square_to_quad,
)


def _apply(matrix: np.ndarray, x: float, y: float) -> tuple[float, float]:
    mapped = matrix @ np.array([x, y, 1.0])
    return float(mapped[0] / mapped[2]), float(mapped[1] / mapped[2])


class TestHomography:
    def test_identity_quad_is_the_identity_map(self):
        matrix = square_to_quad(100, 50, [(0, 0), (100, 0), (100, 50), (0, 50)])
        for x, y in [(0, 0), (100, 50), (37, 11), (50, 25)]:
            assert _apply(matrix, x, y) == pytest.approx((x, y), abs=1e-9)

    def test_corners_land_on_the_named_corners(self):
        quad = [(10, 5), (90, 0), (120, 60), (-5, 70)]
        matrix = square_to_quad(200, 100, quad)
        for (x, y), target in zip(
            [(0, 0), (200, 0), (200, 100), (0, 100)], quad, strict=True
        ):
            assert _apply(matrix, x, y) == pytest.approx(target, abs=1e-6)

    def test_a_trapezoid_keeps_straight_lines_straight(self):
        # Projective maps preserve collinearity. If they did not, the effect
        # would bend the edges of windows.
        matrix = square_to_quad(100, 100, [(0, 0), (100, 0), (80, 60), (20, 60)])
        points = [_apply(matrix, t, 50) for t in (0, 25, 50, 75, 100)]
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        assert ys == pytest.approx([ys[0]] * len(ys), abs=1e-6)
        gaps = np.diff(xs)
        assert gaps == pytest.approx([gaps[0]] * len(gaps), abs=1e-6)

    def test_inverse_round_trips(self):
        quad = [(4, 2), (96, -6), (130, 71), (-14, 66)]
        forward = square_to_quad(200, 120, quad)
        inverse = screen_to_picture(200, 120, quad)
        for x, y in [(0, 0), (200, 120), (63, 29)]:
            sx, sy = _apply(forward, x, y)
            assert _apply(inverse, sx, sy) == pytest.approx((x, y), abs=1e-6)

    def test_rejects_bad_input(self):
        with pytest.raises(ValueError):
            square_to_quad(10, 10, [(0, 0), (1, 0), (1, 1)])
        with pytest.raises(ValueError):
            square_to_quad(0, 10, [(0, 0), (1, 0), (1, 1), (0, 1)])


class TestDepthGeometry:
    screen = (1600.0, 1000.0)

    def test_no_travel_leaves_the_picture_flat(self):
        geometry = DepthGeometry()
        corners = geometry.corners(
            start_angle=100, current_angle=100, viewing_distance_ratio=6, recession=1,
            screen_size=self.screen,
        )
        assert corners[0] == pytest.approx((0.0, 0.0), abs=1e-6)
        assert corners[1] == pytest.approx((1600.0, 0.0), abs=1e-6)
        assert corners[2] == pytest.approx((1600.0, 1000.0), abs=1e-6)
        assert corners[3] == pytest.approx((0.0, 1000.0), abs=1e-6)

    def test_closing_narrows_the_far_edge(self):
        # The far edge is the one that recedes, so it must converge while the
        # hinge edge stays put. This is the whole visual idea in one assertion.
        geometry = DepthGeometry()
        corners = geometry.corners(100, 80, 6, 1, self.screen)
        bottom_width = corners[1][0] - corners[0][0]
        top_width = corners[2][0] - corners[3][0]
        assert top_width < bottom_width
        assert corners[0] == pytest.approx((0.0, 0.0), abs=1e-6)
        assert corners[1] == pytest.approx((1600.0, 0.0), abs=1e-6)

    def test_the_picture_stays_symmetric(self):
        geometry = DepthGeometry()
        corners = geometry.corners(100, 70, 3, 1.5, self.screen)
        middle = self.screen[0] / 2
        assert corners[3][0] - 0 == pytest.approx(
            self.screen[0] - corners[2][0], abs=1e-6
        )
        assert (corners[2][0] + corners[3][0]) / 2 == pytest.approx(middle, abs=1e-6)

    def test_more_travel_recedes_further(self):
        geometry = DepthGeometry()
        widths = []
        for current in (100, 90, 80, 70, 60):
            corners = geometry.corners(100, current, 6, 1, self.screen)
            widths.append(corners[2][0] - corners[3][0])
        assert widths == sorted(widths, reverse=True)

    def test_separation_is_clamped_so_the_picture_never_inverts(self):
        geometry = DepthGeometry(max_separation_degrees=88)
        # Recession of 3 over 60 degrees of travel asks for 180 degrees, which
        # would turn the picture inside out.
        corners = geometry.corners(100, 40, 6, 3, self.screen)
        top_width = corners[2][0] - corners[3][0]
        assert top_width > 0
        assert corners[2][1] > corners[0][1]

    def test_opening_past_the_start_does_not_flip(self):
        geometry = DepthGeometry()
        corners = geometry.corners(100, 120, 6, 1, self.screen)
        assert corners[2][0] - corners[3][0] == pytest.approx(1600.0, abs=1e-6)

    def test_rejects_a_degenerate_screen(self):
        with pytest.raises(ValueError):
            DepthGeometry().corners(100, 90, 6, 1, (0, 100))


class TestCriticallyDampedSpring:
    def test_converges_without_overshooting(self):
        spring = CriticallyDampedSpring(value=0.0, frequency=16.0)
        seen = [spring.advance(10.0, 1 / 120) for _ in range(400)]
        assert seen[-1] == pytest.approx(10.0, abs=1e-3)
        assert max(seen) <= 10.0 + 1e-9

    def test_is_monotonic_toward_the_target(self):
        spring = CriticallyDampedSpring(value=0.0)
        seen = [spring.advance(5.0, 1 / 60) for _ in range(200)]
        assert all(b >= a - 1e-12 for a, b in zip(seen, seen[1:], strict=False))

    def test_reset_clears_momentum(self):
        spring = CriticallyDampedSpring(value=0.0)
        for _ in range(10):
            spring.advance(10.0, 1 / 60)
        assert spring.velocity > 0
        spring.reset(3.0)
        assert (spring.value, spring.velocity) == (3.0, 0.0)

    def test_stays_stable_at_the_clamped_step_the_controller_allows(self):
        # The controller clamps dt to 1/20 s. Semi-implicit Euler holds while
        # frequency * dt stays under 2, and 16/20 is 0.8.
        spring = CriticallyDampedSpring(value=0.0, frequency=16.0)
        seen = [spring.advance(1.0, 1 / 20) for _ in range(200)]
        assert seen[-1] == pytest.approx(1.0, abs=1e-3)
        assert all(math.isfinite(v) for v in seen)


class TestBlurGradient:
    def test_ends_are_pinned(self):
        gradient = BlurGradient()
        assert gradient.blur_strength(0) == 0.0
        assert gradient.blur_strength(1) == 1.0
        assert gradient.dim_strength(0) == 0.0
        assert gradient.dim_strength(1) == 1.0

    def test_clamps_outside_the_range(self):
        gradient = BlurGradient()
        assert gradient.blur_strength(-3) == 0.0
        assert gradient.dim_strength(9) == 1.0

    def test_blur_starts_slowly_and_dimming_starts_quickly(self):
        # The curves are deliberately different: the blur should hold off so the
        # picture stays readable as it begins to move, while the dimming leads.
        gradient = BlurGradient()
        assert gradient.blur_strength(0.5) < 0.5
        assert gradient.dim_strength(0.5) > 0.5
