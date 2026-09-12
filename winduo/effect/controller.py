"""Decides when the effect runs, and drives it while it does.

Ported from ``LidController.swift`` (Apache 2.0, Copyright 2026 Makito), with the
sensor replaced by the camera estimator and absolute angles replaced by travel
from neutral.

One behaviour comes free from that swap and is worth pointing out, because Mac
Duo needs a whole subsystem for it. Its "timeout" setting exists to end the
effect when someone stops the lid partway and leaves it there, since an absolute
angle below the threshold stays below it forever. Here, a lid that stops becomes
the new neutral, travel collapses to zero on its own, and the effect eases back
to flat without anything having to notice. The timeout, its reference angle, its
still-duration, and its awaiting-release flag are all gone.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum, auto

from winduo.angle.estimator import AngleSample
from winduo.config import Settings
from winduo.effect.geometry import DEFAULT_NEUTRAL_ANGLE, DepthGeometry
from winduo.effect.gradient import BlurGradient
from winduo.effect.spring import CriticallyDampedSpring
from winduo.log import get_logger

log = get_logger("controller")

__all__ = ["EffectController", "Phase", "Frame"]


class Phase(Enum):
    #: Nothing on screen. Watching for a close.
    IDLE = auto()
    #: The effect is up and following the lid.
    RUNNING = auto()
    #: Easing back to flat before the overlay fades out.
    CLOSING_OUT = auto()


#: Closing speed that counts as deliberate, in degrees per second. A hand
#: resting on a lid reads under 1.
TRIGGER_SPEED = 4.0

#: How long after the lid last moved downward the effect may still start. A
#: close that pauses for a moment mid-travel should not have to re-earn it.
CLOSING_MEMORY = 1.2

#: Below this the estimate is too noisy to extrapolate usefully.
PREDICTION_SPEED_FLOOR = 30.0

#: Camera pipeline latency the prediction adds on top of the sample's own age.
#: Exposure, transfer, and correlation together land in this range.
PREDICTION_LATENCY = 0.05

#: The overlay stays up at least this long once shown. Prediction can trigger
#: the effect while the newest sample is still short of the threshold, and a
#: run that appears and vanishes within two frames reads as a glitch.
MINIMUM_DURATION = 0.3

#: How close the eased travel must get to zero before the final frame snaps
#: there. Half a degree short, the dimming still darkens the top of the picture
#: by a few percent, and the fade would then reveal a brighter screen behind it.
SETTLE_EPSILON = 0.05

#: Safety net, in case the spring never quite settles.
CLOSING_OUT_TIMEOUT = 1.2

IDLE_INTERVAL = 1.0 / 8
ACTIVE_INTERVAL = 1.0 / 60


@dataclass(frozen=True)
class Frame:
    """What the renderer should draw, or ``None`` from :meth:`EffectController.step`."""

    #: Lid angle the effect started at, for the geometry's eye placement.
    start_angle: float
    #: The eased current angle.
    current_angle: float
    #: 0 to 1, driving blur and dimming.
    progress: float
    #: True on the frame that finishes the ease back to flat.
    is_final: bool = False


class EffectController:
    """Watches travel and decides what the overlay shows.

    Polling is deliberate rather than event-driven, so a stalled camera thread
    cannot wedge the effect on screen: every decision is re-made from the newest
    sample on a fixed cadence, and a missing sample is itself a decision.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.phase = Phase.IDLE
        self.geometry = DepthGeometry()
        self.gradient = BlurGradient()

        self._travel = CriticallyDampedSpring(0.0)
        self._raw_travel = 0.0
        self._velocity = 0.0
        self._confidence = 0.0
        self._neutral_angle = DEFAULT_NEUTRAL_ANGLE
        self._sample_time = 0.0
        self._last_closing = -1e9
        self._started_at = 0.0
        self._closing_out_since = 0.0
        self._last_frame_time = 0.0
        self._suspended = False

    # --- Configuration ---------------------------------------------------

    def retune(self, settings: Settings, neutral_angle: float | None = None) -> None:
        self.settings = settings
        if neutral_angle:
            self._neutral_angle = neutral_angle

    def suspend(self) -> None:
        """The machine is sleeping or the screen configuration changed."""
        self._suspended = True
        self._abandon()

    def resume(self) -> None:
        self._suspended = False
        # A fresh baseline, so waking with a nearly shut lid does not read as
        # closing movement.
        self._raw_travel = 0.0
        self._velocity = 0.0
        self._last_closing = -1e9
        self._travel.reset(0.0)

    @property
    def poll_interval(self) -> float:
        if self.phase is not Phase.IDLE:
            return ACTIVE_INTERVAL
        # Faster polling once the lid is moving at all, so the trigger is not
        # found up to an eighth of a second late.
        if abs(self._velocity) > 1.0 or self._raw_travel > 1.0:
            return ACTIVE_INTERVAL
        return IDLE_INTERVAL

    @property
    def is_active(self) -> bool:
        return self.phase is not Phase.IDLE

    @property
    def travel(self) -> float:
        return self._raw_travel

    # --- Input -----------------------------------------------------------

    def observe(self, sample: AngleSample | None, now: float | None = None) -> None:
        """Take the newest estimate. ``None`` means the camera gave nothing."""
        now = time.monotonic() if now is None else now
        if sample is None:
            # An absent sample is not a still lid, it is an unknown one. Dropping
            # confidence to zero releases the effect rather than freezing it on
            # a stale angle.
            self._confidence = 0.0
            self._velocity = 0.0
            return

        self._raw_travel = sample.travel
        self._velocity = sample.velocity
        self._confidence = sample.confidence
        self._sample_time = sample.timestamp
        if sample.absolute_angle > 0:
            self._neutral_angle = sample.absolute_angle + sample.travel
        if sample.velocity >= TRIGGER_SPEED:
            self._last_closing = now

    def lid_shut(self) -> None:
        """The operating system reported the lid closed. The display is going off."""
        if self.phase is not Phase.IDLE:
            log.info("lid shut, ending the effect")
        self._abandon()

    # --- Decisions -------------------------------------------------------

    def _predicted_travel(self, now: float) -> float:
        """Where the lid is heading, not where the last sample saw it.

        A camera sample is a frame old before it is even measured, and a lid
        closing at 150 degrees per second covers 5 degrees in that time. Without
        this the effect starts visibly late on a quick close.
        """
        if self._velocity < PREDICTION_SPEED_FLOOR:
            return self._raw_travel
        staleness = min(max(now - self._sample_time, 0.0), 0.12)
        return self._raw_travel + self._velocity * (staleness + PREDICTION_LATENCY)

    def _wants_effect(self, now: float) -> bool:
        settings = self.settings
        if not settings.enabled or self._suspended:
            return False
        if self._confidence < settings.confidence_floor:
            return False

        if self.phase is Phase.RUNNING:
            if now - self._started_at <= MINIMUM_DURATION:
                return True
            # Released on the way back up, with hysteresis so a lid hovering on
            # the threshold does not flicker. Travel collapsing to zero because
            # the lid came to rest goes through this same door.
            return self._raw_travel > settings.trigger_travel - settings.release_hysteresis

        # A lid resting below the threshold must not start the effect by itself,
        # so a recent downward movement is required as well as the position.
        closing_recently = now - self._last_closing < CLOSING_MEMORY
        return closing_recently and self._predicted_travel(now) >= settings.trigger_travel

    def step(self, now: float | None = None) -> Frame | None:
        """Advance one frame. Returns what to draw, or ``None`` for nothing."""
        now = time.monotonic() if now is None else now
        dt = self._delta(now)

        wanted = self._wants_effect(now)

        if self.phase is Phase.IDLE and wanted:
            self._begin(now)
        elif self.phase is Phase.RUNNING and not wanted:
            self._begin_closing_out(now)

        if self.phase is Phase.IDLE:
            return None

        target = 0.0 if self.phase is Phase.CLOSING_OUT else max(self._raw_travel, 0.0)
        self._travel.advance(target, dt)

        if self.phase is not Phase.CLOSING_OUT:
            return self._frame(self._travel.value)

        settled = self._travel.value <= SETTLE_EPSILON
        timed_out = now - self._closing_out_since > CLOSING_OUT_TIMEOUT
        if not (settled or timed_out):
            return self._frame(self._travel.value)

        # The frame that fades out has to match the screen behind it exactly, so
        # land on zero rather than just short of it.
        self._travel.reset(0.0)
        self.phase = Phase.IDLE
        return self._frame(0.0, is_final=True)

    # --- Frame construction ----------------------------------------------

    def _frame(self, travel: float, is_final: bool = False) -> Frame:
        settings = self.settings
        span = max(settings.full_effect_travel, 1.0)
        past_trigger = max(travel - settings.trigger_travel, 0.0)
        progress = min(past_trigger / span, 1.0)
        return Frame(
            start_angle=self._neutral_angle - settings.trigger_travel,
            current_angle=self._neutral_angle - travel,
            progress=progress,
            is_final=is_final,
        )

    def corners(self, frame: Frame, screen_size: tuple[float, float]):
        return self.geometry.corners(
            start_angle=frame.start_angle,
            current_angle=frame.current_angle,
            viewing_distance_ratio=self.settings.viewing_distance,
            recession=self.settings.recession,
            screen_size=screen_size,
        )

    # --- Transitions -----------------------------------------------------

    def _begin(self, now: float) -> None:
        self.phase = Phase.RUNNING
        self._started_at = now
        # Start from where the lid actually is, so the picture does not sweep in
        # from flat after a fast close has already passed the threshold.
        self._travel.reset(max(self._raw_travel, 0.0))
        log.info(
            "effect on: travel %.1f deg, predicted %.1f, %.0f deg/s, confidence %.2f",
            self._raw_travel,
            self._predicted_travel(now),
            self._velocity,
            self._confidence,
        )

    def _begin_closing_out(self, now: float) -> None:
        self.phase = Phase.CLOSING_OUT
        self._closing_out_since = now
        log.info("effect easing out: travel %.1f deg", self._raw_travel)

    def _abandon(self) -> None:
        """Stop now, with no ease and no fade. For sleep and for a shut lid."""
        self.phase = Phase.IDLE
        self._travel.reset(0.0)
        self._last_closing = -1e9

    def _delta(self, now: float) -> float:
        last, self._last_frame_time = self._last_frame_time, now
        if last <= 0.0:
            return ACTIVE_INTERVAL
        # Clamped both ways: a long stall must not make the spring explode, and
        # a zero step must not divide by nothing.
        return min(max(now - last, 1.0 / 240), 1.0 / 20)
