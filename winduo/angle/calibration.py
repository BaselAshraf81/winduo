"""Fitting shift-to-degrees from a guided three-position sweep.

Only one number really matters: how many degrees of lid rotation one pixel of
vertical image shift represents. A single closed-form fit recovers it, plus a
second-order term for the two effects that make the relationship not quite
linear.

Where the nonlinearity comes from, since it is easy to assume there isn't any:

1. The projection is a tangent, not a ratio. A point at image height ``y``
   moves by ``f * dtheta * (1 + y^2 / f^2)``, so shift per degree grows toward
   the edges of the frame.
2. The camera swings on an arc. It sits roughly 20 cm from the hinge, so one
   degree of closing also translates it about 3.5 mm. Against a scene one metre
   away that parallax adds around 20% to the apparent shift; at three metres,
   about 6%. The error depends on how far away the room is, which is why the
   wizard asks the user to sit where they normally sit rather than to measure
   anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, auto

from winduo.config import Calibration
from winduo.log import get_logger

log = get_logger("calibration")

__all__ = ["CalibrationSession", "Stage", "fit", "TYPICAL_VIEWING_ANGLE"]

#: Where a laptop lid usually sits in use, in degrees from shut. The wizard
#: offers this as the starting position of the angle picker.
TYPICAL_VIEWING_ANGLE = 100.0

#: The second-order term is a correction, not a free parameter. Beyond this it
#: is fitting noise, and an over-fitted curve makes the effect worse at angles
#: the wizard never visited.
_MAX_CURVATURE = 0.004


def fit(
    viewing_angle: float,
    shift_at_halfway: float,
    shift_at_closed: float,
    track_width: int,
    camera_name: str = "",
) -> Calibration:
    """Solve for degrees per pixel and the curvature term.

    Shifts are cumulative pixels since the lid left the viewing position, so the
    viewing position itself is the origin and contributes ``(0, 0)``.

    The model is ``degrees = k * s * (1 + c * |s|)``. Two anchors, two unknowns,
    so this is exact rather than a least-squares fit:

        halfway: viewing_angle / 2 = k * s2 * (1 + c * s2)
        closed:  viewing_angle     = k * s3 * (1 + c * s3)

    Dividing one by the other cancels ``k`` and leaves a linear equation in ``c``.
    """
    s2, s3 = float(shift_at_halfway), float(shift_at_closed)
    total = float(viewing_angle)

    if s3 <= 0 or total <= 0:
        raise ValueError("the sweep recorded no closing travel")

    curvature = 0.0
    # The halfway anchor is only usable if it actually landed between the two
    # ends. A user who overshot it gives no information, and forcing a curve
    # through a bad point is worse than assuming a straight line.
    if 0.15 * s3 < s2 < 0.85 * s3:
        ratio = 0.5  # halfway angle over closed angle
        denominator = ratio * s3 * s3 - s2 * s2
        if abs(denominator) > 1e-9:
            candidate = (s2 - ratio * s3) / denominator
            curvature = max(-_MAX_CURVATURE, min(_MAX_CURVATURE, candidate))
    else:
        log.info(
            "halfway anchor at %.1f px is outside the usable band of a %.1f px "
            "sweep, fitting a straight line instead",
            s2,
            s3,
        )

    shape = s3 * (1.0 + curvature * s3)
    if abs(shape) < 1e-9:
        curvature = 0.0
        shape = s3
    degrees_per_pixel = total / shape

    if degrees_per_pixel <= 0:
        raise ValueError("the sweep produced an impossible scale")

    return Calibration(
        degrees_per_pixel=degrees_per_pixel,
        track_width=int(track_width),
        curvature=curvature,
        neutral_angle_estimate=total,
        measured_span=s3,
        camera_name=camera_name,
        captured_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


class Stage(Enum):
    """Where the wizard is. The interface renders one panel per stage."""

    INTRO = auto()
    #: Lid at the normal viewing position, and the user setting the angle picker.
    VIEWING = auto()
    #: Lid brought roughly halfway down and held.
    HALFWAY = auto()
    #: Lid closing the rest of the way, recorded continuously.
    CLOSING = auto()
    DONE = auto()
    FAILED = auto()


@dataclass
class SweepProgress:
    """What the wizard shows while a stage is running."""

    stage: Stage
    #: Cumulative shift since the viewing position, in tracking pixels.
    shift: float = 0.0
    #: 0 to 1 for stages that need the lid held still.
    hold_progress: float = 0.0
    #: Live tracker confidence, so a dark room can be called out at once.
    confidence: float = 0.0
    message: str = ""


class CalibrationSession:
    """Drives the sweep. Owns no camera and no widgets.

    The wizard feeds it readings and renders whatever it reports, which means the
    whole flow can be tested without a camera or a screen.
    """

    #: How long the lid must be still before an anchor is accepted.
    HOLD_SECONDS = 0.6
    #: How far it may wander during that hold, in tracking pixels.
    HOLD_TOLERANCE = 2.5
    #: Below this much total travel, the user did not really close the lid.
    MINIMUM_SPAN = 12.0

    def __init__(self, track_width: int, camera_name: str = "") -> None:
        self.track_width = track_width
        self.camera_name = camera_name
        self.stage = Stage.INTRO
        self.viewing_angle = TYPICAL_VIEWING_ANGLE
        self.shift = 0.0
        self.result: Calibration | None = None
        self.failure = ""
        self._anchor_halfway: float | None = None
        self._still_since: float | None = None
        self._still_at = 0.0
        self._dark_frames = 0

    # --- Flow ------------------------------------------------------------

    def begin(self) -> None:
        self.stage = Stage.VIEWING
        self.shift = 0.0
        self._reset_hold()

    def confirm_viewing(self, viewing_angle: float) -> None:
        """The user has set the angle picker and the lid is where they said."""
        self.viewing_angle = max(30.0, min(170.0, float(viewing_angle)))
        self.shift = 0.0
        self.stage = Stage.HALFWAY
        self._reset_hold()

    def confirm_halfway(self) -> None:
        self._anchor_halfway = self.shift
        self.stage = Stage.CLOSING
        self._reset_hold()

    def finish(self) -> SweepProgress:
        """Close out the sweep, whether the lid switch fired or the user said so."""
        if self.stage is not Stage.CLOSING:
            return self.progress("")
        if self.shift < self.MINIMUM_SPAN:
            return self._fail(
                "The camera saw almost no movement. Check that nothing is "
                "covering it, then try again in a brighter room."
            )
        try:
            self.result = fit(
                viewing_angle=self.viewing_angle,
                shift_at_halfway=self._anchor_halfway or self.shift / 2,
                shift_at_closed=self.shift,
                track_width=self.track_width,
                camera_name=self.camera_name,
            )
        except ValueError as error:
            return self._fail(str(error))
        self.stage = Stage.DONE
        return self.progress("Calibrated.")

    def cancel(self) -> None:
        self.stage = Stage.INTRO
        self.result = None
        self.failure = ""

    # --- Feeding ---------------------------------------------------------

    def feed(self, shift_delta: float, confidence: float, now: float) -> SweepProgress:
        """One tracker reading. Returns what the wizard should render."""
        if self.stage in (Stage.INTRO, Stage.DONE, Stage.FAILED):
            return self.progress("")

        if confidence > 0.0:
            self.shift += shift_delta
            self._dark_frames = 0
        else:
            self._dark_frames += 1

        # A run of unmeasurable frames during the closing stage is the lid
        # arriving at the keyboard, which is the end of the sweep rather than a
        # failure. Camera trouble at any other stage is a failure.
        if self._dark_frames > 12:
            if self.stage is Stage.CLOSING and self.shift >= self.MINIMUM_SPAN:
                return self.finish()
            if self.stage is not Stage.CLOSING:
                return self._fail(
                    "The camera view went dark. Make sure nothing is covering it."
                )

        self._track_stillness(now)
        return self.progress("", confidence)

    def lid_closed(self) -> SweepProgress:
        """The operating system reported the lid shut. Ground truth for zero."""
        if self.stage is Stage.CLOSING:
            return self.finish()
        return self.progress("")

    # --- Reporting -------------------------------------------------------

    def progress(self, message: str = "", confidence: float = 0.0) -> SweepProgress:
        return SweepProgress(
            stage=self.stage,
            shift=self.shift,
            hold_progress=self.hold_progress,
            confidence=confidence,
            message=message or self.failure,
        )

    @property
    def hold_progress(self) -> float:
        if self._still_since is None or self.stage not in (Stage.VIEWING, Stage.HALFWAY):
            return 0.0
        return min(1.0, (self._elapsed_still) / self.HOLD_SECONDS)

    @property
    def is_holding_steady(self) -> bool:
        return self.hold_progress >= 1.0

    # --- Internals -------------------------------------------------------

    def _track_stillness(self, now: float) -> None:
        if abs(self.shift - self._still_at) > self.HOLD_TOLERANCE:
            self._still_at = self.shift
            self._still_since = now
        elif self._still_since is None:
            self._still_since = now
        self._now = now

    @property
    def _elapsed_still(self) -> float:
        if self._still_since is None:
            return 0.0
        return max(0.0, getattr(self, "_now", self._still_since) - self._still_since)

    def _reset_hold(self) -> None:
        self._still_since = None
        self._still_at = self.shift
        self._dark_frames = 0

    def _fail(self, reason: str) -> SweepProgress:
        self.failure = reason
        self.stage = Stage.FAILED
        log.info("calibration failed: %s", reason)
        return self.progress()
