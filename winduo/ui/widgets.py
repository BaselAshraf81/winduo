"""Small shared widgets, built in the scene-shop vocabulary.

Two of these carry real information rather than decoration: the sightline dial
is how the wizard asks what angle the lid is at, and the hold meter is how it
says "keep still, nearly there".
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from winduo.ui.theme import Palette, label_font, ui_font

__all__ = ["HoldMeter", "Rule", "SectionLabel", "SightlineDial", "SliderRow", "help_label"]


class Rule(QFrame):
    """A struck chalk line. Structure, not ornament."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "rule")
        self.setFixedHeight(1)
        self.setFrameShape(QFrame.Shape.NoFrame)


class SectionLabel(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("role", "section")
        self.setFont(label_font(8))


def help_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "help")
    label.setWordWrap(True)
    label.setFont(ui_font(8))
    return label


class SliderRow(QWidget):
    """A labelled slider with a live reading and one line of explanation.

    Sliders carry integers internally and a scale factor out, because Qt sliders
    are integer-only and the settings are not.
    """

    changed = pyqtSignal(float)

    def __init__(
        self,
        title: str,
        minimum: float,
        maximum: float,
        value: float,
        suffix: str = "",
        decimals: int = 0,
        display_scale: float = 1.0,
        help_text: str = "",
        steps: int = 200,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._minimum = float(minimum)
        self._maximum = float(maximum)
        self._steps = steps
        self._suffix = suffix
        self._decimals = decimals
        self._display_scale = display_scale

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        self._title = QLabel(title)
        self._title.setFont(ui_font(9))
        self._reading = QLabel()
        self._reading.setProperty("role", "reading")
        self._reading.setFont(ui_font(9, weight=ui_font().weight()))
        self._reading.setAlignment(Qt.AlignmentFlag.AlignRight)
        # Reserve the widest reading so the row does not jitter as it changes.
        widest = self._format(self._maximum)
        self._reading.setMinimumWidth(
            QFontMetrics(self._reading.font()).horizontalAdvance(widest) + 6
        )
        head.addWidget(self._title)
        head.addStretch(1)
        head.addWidget(self._reading)
        layout.addLayout(head)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, steps)
        self._slider.setSingleStep(1)
        self._slider.setPageStep(max(steps // 20, 1))
        self._slider.setAccessibleName(title)
        self._slider.valueChanged.connect(self._on_slider)
        layout.addWidget(self._slider)

        if help_text:
            layout.addWidget(help_label(help_text))

        self.set_value(value)

    def _format(self, value: float) -> str:
        return f"{value * self._display_scale:.{self._decimals}f}{self._suffix}"

    def value(self) -> float:
        span = self._maximum - self._minimum
        return self._minimum + span * (self._slider.value() / self._steps)

    def set_value(self, value: float) -> None:
        span = self._maximum - self._minimum or 1.0
        fraction = (float(value) - self._minimum) / span
        position = int(round(min(max(fraction, 0.0), 1.0) * self._steps))
        blocked = self._slider.blockSignals(True)
        self._slider.setValue(position)
        self._slider.blockSignals(blocked)
        self._refresh()

    def _on_slider(self, _position: int) -> None:
        self._refresh()
        self.changed.emit(self.value())

    def _refresh(self) -> None:
        reading = self._format(self.value())
        self._reading.setText(reading)
        self._slider.setAccessibleDescription(reading)


class HoldMeter(QWidget):
    """Fills while the lid is held still. A paint stroke laid down left to right."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._progress = 0.0
        self._steady = False
        self.setFixedHeight(4)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_progress(self, progress: float, steady: bool = False) -> None:
        progress = min(max(float(progress), 0.0), 1.0)
        if abs(progress - self._progress) < 0.005 and steady == self._steady:
            return
        self._progress = progress
        self._steady = steady
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(Palette.FRAME))
        painter.drawRoundedRect(QRectF(0, 1, self.width(), 2), 1, 1)
        if self._progress <= 0:
            return
        painter.setBrush(
            QColor(Palette.GOOD if self._steady else Palette.OXIDE)
        )
        painter.drawRoundedRect(
            QRectF(0, 0, self.width() * self._progress, 4), 2, 2
        )


class SightlineDial(QWidget):
    """Drag to match how far open the lid actually is.

    This is the one thing the wizard genuinely cannot measure. Everything else
    comes from the camera, but the scale needs one known angle, so the user
    supplies it by matching a silhouette to the machine in front of them. A
    silhouette is answerable by eye in a second; a number in degrees is not.
    """

    changed = pyqtSignal(float)

    MINIMUM = 40.0
    MAXIMUM = 160.0

    def __init__(self, angle: float = 100.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._angle = angle
        # Tall enough that the degree graticule outside the lid arc still fits.
        # Sized from the arc rather than guessed: see _lid_length.
        self.setMinimumHeight(214)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Lid angle")
        self._update_description()

    # --- Value -----------------------------------------------------------

    def angle(self) -> float:
        return self._angle

    def set_angle(self, angle: float) -> None:
        angle = min(max(float(angle), self.MINIMUM), self.MAXIMUM)
        if abs(angle - self._angle) < 0.05:
            return
        self._angle = angle
        self._update_description()
        self.update()
        self.changed.emit(angle)

    def _update_description(self) -> None:
        self.setAccessibleDescription(f"{self._angle:.0f} degrees")

    # --- Input -----------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._track(event.position())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._track(event.position())

    def keyPressEvent(self, event) -> None:  # noqa: N802
        step = 1.0 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 5.0
        key = event.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Down):
            self.set_angle(self._angle - step)
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Up):
            self.set_angle(self._angle + step)
        elif key == Qt.Key.Key_Home:
            self.set_angle(self.MINIMUM)
        elif key == Qt.Key.Key_End:
            self.set_angle(self.MAXIMUM)
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        self.set_angle(self._angle + (1.0 if event.angleDelta().y() > 0 else -1.0))

    def _track(self, point: QPointF) -> None:
        pivot = self._pivot()
        dx = point.x() - pivot.x()
        dy = pivot.y() - point.y()
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return
        self.set_angle(math.degrees(math.atan2(dy, dx)))

    # --- Painting --------------------------------------------------------

    #: Room kept below the pivot for the reading, and above the arc for the
    #: graticule that sits outside it.
    _FOOT = 34.0
    _CROWN = 24.0

    def _pivot(self) -> QPointF:
        return QPointF(self.width() * 0.5, self.height() - self._FOOT)

    def _lid_length(self) -> float:
        """Arc radius that keeps the graticule inside the widget.

        The graticule is drawn beyond the lid, so the arc has to leave room for
        it. Deriving the radius from the available height rather than picking a
        constant is what stops the ticks being clipped at the top.
        """
        available = self.height() - self._FOOT - self._CROWN
        return max(48.0, min(self.width() * 0.28, available))

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pivot = self._pivot()
        lid_length = self._lid_length()
        base_length = lid_length * 0.94

        # Degree graticule, struck in Prussian blue because it is measured rather
        # than chosen. Every 15 degrees, longer at each 45.
        for degrees in range(int(self.MINIMUM), int(self.MAXIMUM) + 1, 15):
            radians = math.radians(degrees)
            inner = lid_length + 8
            outer = inner + (11 if degrees % 45 == 0 else 6)
            painter.setPen(
                QPen(
                    QColor(Palette.PRUSSIAN)
                    if degrees % 45 == 0
                    else QColor(Palette.PRUSSIAN).darker(135),
                    1,
                )
            )
            painter.drawLine(
                QPointF(
                    pivot.x() + math.cos(radians) * inner,
                    pivot.y() - math.sin(radians) * inner,
                ),
                QPointF(
                    pivot.x() + math.cos(radians) * outer,
                    pivot.y() - math.sin(radians) * outer,
                ),
            )

        # The base, seen from the side.
        painter.setPen(
            QPen(QColor(Palette.CHALK_SOFT), 3, Qt.PenStyle.SolidLine,
                 Qt.PenCapStyle.RoundCap)
        )
        painter.drawLine(pivot, QPointF(pivot.x() + base_length, pivot.y()))
        painter.setPen(QPen(QColor(Palette.FRAME), 1))
        painter.drawLine(
            QPointF(pivot.x() - 14, pivot.y() + 5),
            QPointF(pivot.x() + base_length + 8, pivot.y() + 5),
        )

        # The lid, at the chosen angle.
        radians = math.radians(self._angle)
        tip = QPointF(
            pivot.x() + math.cos(radians) * lid_length,
            pivot.y() - math.sin(radians) * lid_length,
        )
        painter.setPen(
            QPen(QColor(Palette.OXIDE_BRIGHT), 4, Qt.PenStyle.SolidLine,
                 Qt.PenCapStyle.RoundCap)
        )
        painter.drawLine(pivot, tip)

        # The screen face, so it reads as a lid and not just a line.
        face = QPainterPath()
        normal = QPointF(math.sin(radians), math.cos(radians))
        inset = 9.0
        face.moveTo(pivot)
        face.lineTo(tip)
        face.lineTo(tip.x() - normal.x() * inset, tip.y() - normal.y() * inset)
        face.lineTo(pivot.x() - normal.x() * inset, pivot.y() - normal.y() * inset)
        face.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(193, 80, 46, 55))
        painter.drawPath(face)

        # The pivot itself.
        painter.setBrush(QColor(Palette.CHALK))
        painter.drawEllipse(pivot, 3.5, 3.5)

        # The reading.
        painter.setPen(QPen(QColor(Palette.CHALK)))
        painter.setFont(ui_font(15))
        painter.drawText(
            QRectF(0, self.height() - 26, self.width(), 22),
            Qt.AlignmentFlag.AlignCenter,
            f"{self._angle:.0f}\u00b0",
        )

        if self.hasFocus():
            painter.setPen(QPen(QColor(Palette.PRUSSIAN_BRIGHT), 1, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 3, 3)
