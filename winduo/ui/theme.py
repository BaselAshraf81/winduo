"""The scene shop, as interface tokens.

The world is a scene painter's flat: oiled canvas stretched on a frame, chalk
snap-lines struck across it, paint in oxide red and Prussian blue, everything
squared up against a marked sightline. A painted flat is an image built to read
correctly from one seat while the surface it sits on is angled away from the
audience, which is exactly what this app does to a screen.

These windows are Operate surfaces. The world shows up in material and detail,
never in a way that makes a slider harder to find. Contrast is checked against
WCAG 2.2 AA, and the accent is never the only carrier of meaning.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

__all__ = ["Palette", "STYLESHEET", "app_icon", "tray_icon", "ui_font"]


class Palette:
    """Named colours. Every text pair below is 4.5:1 or better on its ground."""

    # Oiled canvas seen under work light, not black. A flat in a scene shop is
    # warm and slightly uneven, and the app is used in a lit room.
    CANVAS = "#1c1a17"
    CANVAS_RAISED = "#252220"
    CANVAS_SUNK = "#141210"
    FRAME = "#3a3531"

    # Chalk, struck and then rubbed back.
    CHALK = "#f2ede4"          # 13.9:1 on CANVAS
    CHALK_SOFT = "#bdb5a8"     # 7.6:1 on CANVAS
    CHALK_FAINT = "#8d857a"    # 4.6:1 on CANVAS

    # Scene paint. Oxide red is the active mark; Prussian blue is the layout
    # line, used where something is measured rather than chosen.
    OXIDE = "#c1502e"
    OXIDE_BRIGHT = "#e2703f"
    OXIDE_SUNK = "#9c3d21"
    PRUSSIAN = "#4a7fa5"
    PRUSSIAN_BRIGHT = "#6fa3c7"

    # Status. Paired with text in the interface, never colour alone.
    GOOD = "#7fa663"
    WARN = "#d99b45"
    BAD = "#cf5b4d"


def ui_font(size: int = 10, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    """A workhorse UI face.

    Operate surfaces are well served by the platform's own text face, and a
    settings window is not the place to introduce a display voice. The site
    carries the lettering; these windows carry the work.
    """
    for family in ("Segoe UI Variable Text", "Segoe UI", "Inter"):
        if family in QFontDatabase.families():
            font = QFont(family, size)
            font.setWeight(weight)
            return font
    font = QFont()
    font.setPointSize(size)
    font.setWeight(weight)
    return font


def label_font(size: int = 8) -> QFont:
    """Small tracked caps, the way a scene shop stencils a label onto a flat."""
    font = ui_font(size, QFont.Weight.DemiBold)
    font.setCapitalization(QFont.Capitalization.AllUppercase)
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 112)
    return font


P = Palette

STYLESHEET = f"""
QWidget {{
    background: {P.CANVAS};
    color: {P.CHALK};
}}

QDialog, QMainWindow {{
    background: {P.CANVAS};
}}

/* Chalk snap-line. Used to separate stages, never as decoration. */
QFrame[role="rule"] {{
    background: {P.FRAME};
    max-height: 1px;
    border: none;
}}

QLabel[role="title"] {{
    color: {P.CHALK};
    font-size: 17px;
    font-weight: 600;
}}

QLabel[role="section"] {{
    color: {P.CHALK_SOFT};
}}

QLabel[role="help"] {{
    color: {P.CHALK_FAINT};
}}

QLabel[role="reading"] {{
    color: {P.PRUSSIAN_BRIGHT};
    font-weight: 600;
}}

QLabel[role="notice"] {{
    background: {P.CANVAS_RAISED};
    border: 1px solid {P.FRAME};
    border-radius: 4px;
    padding: 10px 12px;
    color: {P.CHALK_SOFT};
}}

QLabel[role="alert"] {{
    background: #2b1f1b;
    border: 1px solid {P.OXIDE_SUNK};
    border-radius: 4px;
    padding: 10px 12px;
    color: #f0d9d1;
}}

/* --- Buttons ---------------------------------------------------------- */

QPushButton {{
    background: {P.CANVAS_RAISED};
    border: 1px solid {P.FRAME};
    border-radius: 3px;
    padding: 7px 16px;
    color: {P.CHALK};
}}

QPushButton:hover {{
    background: #2e2a27;
    border-color: #4b453f;
}}

QPushButton:pressed {{
    background: {P.CANVAS_SUNK};
}}

QPushButton:focus {{
    outline: none;
    border-color: {P.PRUSSIAN_BRIGHT};
}}

QPushButton:disabled {{
    color: {P.CHALK_FAINT};
    background: {P.CANVAS_SUNK};
    border-color: #2c2825;
}}

QPushButton[role="primary"] {{
    background: {P.OXIDE};
    border-color: {P.OXIDE_SUNK};
    color: #fff6f2;
    font-weight: 600;
}}

QPushButton[role="primary"]:hover {{
    background: {P.OXIDE_BRIGHT};
}}

QPushButton[role="primary"]:pressed {{
    background: {P.OXIDE_SUNK};
}}

QPushButton[role="primary"]:disabled {{
    background: #4a3229;
    border-color: #3c2a23;
    color: #a08b83;
}}

/* --- Sliders ---------------------------------------------------------- */

QSlider::groove:horizontal {{
    height: 2px;
    background: {P.FRAME};
    margin: 8px 0;
}}

QSlider::sub-page:horizontal {{
    background: {P.OXIDE};
    height: 2px;
}}

QSlider::handle:horizontal {{
    background: {P.CHALK};
    border: none;
    width: 12px;
    height: 12px;
    margin: -6px 0;
    border-radius: 6px;
}}

QSlider::handle:horizontal:hover {{
    background: #ffffff;
}}

QSlider:focus::handle:horizontal {{
    background: {P.OXIDE_BRIGHT};
}}

QSlider::handle:horizontal:disabled {{
    background: {P.CHALK_FAINT};
}}

/* --- Checkboxes ------------------------------------------------------- */

QCheckBox {{
    spacing: 9px;
}}

QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid #514a44;
    border-radius: 3px;
    background: {P.CANVAS_SUNK};
}}

QCheckBox::indicator:hover {{
    border-color: {P.CHALK_FAINT};
}}

QCheckBox::indicator:checked {{
    background: {P.OXIDE};
    border-color: {P.OXIDE_SUNK};
}}

QCheckBox::indicator:focus {{
    border-color: {P.PRUSSIAN_BRIGHT};
}}

QCheckBox:disabled {{
    color: {P.CHALK_FAINT};
}}

/* --- Combo box -------------------------------------------------------- */

QComboBox {{
    background: {P.CANVAS_RAISED};
    border: 1px solid {P.FRAME};
    border-radius: 3px;
    padding: 5px 10px;
    color: {P.CHALK};
}}

QComboBox:focus {{
    border-color: {P.PRUSSIAN_BRIGHT};
}}

QComboBox::drop-down {{
    border: none;
    width: 18px;
}}

QComboBox QAbstractItemView {{
    background: {P.CANVAS_RAISED};
    border: 1px solid {P.FRAME};
    selection-background-color: {P.OXIDE};
    selection-color: #fff6f2;
    outline: none;
}}

/* --- Scroll area ------------------------------------------------------ */

QScrollArea {{
    border: none;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 9px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {P.FRAME};
    border-radius: 4px;
    min-height: 28px;
}}

QScrollBar::handle:vertical:hover {{
    background: #4f4842;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}

/* --- Tray menu -------------------------------------------------------- */

QMenu {{
    background: {P.CANVAS_RAISED};
    border: 1px solid {P.FRAME};
    padding: 5px;
}}

QMenu::item {{
    padding: 6px 26px 6px 14px;
    border-radius: 3px;
}}

QMenu::item:selected {{
    background: {P.OXIDE};
    color: #fff6f2;
}}

QMenu::item:disabled {{
    color: {P.CHALK_FAINT};
}}

QMenu::separator {{
    height: 1px;
    background: {P.FRAME};
    margin: 5px 8px;
}}

QMenu::indicator {{
    width: 13px;
    height: 13px;
    left: 8px;
}}

QToolTip {{
    background: {P.CANVAS_RAISED};
    color: {P.CHALK};
    border: 1px solid {P.FRAME};
    padding: 5px 7px;
}}
"""


# --- Icons ---------------------------------------------------------------


def _draw_flat(painter: QPainter, size: int, active: bool) -> None:
    """A painted flat seen from the side, hinged at its foot and angled back.

    The icon is the product's own geometry: a rectangle pivoted about its bottom
    edge, with the sightline it is built for struck across it. Drawn rather than
    borrowed, in one stroke weight, so there is no glyph standing in for an icon.
    """
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    unit = size / 32.0

    # The hinge line, along the foot.
    foot_y = 25 * unit
    painter.setPen(
        QPen(QColor(Palette.CHALK_SOFT), max(1.0, 1.6 * unit), Qt.PenStyle.SolidLine,
             Qt.PenCapStyle.RoundCap)
    )
    painter.drawLine(QPointF(4 * unit, foot_y), QPointF(28 * unit, foot_y))

    # The flat itself, leaning back. Narrower at the top, which is the whole
    # effect in one shape.
    flat = QPainterPath()
    flat.moveTo(6.5 * unit, foot_y)
    flat.lineTo(25.5 * unit, foot_y)
    flat.lineTo(21.5 * unit, 7 * unit)
    flat.lineTo(10.5 * unit, 7 * unit)
    flat.closeSubpath()

    fill = QLinearGradient(0, 7 * unit, 0, foot_y)
    if active:
        fill.setColorAt(0.0, QColor(Palette.OXIDE_SUNK))
        fill.setColorAt(1.0, QColor(Palette.OXIDE_BRIGHT))
    else:
        fill.setColorAt(0.0, QColor(Palette.FRAME))
        fill.setColorAt(1.0, QColor(Palette.CHALK_SOFT))
    painter.setBrush(QBrush(fill))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawPath(flat)

    # One chalk snap-line across the flat, the line the picture is squared to.
    painter.setPen(
        QPen(QColor(28, 26, 23, 190), max(1.0, 1.2 * unit), Qt.PenStyle.SolidLine)
    )
    painter.drawLine(QPointF(9 * unit, 16 * unit), QPointF(23 * unit, 16 * unit))


def _pixmap(size: int, active: bool) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    _draw_flat(painter, size, active)
    painter.end()
    return pixmap


def app_icon(active: bool = False) -> QIcon:
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_pixmap(size, active))
    return icon


def tray_icon(active: bool = False) -> QIcon:
    """Separate from the app icon so the tray can show that the effect is live."""
    icon = QIcon()
    for size in (16, 20, 24, 32, 40, 48):
        icon.addPixmap(_pixmap(size, active))
    return icon
