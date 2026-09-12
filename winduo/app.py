"""Wiring. Owns the camera, the capture, the overlay, and the clock that drives them.

The loop is deliberately simple: one timer, re-reading the newest estimate and
re-deciding from scratch each time. Nothing latches, so a stalled camera thread
or a dropped capture backend cannot leave the effect stuck on screen.
"""

from __future__ import annotations

import time

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication

from winduo.angle.camera import CameraAngleSource
from winduo.angle.lidswitch import LidSwitch
from winduo.config import Store
from winduo.effect.controller import EffectController
from winduo.log import get_logger
from winduo.render import win32
from winduo.render.capture import CaptureError, ScreenCapture
from winduo.render.overlay import DepthOverlay, FrameParams

log = get_logger("app")

__all__ = ["Engine", "PreviewSweep"]


class PreviewSweep:
    """A scripted close, so the effect can be seen and tuned without a lid.

    Ported from Mac Duo's preview, and the single most useful thing in this
    project for judging the look. It feeds the same path a real close feeds, so
    what the preview shows is what a close shows.
    """

    def __init__(self, trigger_travel: float, span: float) -> None:
        self.started_at = time.monotonic()
        self.rest = 0.0
        self.deep = trigger_travel + span * 1.15
        self.closing = 1.4
        self.hold = 0.8
        self.opening = 0.6

    def travel(self, now: float) -> float | None:
        """Travel at this moment, or ``None`` once the sweep is over."""
        elapsed = now - self.started_at
        if elapsed < self.closing:
            return self.rest + (self.deep - self.rest) * (elapsed / self.closing)
        if elapsed < self.closing + self.hold:
            return self.deep
        if elapsed < self.closing + self.hold + self.opening:
            fraction = (elapsed - self.closing - self.hold) / self.opening
            return self.deep + (self.rest - self.deep) * fraction
        return None

    @property
    def velocity(self) -> float:
        return self.deep / self.closing


class Engine(QObject):
    """Everything the tray icon needs to talk to."""

    #: Emitted when the status the interface shows may have changed.
    changed = pyqtSignal()
    #: Forwards the OS lid switch. Exists so the calibration wizard has a way to
    #: hear "the lid just shut" without owning a second LidSwitch of its own;
    #: Windows only reports one open/shut pair of callbacks per registration,
    #: and this fans that single signal out to whichever Qt object wants it,
    #: auto-queued onto the receiver's thread because pyqtSignal crossing
    #: threads does that safely.
    lid_state_changed = pyqtSignal(bool)

    #: How long the capture keeps running after the lid stops moving. Long
    #: enough to cover a close that pauses, short enough not to hold a capture
    #: session open all day.
    PREWARM_LINGER = 2.0

    def __init__(self, store: Store) -> None:
        super().__init__()
        self.store = store
        self.controller = EffectController(store.settings)
        self.camera = CameraAngleSource(store.settings, store.calibration)
        self.overlay = DepthOverlay()
        self.capture: ScreenCapture | None = None
        self.lid = LidSwitch(self._on_lid_change)

        self._timer = QTimer(self)
        # The default coarse timer quantises to 5 ms or worse, which is visible
        # as judder in a 60 Hz effect.
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._preview: PreviewSweep | None = None
        self._problem = ""
        self._screen_size = (0.0, 0.0)
        self._running = False
        self._prewarm_until = 0.0
        self._unsubscribe = store.subscribe(self._settings_changed)

    # --- Lifecycle -------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._note_screen()
        self._warm_overlay()
        self.camera.start()
        self.lid.start()
        self._timer.start(int(self.controller.poll_interval * 1000))
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            screen.geometryChanged.connect(lambda _: self._screen_changed())
        QGuiApplication.instance().screenAdded.connect(lambda _: self._screen_changed())
        QGuiApplication.instance().screenRemoved.connect(lambda _: self._screen_changed())
        log.info("engine started")

    def stop(self) -> None:
        self._running = False
        self._timer.stop()
        self._teardown_effect()
        self.overlay.destroy()
        self.camera.stop()
        self.lid.stop()
        self._unsubscribe()
        log.info("engine stopped")

    # --- Status the interface reads ---------------------------------------

    @property
    def problem(self) -> str:
        """One sentence naming whatever is stopping the effect, or empty."""
        if self._problem:
            return self._problem
        status = self.camera.status()
        if status.problem:
            return status.problem
        if not status.running:
            return "Starting the camera."
        if not win32.supports_capture_exclusion():
            return (
                "Windows 10 version 2004 or later is needed to keep the effect "
                "out of its own capture."
            )
        return ""

    @property
    def travel(self) -> float:
        return self.controller.travel

    @property
    def is_effect_running(self) -> bool:
        return self.controller.is_active

    def run_preview(self) -> None:
        """Play the effect once on whatever is on screen."""
        if self._preview is not None or self.controller.is_active:
            return
        settings = self.store.settings
        # Capture first, sweep second. Starting the capture takes up to a couple
        # of seconds while the duplication backend hands over its first frame,
        # and a sweep whose clock started before that wait would be half over by
        # the time anything could be drawn.
        self._ensure_capture()
        # Hold the pre-warm open for the whole sweep, or the first idle tick
        # would release the capture that was just started for it.
        self._prewarm_until = time.monotonic() + 8.0
        self._preview = PreviewSweep(
            settings.trigger_travel, settings.full_effect_travel
        )
        self._timer.setInterval(int(1000 / 60))

    # --- The loop --------------------------------------------------------

    def _tick(self) -> None:
        now = time.monotonic()

        if self._preview is not None:
            self._drive_preview(now)
        else:
            self.controller.observe(self.camera.latest(), now)

        frame = self.controller.step(now)

        if frame is None:
            if self.overlay.is_visible:
                self.overlay.dismiss(animated=True)
            self._update_prewarm(now)
            self._timer.setInterval(int(self.controller.poll_interval * 1000))
            return

        if not self.overlay.is_visible and not self._present():
            return

        self._draw(frame)

        if frame.is_final:
            self.overlay.dismiss(animated=True)
            self._prewarm_until = now + self.PREWARM_LINGER
            self.changed.emit()

        self._timer.setInterval(int(self.controller.poll_interval * 1000))

    def _drive_preview(self, now: float) -> None:
        assert self._preview is not None
        travel = self._preview.travel(now)
        log.debug(
            "preview t=%.3f travel=%s", now - self._preview.started_at, travel
        )
        if travel is None:
            log.debug("preview sweep finished")
            self._preview = None
            return
        from winduo.angle.estimator import AngleSample

        self.controller.observe(
            AngleSample(
                travel=travel,
                velocity=self._preview.velocity,
                confidence=1.0,
                timestamp=now,
                at_rest=False,
                absolute_angle=100.0 - travel,
            ),
            now,
        )

    def _draw(self, frame) -> None:
        settings = self.store.settings
        gradient = self.controller.gradient
        params = FrameParams(
            corners=self.controller.corners(frame, self._screen_size),
            blur_strength=gradient.blur_strength(frame.progress),
            dim_strength=gradient.dim_strength(frame.progress),
            blur_floor=settings.blur_evenness,
            dim_floor=gradient.dim_hinge_floor,
            dim_reach=settings.dim_reach,
            max_blur_radius=settings.max_blur_radius,
            max_dim=settings.max_dim,
        )
        # A held picture takes the first frame and nothing after it, which is what
        # "live rendering off" means.
        wants_frame = settings.live_picture or not self.overlay.has_picture
        new_frame = (
            self.capture.take() if self.capture is not None and wants_frame else None
        )
        self.overlay.submit(new_frame, params)

    # --- Pre-warming -----------------------------------------------------

    def _update_prewarm(self, now: float) -> None:
        """Have the capture already running before the effect needs it.

        Starting Desktop Duplication takes long enough to be felt: the backend
        can spend a second or two before it hands over a first frame, and it
        does that work on whichever thread asked. Doing it at the moment the
        effect triggers would stall the frame loop through exactly the movement
        the effect is supposed to follow.

        So the capture starts as soon as the lid is moving downward at all, well
        before the trigger, and lingers briefly afterwards in case the lid is
        about to move again. A lid sitting still keeps nothing running.
        """
        settings = self.store.settings
        if not settings.enabled:
            self._release_capture()
            return

        travel = self.controller.travel
        approaching = travel > settings.trigger_travel * 0.35
        if approaching:
            self._prewarm_until = now + self.PREWARM_LINGER

        if now < self._prewarm_until:
            self._ensure_capture()
        else:
            self._release_capture()

    def _ensure_capture(self) -> bool:
        if self.capture is not None and self.capture.is_running:
            return True
        try:
            capture = ScreenCapture(
                monitor=0, fps=60, width_cap=self.store.settings.render_width_cap
            )
            capture.start()
        except CaptureError as error:
            self._problem = str(error)
            log.warning("could not start capture: %s", error)
            self.changed.emit()
            return False
        self.capture = capture
        self._problem = ""
        return True

    # --- Presenting ------------------------------------------------------

    def _present(self) -> bool:
        """Bring up the overlay for a new run."""
        if not self._ensure_capture():
            self.controller.suspend()
            self.controller.resume()
            return False

        screen = QGuiApplication.primaryScreen()
        if screen is None or self.capture is None:
            return False

        # The capture backend knows the true panel size; trust it over Qt's
        # scaled geometry.
        self._screen_size = (
            float(self.capture.native_size[0]),
            float(self.capture.native_size[1]),
        )
        if not self.overlay.show(screen.geometry(), self._screen_size, self.capture.size):
            self._problem = "The graphics driver would not start the renderer."
            self.changed.emit()
            return False

        if not self.overlay.excludes_itself_from_capture:
            # Without exclusion, a live picture captures the overlay and feeds it
            # back into itself. One held frame still looks right.
            log.info("no capture exclusion available, holding a single frame")

        self.changed.emit()
        return True

    def _release_capture(self) -> None:
        capture, self.capture = self.capture, None
        if capture is not None:
            capture.stop()

    def _warm_overlay(self) -> None:
        """Build the window and compile the shader before any lid moves."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        self._screen_size = _native_size()
        picture = _picture_size(self._screen_size, self.store.settings.render_width_cap)
        if not self.overlay.warm_up(screen.geometry(), self._screen_size, picture):
            self._problem = "The graphics driver would not start the renderer."

    def _teardown_effect(self) -> None:
        self.overlay.dismiss(animated=False)
        self._release_capture()
        self._preview = None

    # --- Events ----------------------------------------------------------

    def _on_lid_change(self, is_open: bool) -> None:
        # Called from the lid switch thread. The controller only touches plain
        # attributes here, and the timer re-reads them next tick. Emitting the
        # signal is also thread safe; Qt queues it onto whatever thread each
        # connected slot actually lives on.
        if not is_open:
            self.controller.lid_shut()
        self.lid_state_changed.emit(is_open)

    def _settings_changed(self) -> None:
        self.controller.retune(
            self.store.settings, self.store.calibration.neutral_angle_estimate
        )
        self.camera.retune(self.store.settings, self.store.calibration)
        if not self.store.settings.enabled and self.controller.is_active:
            self.controller.suspend()
            self.controller.resume()
            self._teardown_effect()
        self.changed.emit()

    def _screen_changed(self) -> None:
        log.info("screen configuration changed")
        self.controller.suspend()
        self._teardown_effect()
        self._note_screen()
        self.controller.resume()
        self.changed.emit()

    def _note_screen(self) -> None:
        self._screen_size = _native_size()


def _native_size() -> tuple[float, float]:
    """The primary display in device pixels.

    Two coordinate spaces meet here and mixing them puts the picture in the
    wrong place. Qt reports window geometry in logical pixels, which on a
    display scaled to 125% is smaller than the panel. Desktop Duplication and
    ``gl_FragCoord`` both work in device pixels. The geometry and the shader use
    device pixels; only ``setGeometry`` uses logical ones.
    """
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return (0.0, 0.0)
    rect = screen.geometry()
    ratio = screen.devicePixelRatio()
    return (float(rect.width()) * ratio, float(rect.height()) * ratio)


def _picture_size(native: tuple[float, float], width_cap: int) -> tuple[int, int]:
    """Mirror of the capture layer's downscale, so the warm-up guesses right.

    A warm-up that allocates the wrong texture size costs a reconfigure on the
    first close, which is the stall the warm-up exists to avoid.
    """
    width, height = int(native[0]), int(native[1])
    if width_cap <= 0 or width <= width_cap or width <= 0:
        return (width, height)
    scale = width_cap / width
    return (width_cap, max(2, int(round(height * scale)) // 2 * 2))
