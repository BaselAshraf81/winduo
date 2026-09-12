"""Smooths a low-rate angle signal up to the display refresh rate.

Ported from ``CriticallyDampedSpring.swift`` (Apache 2.0, Copyright 2026
Makito). The camera estimator publishes at roughly 30 Hz; the overlay draws at
60 Hz or better.
"""

from __future__ import annotations

__all__ = ["CriticallyDampedSpring"]


class CriticallyDampedSpring:
    """A critically damped spring integrated with semi-implicit Euler.

    Stable while ``frequency * dt`` stays below 2, which the caller guarantees
    by clamping ``dt``.
    """

    __slots__ = ("value", "velocity", "frequency")

    def __init__(self, value: float = 0.0, frequency: float = 16.0) -> None:
        self.value = float(value)
        self.velocity = 0.0
        # Radians per second. Higher follows the target faster and smooths less.
        self.frequency = float(frequency)

    def advance(self, target: float, dt: float) -> float:
        f = self.frequency
        acceleration = f * f * (target - self.value) - 2 * f * self.velocity
        self.velocity += acceleration * dt
        self.value += self.velocity * dt
        return self.value

    def reset(self, value: float) -> None:
        self.value = float(value)
        self.velocity = 0.0
