"""Projective mapping of a rectangle onto an arbitrary quadrilateral.

Ported from Mac Duo's ``Homography.swift`` (Apache 2.0, Copyright 2026 Makito).
"""

from __future__ import annotations

import numpy as np

__all__ = ["square_to_quad", "screen_to_picture"]

# Corner order used throughout: bottom-left, bottom-right, top-right, top-left.
_BL, _BR, _TR, _TL = 0, 1, 2, 3


def square_to_quad(width: float, height: float, corners) -> np.ndarray:
    """Map the rectangle ``(0, 0)``..``(width, height)`` onto ``corners``.

    ``corners`` is four ``(x, y)`` pairs listed bottom-left, bottom-right,
    top-right, top-left.

    Returns a 3x3 matrix in column-vector convention, so
    ``screen = M @ (x, y, 1)`` divided by the third component.

    Uses Heckbert's square-to-quad solution on the unit square, then folds in
    ``u = x / width`` and ``v = y / height``.
    """
    pts = np.asarray(corners, dtype=np.float64)
    if pts.shape != (4, 2):
        raise ValueError(f"four corners expected, got shape {pts.shape}")
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")

    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = pts

    dx1, dx2, dx3 = x1 - x2, x3 - x2, x0 - x1 + x2 - x3
    dy1, dy2, dy3 = y1 - y2, y3 - y2, y0 - y1 + y2 - y3

    g = h = 0.0
    if abs(dx3) > 1e-9 or abs(dy3) > 1e-9:
        determinant = dx1 * dy2 - dx2 * dy1
        if abs(determinant) > 1e-12:
            g = (dx3 * dy2 - dx2 * dy3) / determinant
            h = (dx1 * dy3 - dx3 * dy1) / determinant

    a = x1 - x0 + g * x1
    b = x3 - x0 + h * x3
    c = x0
    d = y1 - y0 + g * y1
    e = y3 - y0 + h * y3
    f = y0

    return np.array(
        [
            [a / width, b / height, c],
            [d / width, e / height, f],
            [g / width, h / height, 1.0],
        ],
        dtype=np.float64,
    )


def screen_to_picture(width: float, height: float, corners) -> np.ndarray:
    """The inverse of :func:`square_to_quad`, which is what the shader samples with.

    The fragment shader walks screen pixels and needs to know where each one
    came from in the picture, so it receives this rather than the forward map.
    """
    return np.linalg.inv(square_to_quad(width, height, corners))
