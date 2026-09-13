"""The settings window.

Operate mode. Every control names its own action, the live reading sits where
the eye lands first, and anything blocking the effect says so at the top rather
than leaving the user to guess why nothing happens.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from winduo.config import (
    Store,
    distance_from_perspective,
    perspective_from_distance,
)
from winduo.log import get_logger
from winduo.ui.theme import app_icon, ui_font
from winduo.ui.widgets import HoldMeter, Rule, SectionLabel, SliderRow, help_label

log = get_logger("settings")

__all__ = ["SettingsWindow"]


class SettingsWindow(QWidget):
    """A single scrolling column. No tabs; there is not enough here to hide."""

    def __init__(self, store: Store, engine, on_calibrate, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.engine = engine
        self._on_calibrate = on_calibrate
        self._applying = False

        self.setWindowTitle("WinDuo")
        self.setWindowIcon(app_icon())
        self.setFixedWidth(384)
        self.setFont(ui_font(9))

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())
        root.addWidget(Rule())
        root.addWidget(self._build_body(), 1)
        root.addWidget(Rule())
        root.addWidget(self._build_footer())

        self._poll = QTimer(self)
        self._poll.setInterval(120)
        self._poll.timeout.connect(self._refresh_status)
        engine.changed.connect(self._refresh_status)

        self._load_from_store()
        self._refresh_status()

    # --- Header ----------------------------------------------------------

    def _build_header(self) -> QWidget:
        header = QWidget()
        layout = QVBoxLayout(header)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        title = QLabel("WinDuo")
        title.setProperty("role", "title")
        top.addWidget(title)
        top.addStretch(1)

        self._reading = QLabel("--")
        self._reading.setProperty("role", "reading")
        self._reading.setFont(ui_font(14))
        self._reading.setAccessibleName("Travel from neutral")
        self._reading.setMinimumWidth(72)
        self._reading.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self._reading)
        layout.addLayout(top)

        self._reading_caption = QLabel("Degrees closed from where the lid is resting")
        self._reading_caption.setProperty("role", "help")
        self._reading_caption.setFont(ui_font(8))
        layout.addWidget(self._reading_caption)

        self._confidence = HoldMeter()
        self._confidence.setToolTip("How well the camera can currently read the lid")
        layout.addWidget(self._confidence)

        self._problem = QLabel()
        self._problem.setProperty("role", "alert")
        self._problem.setWordWrap(True)
        self._problem.setFont(ui_font(8))
        self._problem.hide()
        layout.addWidget(self._problem)

        return header

    # --- Body ------------------------------------------------------------

    def _build_body(self) -> QWidget:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(16)

        # --- Switches
        switches = QVBoxLayout()
        switches.setSpacing(9)
        self._enabled = QCheckBox("Run the effect")
        self._enabled.toggled.connect(lambda v: self._apply(enabled=v))
        switches.addWidget(self._enabled)
        switches.addWidget(
            help_label("Leans the screen away as you close the lid.")
        )

        self._live = QCheckBox("Keep the picture live")
        self._live.toggled.connect(lambda v: self._apply(live_picture=v))
        switches.addWidget(self._live)
        switches.addWidget(
            help_label("Off holds the frame from the moment the effect started.")
        )
        layout.addLayout(switches)

        # --- Calibration
        layout.addWidget(SectionLabel("Calibration"))
        self._calibration_state = QLabel()
        self._calibration_state.setProperty("role", "notice")
        self._calibration_state.setWordWrap(True)
        self._calibration_state.setFont(ui_font(8))
        layout.addWidget(self._calibration_state)

        calibrate_row = QHBoxLayout()
        calibrate_row.setContentsMargins(0, 0, 0, 0)
        calibrate = QPushButton("Calibrate")
        calibrate.clicked.connect(self._on_calibrate)
        calibrate_row.addWidget(calibrate)
        preview = QPushButton("Preview the effect")
        preview.clicked.connect(self.engine.run_preview)
        calibrate_row.addWidget(preview)
        calibrate_row.addStretch(1)
        layout.addLayout(calibrate_row)

        # --- Start
        layout.addWidget(SectionLabel("How it follows the lid"))
        layout.addWidget(
            help_label(
                "The effect follows the lid the whole way down. It fades in "
                "once you have closed a little, then keeps growing as you keep "
                "closing, and reverses if you open again."
            )
        )

        self._trigger = SliderRow(
            "Fades in after", 2, 40, 10, suffix="\u00b0",
            help_text="How far you can close before anything happens.",
        )
        self._trigger.changed.connect(lambda v: self._apply(trigger_travel=v))
        layout.addWidget(self._trigger)

        self._span = SliderRow(
            "Reaches full strength over", 5, 90, 75, suffix="\u00b0",
            help_text="Degrees of further closing to go from just visible to full.",
        )
        self._span.changed.connect(lambda v: self._apply(full_effect_travel=v))
        layout.addWidget(self._span)

        # --- Look
        layout.addWidget(SectionLabel("Look"))
        self._blur = SliderRow(
            "Blur", 10, 200, 135, suffix=" px",
            help_text="Blur radius at the top edge, furthest from the hinge.",
        )
        self._blur.changed.connect(lambda v: self._apply(max_blur_radius=v))
        layout.addWidget(self._blur)

        self._blur_spread = SliderRow(
            "Blur spread", 0, 1, 0, suffix="%", display_scale=100,
            help_text="0 blurs the top edge only, 100 blurs the whole picture.",
        )
        self._blur_spread.changed.connect(lambda v: self._apply(blur_evenness=v))
        layout.addWidget(self._blur_spread)

        self._dim = SliderRow(
            "Dimming", 0, 1, 1, suffix="%", display_scale=100,
            help_text="How dark the top edge goes.",
        )
        self._dim.changed.connect(lambda v: self._apply(max_dim=v))
        layout.addWidget(self._dim)

        self._dim_reach = SliderRow(
            "Dimming spread", 0.2, 1, 0.5, suffix="%", display_scale=100,
            help_text="Everything above this height goes fully dark.",
        )
        self._dim_reach.changed.connect(lambda v: self._apply(dim_reach=v))
        layout.addWidget(self._dim_reach)

        self._hinge_glow = SliderRow(
            "Hinge glow", 0, 1, 0.5, suffix="%", display_scale=100,
            help_text="A narrow highlight along the hinge, as it catches light while turning.",
        )
        self._hinge_glow.changed.connect(lambda v: self._apply(hinge_glow=v))
        layout.addWidget(self._hinge_glow)

        self._reflection = SliderRow(
            "Reflection", 0, 1, 0.5, suffix="%", display_scale=100,
            help_text="A soft pale band partway up the picture, standing in for the glass.",
        )
        self._reflection.changed.connect(
            lambda v: self._apply(reflection_intensity=v)
        )
        layout.addWidget(self._reflection)

        # --- Perspective
        layout.addWidget(SectionLabel("Perspective"))
        self._recession = SliderRow(
            "Lean back", 0, 3, 1, suffix="\u00d7", decimals=1,
            help_text=(
                "Degrees of lean per degree of closing. 1 holds the picture "
                "still in the room."
            ),
        )
        self._recession.changed.connect(lambda v: self._apply(recession=v))
        layout.addWidget(self._recession)

        self._perspective = SliderRow(
            "Perspective", 0, 1, 0, suffix="%", display_scale=100,
            help_text="0 keeps the sides parallel, 100 converges sharply.",
        )
        self._perspective.changed.connect(
            lambda v: self._apply(viewing_distance=distance_from_perspective(v))
        )
        layout.addWidget(self._perspective)

        # --- Camera
        layout.addWidget(SectionLabel("Camera"))
        self._confidence_floor = SliderRow(
            "Required confidence", 0, 0.95, 0.35, suffix="%", display_scale=100,
            help_text="The effect stays off when the camera reads the lid less clearly than this.",
        )
        self._confidence_floor.changed.connect(
            lambda v: self._apply(confidence_floor=v)
        )
        layout.addWidget(self._confidence_floor)

        self._settle = SliderRow(
            "Treat as resting after", 0.15, 3.0, 0.4, suffix=" s", decimals=2,
            help_text=(
                "How long the lid must hold still before that position becomes "
                "the new neutral."
            ),
        )
        self._settle.changed.connect(lambda v: self._apply(neutral_settle_seconds=v))
        layout.addWidget(self._settle)

        self._render_width = SliderRow(
            "Capture width", 640, 3840, 1600, suffix=" px",
            help_text=(
                "Lower is smoother on a high-resolution screen, and the picture "
                "is blurring anyway."
            ),
        )
        self._render_width.changed.connect(
            lambda v: self._apply(render_width_cap=int(round(v)))
        )
        layout.addWidget(self._render_width)

        layout.addStretch(1)
        area.setWidget(content)
        self._body = content
        return area

    # --- Footer ----------------------------------------------------------

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        layout = QVBoxLayout(footer)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(10)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        reset = QPushButton("Reset")
        reset.clicked.connect(self._reset)
        row.addWidget(reset)
        row.addStretch(1)
        close = QPushButton("Done")
        close.setProperty("role", "primary")
        close.clicked.connect(self.hide)
        close.setDefault(True)
        row.addWidget(close)
        layout.addLayout(row)

        credit = QLabel(
            'Built by <a href="https://baselashraf.com" style="color:#6fa3c7;">'
            "Basel Ashraf</a>. Ported from "
            '<a href="https://github.com/sumimakito/Mac-Duo" '
            'style="color:#6fa3c7;">Mac Duo</a> by Makito. Free for noncommercial use.'
        )
        credit.setOpenExternalLinks(True)
        credit.setWordWrap(True)
        credit.setFont(ui_font(8))
        credit.setProperty("role", "help")
        layout.addWidget(credit)

        support = QLabel(
            'Free, and staying free. If it is worth a coffee: '
            '<a href="https://ko-fi.com/baselashraf" style="color:#6fa3c7;">Ko-fi</a>'
            " &middot; "
            '<a href="https://paypal.me/baselashrafusd" style="color:#6fa3c7;">PayPal</a>'
            " &middot; "
            '<a href="https://liberapay.com/BaselAshraf81/donate" '
            'style="color:#6fa3c7;">Liberapay</a>'
        )
        support.setOpenExternalLinks(True)
        support.setWordWrap(True)
        support.setFont(ui_font(8))
        support.setProperty("role", "help")
        layout.addWidget(support)

        return footer

    # --- Wiring ----------------------------------------------------------

    def _apply(self, **changes) -> None:
        if self._applying:
            return
        self.store.update(**changes)

    def _load_from_store(self) -> None:
        settings = self.store.settings
        self._applying = True
        try:
            self._enabled.setChecked(settings.enabled)
            self._live.setChecked(settings.live_picture)
            self._trigger.set_value(settings.trigger_travel)
            self._span.set_value(settings.full_effect_travel)
            self._blur.set_value(settings.max_blur_radius)
            self._blur_spread.set_value(settings.blur_evenness)
            self._dim.set_value(settings.max_dim)
            self._dim_reach.set_value(settings.dim_reach)
            self._hinge_glow.set_value(settings.hinge_glow)
            self._reflection.set_value(settings.reflection_intensity)
            self._recession.set_value(settings.recession)
            self._perspective.set_value(
                perspective_from_distance(settings.viewing_distance)
            )
            self._confidence_floor.set_value(settings.confidence_floor)
            self._settle.set_value(settings.neutral_settle_seconds)
            self._render_width.set_value(settings.render_width_cap or 1600)
        finally:
            self._applying = False
        self._refresh_calibration()

    def _reset(self) -> None:
        self.store.reset_settings()
        self._load_from_store()

    def _refresh_calibration(self) -> None:
        calibration = self.store.calibration
        if calibration.captured_at:
            when = calibration.captured_at.replace("T", " at ").replace("+00:00", " UTC")
            self._calibration_state.setText(
                f"Measured {when}. A closing lid reads about "
                f"{1 / calibration.degrees_per_pixel:.1f} pixels per degree."
            )
        else:
            self._calibration_state.setText(
                "Not calibrated yet, so the scale is estimated from a typical "
                "camera. Calibrating takes about twenty seconds and makes the "
                "effect start at the angle you actually want."
            )

    def _refresh_status(self) -> None:
        problem = self.engine.problem
        if problem:
            self._problem.setText(problem)
            self._problem.show()
        else:
            self._problem.hide()

        sample = self.engine.camera.latest(max_age=1.0)
        if sample is None:
            self._reading.setText("--")
            self._confidence.set_progress(0.0)
            self._reading_caption.setText("Waiting for the camera")
            return

        self._reading.setText(f"{max(sample.travel, 0.0):.1f}\u00b0")
        self._confidence.set_progress(sample.confidence, steady=sample.at_rest)
        if self.engine.is_effect_running:
            self._reading_caption.setText("The effect is running")
        elif sample.at_rest:
            self._reading_caption.setText("Resting. This position is neutral.")
        else:
            self._reading_caption.setText(
                "Degrees closed from where the lid was resting"
            )

    # --- Window ----------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._load_from_store()
        self._refresh_status()
        self._poll.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        self._poll.stop()

    def closeEvent(self, event) -> None:  # noqa: N802
        # Closing the window must not quit the app; the tray owns the lifetime.
        event.ignore()
        self.hide()
