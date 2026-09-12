"""The scroll-safety fix on SliderRow's slider.

A QSlider accepts the mouse wheel by default. Inside a QScrollArea, as every
slider in the settings window is, that means scrolling the page changes
whatever value the cursor happens to be over. This checks the fix at the level
where it actually has to hold: an ignored wheel event propagating to a real
parent widget.
"""

from __future__ import annotations

import sys

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication, QScrollArea, QWidget

from winduo.ui.widgets import SliderRow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv[:1])


def _wheel(delta_y: int) -> QWheelEvent:
    return QWheelEvent(
        QPointF(5, 5),
        QPointF(5, 5),
        QPoint(0, 0),
        QPoint(0, delta_y),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )


class TestSliderRowInsideAScrollArea:
    def _build(self, app):
        area = QScrollArea()
        content = QWidget()
        area.setWidget(content)
        row = SliderRow("Test", 0, 100, 25, parent=content)
        area.resize(200, 100)
        content.resize(200, 400)
        return area, row

    def test_wheeling_over_the_slider_does_not_change_its_value(self, app):
        area, row = self._build(app)
        before = row.value()
        row._slider.wheelEvent(_wheel(120))
        assert row.value() == before

    def test_the_wheel_event_is_left_unaccepted_so_it_reaches_the_scroll_area(self, app):
        area, row = self._build(app)
        event = _wheel(120)
        row._slider.wheelEvent(event)
        assert not event.isAccepted()

    def test_dragging_the_handle_still_changes_the_value(self, app):
        area, row = self._build(app)
        row._slider.setValue(150)
        assert row.value() != 25
