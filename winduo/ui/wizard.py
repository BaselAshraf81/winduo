"""The calibration wizard.

One thing to measure and one thing to ask. The camera measures how far the image
shifts; the user supplies one known angle by matching a silhouette, because
that is the single fact no amount of image processing can recover on its own.

The whole flow is four panels in one window, no back-and-forth navigation. A
wizard the user has to steer with one hand while moving a lid with the other has
already failed.
"""

from __future__ import annotations

import time

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from winduo.angle.calibration import (
    TYPICAL_VIEWING_ANGLE,
    CalibrationSession,
    Stage,
)
from winduo.angle.tracker import ShiftTracker
from winduo.log import get_logger
from winduo.ui.theme import app_icon, ui_font
from winduo.ui.widgets import HoldMeter, Rule, SectionLabel, SightlineDial, help_label

log = get_logger("wizard")

__all__ = ["CalibrationWizard"]


class _Panel(QWidget):
    """A stage: a stencilled label, a heading, a line of instruction, a body."""

    def __init__(self, step: str, heading: str, instruction: str) -> None:
        super().__init__()
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(10)

        self.layout_.addWidget(SectionLabel(step))

        self.heading = QLabel(heading)
        self.heading.setProperty("role", "title")
        self.heading.setWordWrap(True)
        self.layout_.addWidget(self.heading)

        self.instruction = QLabel(instruction)
        self.instruction.setWordWrap(True)
        self.instruction.setFont(ui_font(9))
        self.layout_.addWidget(self.instruction)

    def add(self, widget: QWidget) -> None:
        self.layout_.addWidget(widget)

    def add_stretch(self) -> None:
        self.layout_.addStretch(1)


class CalibrationWizard(QWidget):
    """Runs a sweep and saves the result."""

    finished = pyqtSignal(bool)

    def __init__(self, store, engine, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.engine = engine
        self.setWindowTitle("Calibrate WinDuo")
        self.setWindowIcon(app_icon())
        self.setFixedSize(430, 486)
        self.setFont(ui_font(9))

        self._tracker = ShiftTracker(store.calibration.track_width or 320)
        self._session = CalibrationSession(
            track_width=self._tracker.width,
            camera_name=engine.camera.status().name,
        )
        self._confidence = 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        self._stack = QStackedWidget()
        self._build_panels()
        root.addWidget(self._stack, 1)
        root.addWidget(Rule())
        root.addLayout(self._build_actions())

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    # --- Panels ----------------------------------------------------------

    def _build_panels(self) -> None:
        self._intro = _Panel(
            "Before you start",
            "Three positions, about twenty seconds",
            "WinDuo works out how far your lid has moved by watching how far the "
            "camera's view slides. To turn that into degrees it needs to see one "
            "close, and to be told one angle.",
        )
        notice = QLabel(
            "The camera indicator will light while WinDuo is running. Nothing is "
            "recorded, and no image leaves your machine: each frame is compared "
            "with the one before it and then discarded."
        )
        notice.setProperty("role", "notice")
        notice.setWordWrap(True)
        notice.setFont(ui_font(8))
        self._intro.add(notice)
        self._intro.add(
            help_label(
                "Sit the way you normally do, and work in a reasonably lit room. "
                "Both change the measurement."
            )
        )
        self._intro.add_stretch()
        self._stack.addWidget(self._intro)

        self._viewing = _Panel(
            "Step 1 of 3",
            "Set the lid where you normally have it",
            "Now drag the silhouette until it matches. Eyeballing it against a "
            "door frame or a book is close enough.",
        )
        self._dial = SightlineDial(TYPICAL_VIEWING_ANGLE)
        self._viewing.add(self._dial)
        self._viewing_hold = HoldMeter()
        self._viewing.add(self._viewing_hold)
        self._viewing_hint = help_label("Hold the lid still.")
        self._viewing.add(self._viewing_hint)
        self._viewing.add_stretch()
        self._stack.addWidget(self._viewing)

        self._halfway = _Panel(
            "Step 2 of 3",
            "Bring it about halfway down",
            "Roughly halfway between where it was and shut. Then hold it there.",
        )
        self._halfway_hold = HoldMeter()
        self._halfway.add(self._halfway_hold)
        self._halfway_hint = help_label("Hold the lid still.")
        self._halfway.add(self._halfway_hint)
        self._halfway.add_stretch()
        self._stack.addWidget(self._halfway)

        self._closing = _Panel(
            "Step 3 of 3",
            "Now close it the rest of the way",
            "Slowly and steadily, all the way shut. WinDuo will notice when you "
            "get there, so you can stop reading now.",
        )
        self._closing_progress = HoldMeter()
        self._closing.add(self._closing_progress)
        self._closing_hint = help_label("Watching.")
        self._closing.add(self._closing_hint)
        self._closing.add_stretch()
        self._stack.addWidget(self._closing)

        self._result = _Panel("Done", "Calibrated", "")
        self._result_detail = QLabel()
        self._result_detail.setProperty("role", "notice")
        self._result_detail.setWordWrap(True)
        self._result_detail.setFont(ui_font(8))
        self._result.add(self._result_detail)
        self._result.add_stretch()
        self._stack.addWidget(self._result)

    def _build_actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self._cancel = QPushButton("Cancel")
        self._cancel.clicked.connect(self._abandon)
        row.addWidget(self._cancel)
        row.addStretch(1)
        self._advance = QPushButton("Start")
        self._advance.setProperty("role", "primary")
        self._advance.setDefault(True)
        self._advance.clicked.connect(self._on_advance)
        row.addWidget(self._advance)
        return row

    # --- Flow ------------------------------------------------------------

    def start(self) -> None:
        self._session.cancel()
        self._tracker.reset()
        self._confidence = 0.0
        self._stack.setCurrentWidget(self._intro)
        self._advance.setText("Start")
        self._advance.setEnabled(True)
        self._cancel.setText("Cancel")
        self.engine.camera.set_tap(self._on_frame)
        self._timer.start()
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_advance(self) -> None:
        stage = self._session.stage
        if stage is Stage.INTRO:
            self._session.begin()
            self._stack.setCurrentWidget(self._viewing)
            self._advance.setText("This is my usual angle")
        elif stage is Stage.VIEWING:
            self._session.confirm_viewing(self._dial.angle())
            self._stack.setCurrentWidget(self._halfway)
            self._advance.setText("It is halfway")
        elif stage is Stage.HALFWAY:
            self._session.confirm_halfway()
            self._stack.setCurrentWidget(self._closing)
            self._advance.setText("It is shut")
        elif stage is Stage.CLOSING:
            self._session.finish()
            self._show_outcome()
        else:
            self._commit()

    def _show_outcome(self) -> None:
        self._timer.stop()
        self.engine.camera.set_tap(None)
        if self._session.stage is Stage.DONE and self._session.result is not None:
            result = self._session.result
            self._result.heading.setText("Calibrated")
            self._result.instruction.setText(
                "WinDuo now knows how your camera's view moves with the lid."
            )
            per_degree = 1 / result.degrees_per_pixel
            self._result_detail.setText(
                f"Measured over {result.measured_span:.0f} pixels of image movement "
                f"from {result.neutral_angle_estimate:.0f}\u00b0 to shut, which is "
                f"about {per_degree:.1f} pixels per degree."
            )
            self._advance.setText("Save")
        else:
            self._result.heading.setText("That did not work")
            self._result.instruction.setText(self._session.progress().message)
            self._result_detail.setText(
                "Nothing has been changed. You can try again from the tray menu."
            )
            self._advance.setText("Close")
        self._cancel.setText("Try again")
        self._stack.setCurrentWidget(self._result)

    def _commit(self) -> None:
        result = self._session.result
        if result is not None:
            self.store.save_calibration(result)
            self.engine.camera.reset()
            log.info(
                "calibration saved: %.4f deg/px at %d wide, curvature %.5f",
                result.degrees_per_pixel,
                result.track_width,
                result.curvature,
            )
        self.hide()
        self.finished.emit(result is not None)

    def _abandon(self) -> None:
        if self._session.stage in (Stage.DONE, Stage.FAILED):
            # "Try again" from the outcome panel.
            self.start()
            return
        self._timer.stop()
        self.engine.camera.set_tap(None)
        self._session.cancel()
        self.hide()
        self.finished.emit(False)

    # --- Camera ----------------------------------------------------------

    def _on_frame(self, frame, _now: float) -> None:
        """Called on the camera thread. Only measures; never touches widgets."""
        reading = self._tracker.feed(frame)
        if reading is None:
            return
        self._pending = (reading.shift if reading.usable else 0.0, reading.confidence)

    def _tick(self) -> None:
        pending = getattr(self, "_pending", None)
        self._pending = None
        now = time.monotonic()
        if pending is not None:
            shift, confidence = pending
            self._confidence = confidence
            self._session.feed(shift, confidence, now)
        else:
            self._session.feed(0.0, self._confidence, now)

        stage = self._session.stage
        if stage in (Stage.DONE, Stage.FAILED):
            self._show_outcome()
            return

        steady = self._session.is_holding_steady
        progress = self._session.hold_progress

        if stage is Stage.VIEWING:
            self._viewing_hold.set_progress(progress, steady)
            self._viewing_hint.setText(self._hold_text(steady))
            self._advance.setEnabled(steady)
        elif stage is Stage.HALFWAY:
            self._halfway_hold.set_progress(progress, steady)
            self._halfway_hint.setText(self._hold_text(steady))
            self._advance.setEnabled(steady)
        elif stage is Stage.CLOSING:
            span = max(self._session.shift, 1.0)
            self._closing_progress.set_progress(min(span / 240.0, 1.0))
            self._closing_hint.setText(
                f"Seen {self._session.shift:.0f} pixels of movement so far."
            )
            self._advance.setEnabled(self._session.shift >= self._session.MINIMUM_SPAN)

    def _hold_text(self, steady: bool) -> str:
        if self._confidence <= 0.05:
            return "The camera cannot see anything to measure. Check it is not covered."
        if steady:
            return "Holding steady."
        return "Hold the lid still."

    # --- Window ----------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802
        event.ignore()
        self._abandon()
