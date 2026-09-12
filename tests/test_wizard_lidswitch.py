"""The wizard's own handling of the OS lid switch signal.

CalibrationSession.lid_closed() is covered in test_calibration.py. What is
tested here is the wiring above it: that the wizard forwards Engine's
lid_state_changed signal into the session at the right moment, since the
camera has no way to notice a closed lid on its own. Most laptop cameras face
the user, not the keyboard well, so the image stays lit and steady right up to
the instant the lid meets the base and the display cuts out.
"""

from __future__ import annotations

import sys

import pytest

pytest.importorskip("PyQt6")

if sys.platform != "win32":
    pytest.skip("the wizard imports Windows-only overlay and lid switch modules", allow_module_level=True)

from PyQt6.QtWidgets import QApplication

from winduo.angle.calibration import Stage
from winduo.config import Store
from winduo.ui.wizard import CalibrationWizard


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv[:1])


class _StubStatus:
    name = "stub"


class _StubCamera:
    def status(self):
        return _StubStatus()

    def set_tap(self, _tap):
        pass

    def reset(self):
        pass


class _StubEngine:
    """Just enough of Engine for the wizard to construct against."""

    def __init__(self):
        from PyQt6.QtCore import QObject, pyqtSignal

        class _Signals(QObject):
            lid_state_changed = pyqtSignal(bool)
            changed = pyqtSignal()

        self._signals = _Signals()
        self.lid_state_changed = self._signals.lid_state_changed
        self.changed = self._signals.changed
        self.camera = _StubCamera()


@pytest.fixture
def wizard(app, tmp_path):
    store = Store(
        config_path=tmp_path / "config.json", calibration_path=tmp_path / "cal.json"
    )
    engine = _StubEngine()
    w = CalibrationWizard(store, engine)
    yield w, engine
    w.deleteLater()


class TestLidShutSignal:
    def test_a_shut_lid_finishes_the_closing_stage(self, wizard):
        w, engine = wizard
        w._session.begin()
        w._session.confirm_viewing(100.0)
        w._session.shift = 30.0
        w._session.confirm_halfway()
        w._session.shift = 60.0
        assert w._session.stage is Stage.CLOSING

        engine.lid_state_changed.emit(False)

        assert w._session.stage is Stage.DONE
        assert w._session.result is not None

    def test_lid_shut_is_ignored_outside_the_closing_stage(self, wizard):
        w, engine = wizard
        w._session.begin()
        engine.lid_state_changed.emit(False)
        assert w._session.stage is Stage.VIEWING

    def test_lid_opening_is_not_treated_as_shutting(self, wizard):
        w, engine = wizard
        w._session.begin()
        w._session.confirm_viewing(100.0)
        w._session.confirm_halfway()
        engine.lid_state_changed.emit(True)
        assert w._session.stage is Stage.CLOSING

    def test_the_outcome_panel_is_shown_once_the_lid_switch_finishes_the_sweep(
        self, wizard
    ):
        w, engine = wizard
        w._session.begin()
        w._session.confirm_viewing(100.0)
        w._session.shift = 30.0
        w._session.confirm_halfway()
        w._session.shift = 60.0

        engine.lid_state_changed.emit(False)

        assert w._stack.currentWidget() is w._result
        assert w._advance.text() == "Save"
