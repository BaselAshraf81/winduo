"""First run has to show its own controls.

The app has no main window, so on a fresh install the only evidence it is
configurable is a tray icon and a balloon, and both are easy to miss entirely.
These pin the behaviour that fixes that: the wizard opens first, and the
settings window follows it once, on a fresh install only.
"""

from __future__ import annotations

import sys

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from winduo.config import Calibration, Store  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv[:1])


class _FakeSignal:
    def connect(self, *_args, **_kwargs):
        return None


class _FakeEngine:
    """Only what TrayController touches, so no camera or GL is involved."""

    changed = _FakeSignal()
    problem = ""
    is_effect_running = False

    class camera:
        @staticmethod
        def latest(max_age: float = 1.0):
            return None

    @staticmethod
    def run_preview():
        return None


def _store(tmp_path, calibrated: bool) -> Store:
    store = Store(
        config_path=tmp_path / "config.json",
        calibration_path=tmp_path / "calibration.json",
    )
    if calibrated:
        store.calibration = Calibration(
            degrees_per_pixel=0.25,
            track_width=320,
            captured_at="2026-09-13T00:00:00+00:00",
        )
    return store


def _tray(store):
    from winduo.ui.tray import TrayController

    return TrayController(store, _FakeEngine())


class TestFreshInstall:
    def test_an_uncalibrated_install_is_treated_as_a_first_run(self, app, tmp_path):
        store = _store(tmp_path, calibrated=False)
        assert not store.calibration.captured_at
        tray = _tray(store)
        assert tray._first_run is False  # not until show() decides
        tray.show()
        try:
            assert tray._first_run is True
        finally:
            tray.icon.hide()

    def test_the_settings_window_is_queued_after_the_wizard(self, app, tmp_path):
        # The window itself is opened on a timer, so what is asserted here is
        # that finishing the wizard consumes the first-run flag. Without that,
        # the settings window would reopen on every later recalibration.
        store = _store(tmp_path, calibrated=False)
        tray = _tray(store)
        tray.show()
        try:
            assert tray._first_run is True
            tray._on_wizard_finished(saved=True)
            assert tray._first_run is False
        finally:
            tray.icon.hide()

    def test_a_cancelled_wizard_still_clears_the_flag(self, app, tmp_path):
        # Skipping calibration is allowed, and someone who skips it needs to see
        # the controls more than someone who did not.
        store = _store(tmp_path, calibrated=False)
        tray = _tray(store)
        tray.show()
        try:
            tray._on_wizard_finished(saved=False)
            assert tray._first_run is False
        finally:
            tray.icon.hide()


class TestAlreadySetUp:
    def test_a_calibrated_install_is_not_a_first_run(self, app, tmp_path):
        store = _store(tmp_path, calibrated=True)
        tray = _tray(store)
        tray.show()
        try:
            assert tray._first_run is False
        finally:
            tray.icon.hide()

    def test_recalibrating_later_does_not_reopen_settings(self, app, tmp_path):
        store = _store(tmp_path, calibrated=True)
        tray = _tray(store)
        tray.show()
        try:
            tray._on_wizard_finished(saved=True)
            assert tray._first_run is False
        finally:
            tray.icon.hide()
