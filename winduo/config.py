"""User settings and the calibration record, persisted as JSON.

Two files under ``%APPDATA%\\WinDuo``:

- ``config.json``, everything the settings window can change.
- ``calibration.json``, what the wizard measured. Separate because it is
  hardware truth rather than taste, and resetting settings must not throw it
  away.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from winduo.log import APP_DIR, get_logger

log = get_logger("config")

__all__ = ["Calibration", "Settings", "Store"]

CONFIG_PATH = APP_DIR / "config.json"
CALIBRATION_PATH = APP_DIR / "calibration.json"


@dataclass
class Settings:
    """Everything the settings window owns.

    Angles are degrees of closing travel away from neutral, not absolute lid
    angles. Neutral is wherever the lid last held still, so nothing here needs
    to know the true hinge angle.
    """

    # --- Master switches -------------------------------------------------
    enabled: bool = True
    #: Keep the picture updating, instead of holding the frame from the trigger.
    live_picture: bool = True

    # --- When the effect starts -----------------------------------------
    #: Degrees of closing away from neutral that start the effect.
    trigger_travel: float = 8.0
    #: Further degrees of closing to reach full strength.
    #:
    #: 60 matches the reference implementation's ramp rate, and it is worth not
    #: shortening. Dimming deliberately leads blur, so compressing the ramp hits
    #: the dimming hardest and the picture reaches black before the blur has
    #: developed enough to see. Windows does cut the display partway through a
    #: close, which is an argument for a shorter ramp, but the answer to that is
    #: to let the effect be unfinished rather than to rush it: macOS sleeps
    #: partway through too.
    full_effect_travel: float = 60.0
    #: Degrees of reopening past the trigger before the effect is released.
    #: Stops the effect flickering when the lid hovers on the threshold.
    release_hysteresis: float = 4.0

    # --- Look ------------------------------------------------------------
    #: Gaussian blur radius at the far edge, in points.
    max_blur_radius: float = 135.0
    #: Blur at the hinge edge as a fraction of the blur at the far edge.
    #: 0 blurs the far edge only, 1 blurs the whole picture evenly.
    blur_evenness: float = 0.0
    #: Opacity of the darkening where the blur is at full strength.
    max_dim: float = 1.0
    #: Height at which the dimming reaches full strength, as a fraction of the
    #: screen height.
    dim_reach: float = 0.5

    # --- Perspective -----------------------------------------------------
    #: Eye distance from the middle of the screen, in screen heights.
    viewing_distance: float = 6.0
    #: Degrees the picture turns away from the glass per degree of closing.
    #: 1.0 holds the picture still in the room.
    recession: float = 1.0

    # --- Neutral detection ----------------------------------------------
    #: How long the lid must hold still before its position becomes neutral.
    neutral_settle_seconds: float = 0.4
    #: How far the lid may drift and still count as holding still, in degrees.
    neutral_settle_tolerance: float = 1.5

    # --- Estimator -------------------------------------------------------
    camera_index: int = 0
    #: Estimator confidence below which the effect will not trigger.
    confidence_floor: float = 0.35
    #: Capture the screen no wider than this, in pixels. The picture is
    #: receding and blurring while the effect runs, so full resolution buys
    #: very little and costs a lot of memory bandwidth. 0 means native.
    render_width_cap: int = 1600

    # --- Housekeeping ----------------------------------------------------
    launch_at_login: bool = False
    #: Draw the live travel reading in the tray tooltip.
    show_reading: bool = True
    #: Warn once that the camera indicator will light while armed.
    has_seen_camera_notice: bool = False

    def clamped(self) -> Settings:
        """A copy with every value inside the range the interface offers."""
        out = Settings(**asdict(self))
        out.trigger_travel = _clamp(out.trigger_travel, 2.0, 40.0)
        out.full_effect_travel = _clamp(out.full_effect_travel, 5.0, 70.0)
        out.release_hysteresis = _clamp(out.release_hysteresis, 0.5, 15.0)
        out.max_blur_radius = _clamp(out.max_blur_radius, 10.0, 200.0)
        out.blur_evenness = _clamp(out.blur_evenness, 0.0, 1.0)
        out.max_dim = _clamp(out.max_dim, 0.0, 1.0)
        out.dim_reach = _clamp(out.dim_reach, 0.2, 1.0)
        out.viewing_distance = _clamp(out.viewing_distance, 1.0, 6.0)
        out.recession = _clamp(out.recession, 0.0, 3.0)
        out.neutral_settle_seconds = _clamp(out.neutral_settle_seconds, 0.15, 3.0)
        out.neutral_settle_tolerance = _clamp(out.neutral_settle_tolerance, 0.3, 6.0)
        out.confidence_floor = _clamp(out.confidence_floor, 0.0, 0.95)
        out.camera_index = int(_clamp(out.camera_index, 0, 16))
        out.render_width_cap = int(_clamp(out.render_width_cap, 0, 7680))
        return out


#: Perspective runs the other way from viewing distance in the interface: a
#: nearer eye converges more sharply. These are the two ends of that slider.
NEAREST_EYE = 1.0
FARTHEST_EYE = 6.0


def perspective_from_distance(distance: float) -> float:
    """Slider position, 0 to 1, from an eye distance in screen heights."""
    return (FARTHEST_EYE - distance) / (FARTHEST_EYE - NEAREST_EYE)


def distance_from_perspective(perspective: float) -> float:
    """Eye distance in screen heights, from a slider position 0 to 1."""
    return FARTHEST_EYE - _clamp(perspective, 0.0, 1.0) * (FARTHEST_EYE - NEAREST_EYE)


@dataclass
class Calibration:
    """What the wizard measured about this particular laptop and camera.

    One number carries the effect: how many degrees of lid travel one pixel of
    vertical image shift represents. The rest is provenance, so the interface
    can say when it was measured and on what.
    """

    #: Degrees of lid rotation per pixel of vertical shift, at the correlation
    #: resolution named by ``track_width``. Zero means uncalibrated.
    degrees_per_pixel: float = 0.0
    #: Frame width the shift was measured at. Shifts scale with it, so a
    #: calibration taken at one width is meaningless at another without this.
    track_width: int = 0
    #: A second-order term, fitted from the halfway anchor. Absorbs the tangent
    #: nonlinearity and the parallax from the camera swinging on its arc.
    curvature: float = 0.0
    #: Estimated absolute angle at the position the user called normal viewing.
    #: Only ever used to place the eye for the perspective, which is forgiving.
    neutral_angle_estimate: float = 0.0
    #: Total travel the wizard saw between normal viewing and closed.
    measured_span: float = 0.0
    camera_name: str = ""
    captured_at: str = ""

    @property
    def is_calibrated(self) -> bool:
        return self.degrees_per_pixel > 0.0 and self.track_width > 0

    def travel_for_shift(self, shift_px: float, track_width: int) -> float:
        """Convert accumulated vertical shift in pixels into degrees of travel.

        Positive shift means the image moved down the frame, which is what
        closing the lid does: the camera pitches forward, so the scene rises out
        of the top of the frame and everything below it slides up. The sign
        convention is settled in the estimator; this only scales.
        """
        if not self.is_calibrated:
            return 0.0
        # A shift measured at a different width is proportionally different.
        scaled = shift_px * (self.track_width / max(track_width, 1))
        return scaled * self.degrees_per_pixel * (1.0 + self.curvature * abs(scaled))


DEFAULT_TRACK_WIDTH = 320
#: What one pixel of shift is worth before anyone calibrates, from a 75 degree
#: horizontal field of view at 320 pixels wide. Close enough that the effect
#: works out of the box, wrong enough to be worth the wizard.
FALLBACK_DEGREES_PER_PIXEL = 0.269


def fallback_calibration() -> Calibration:
    return Calibration(
        degrees_per_pixel=FALLBACK_DEGREES_PER_PIXEL,
        track_width=DEFAULT_TRACK_WIDTH,
        neutral_angle_estimate=100.0,
        camera_name="estimated from a typical field of view",
    )


class Store:
    """Loads, saves, and broadcasts changes to settings and calibration."""

    def __init__(
        self,
        config_path: Path = CONFIG_PATH,
        calibration_path: Path = CALIBRATION_PATH,
    ) -> None:
        self._config_path = config_path
        self._calibration_path = calibration_path
        self._lock = threading.RLock()
        self._listeners: list[Callable[[], None]] = []
        self.settings = _load(config_path, Settings).clamped()
        self.calibration = _load(calibration_path, Calibration)
        if not self.calibration.is_calibrated:
            self.calibration = fallback_calibration()

    # --- Change notification --------------------------------------------

    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def _notify(self) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener()
            except Exception:
                log.exception("settings listener failed")

    # --- Mutation --------------------------------------------------------

    def update(self, **changes: Any) -> None:
        """Apply named changes, clamp, persist, and notify."""
        known = {f.name for f in fields(Settings)}
        unknown = set(changes) - known
        if unknown:
            raise KeyError(f"unknown settings: {sorted(unknown)}")
        with self._lock:
            for key, value in changes.items():
                setattr(self.settings, key, value)
            self.settings = self.settings.clamped()
            _save(self._config_path, self.settings)
        self._notify()

    def reset_settings(self) -> None:
        """Back to factory values. Leaves the calibration alone."""
        with self._lock:
            self.settings = Settings()
            _save(self._config_path, self.settings)
        self._notify()

    def save_calibration(self, calibration: Calibration) -> None:
        with self._lock:
            self.calibration = calibration
            _save(self._calibration_path, calibration)
        self._notify()

    def clear_calibration(self) -> None:
        with self._lock:
            self.calibration = fallback_calibration()
            self._calibration_path.unlink(missing_ok=True)
        self._notify()


def _clamp(value: float, low: float, high: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return low
    if value != value:  # NaN
        return low
    return low if value < low else high if value > high else value


def _load(path: Path, kind):
    if not path.exists():
        return kind()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("could not read %s, using defaults", path.name, exc_info=True)
        return kind()
    if not isinstance(raw, dict):
        return kind()
    known = {f.name for f in fields(kind)}
    dropped = set(raw) - known
    if dropped:
        log.info("ignoring retired keys in %s: %s", path.name, sorted(dropped))
    return kind(**{k: v for k, v in raw.items() if k in known})


def _save(path: Path, value) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write beside the target and swap, so a crash mid-write cannot leave a
        # truncated settings file behind.
        scratch = path.with_suffix(path.suffix + ".tmp")
        scratch.write_text(json.dumps(asdict(value), indent=2), encoding="utf-8")
        scratch.replace(path)
    except OSError:
        log.warning("could not save %s", path.name, exc_info=True)
