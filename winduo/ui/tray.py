"""The tray icon, which owns the application.

There is no main window. The effect happens on the screen you are already
looking at, so a window would only ever be in the way.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from winduo.config import Store
from winduo.log import get_logger
from winduo.ui.settings import SettingsWindow
from winduo.ui.theme import tray_icon
from winduo.ui.wizard import CalibrationWizard

log = get_logger("tray")

__all__ = ["TrayController"]


class TrayController(QObject):
    def __init__(self, store: Store, engine) -> None:
        super().__init__()
        self.store = store
        self.engine = engine

        self._settings: SettingsWindow | None = None
        self._wizard: CalibrationWizard | None = None
        self._was_active = False
        #: True between the first-run wizard opening and it closing, so the
        #: settings window is shown once on a fresh install and not again every
        #: time somebody recalibrates.
        self._first_run = False

        self.icon = QSystemTrayIcon(tray_icon(False))
        self.icon.setToolTip("WinDuo")
        self.icon.activated.connect(self._on_activated)
        self.icon.setContextMenu(self._build_menu())

        engine.changed.connect(self._refresh)
        self._tooltip = QTimer(self)
        self._tooltip.setInterval(400)
        self._tooltip.timeout.connect(self._refresh)

    def show(self) -> None:
        self.icon.show()
        self._tooltip.start()
        self._refresh()

        # First run: open the wizard rather than leaving a tray icon to be
        # discovered. Nobody installs this to go looking for a menu, and the
        # wizard's first panel is also where the camera indicator gets
        # explained, so it is the right place to land.
        if not self.store.calibration.captured_at:
            self._first_run = True
            QTimer.singleShot(600, self.open_wizard)
            return

        if not self.store.settings.has_seen_camera_notice:
            self._announce_camera()

    # --- Menu ------------------------------------------------------------

    def _build_menu(self) -> QMenu:
        menu = QMenu()

        self._effect_action = QAction("Run the effect", menu)
        self._effect_action.setCheckable(True)
        self._effect_action.setChecked(self.store.settings.enabled)
        self._effect_action.toggled.connect(
            lambda value: self.store.update(enabled=value)
        )
        menu.addAction(self._effect_action)

        preview = QAction("Preview once", menu)
        preview.triggered.connect(self.engine.run_preview)
        menu.addAction(preview)

        menu.addSeparator()

        calibrate = QAction("Calibrate\u2026", menu)
        calibrate.triggered.connect(self.open_wizard)
        menu.addAction(calibrate)

        settings = QAction("Settings\u2026", menu)
        settings.triggered.connect(self.open_settings)
        menu.addAction(settings)

        menu.addSeparator()

        self._status_action = QAction("", menu)
        self._status_action.setEnabled(False)
        menu.addAction(self._status_action)

        menu.addSeparator()

        quit_action = QAction("Quit WinDuo", menu)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self._menu = menu
        return menu

    # --- Windows ---------------------------------------------------------

    def open_settings(self) -> None:
        if self._settings is None:
            self._settings = SettingsWindow(self.store, self.engine, self.open_wizard)
        self._settings.show()
        self._settings.raise_()
        self._settings.activateWindow()

    def open_wizard(self) -> None:
        if self._wizard is None:
            self._wizard = CalibrationWizard(self.store, self.engine)
            self._wizard.finished.connect(self._on_wizard_finished)
        self._wizard.start()

    def _on_wizard_finished(self, saved: bool) -> None:
        self.store.update(has_seen_camera_notice=True)
        if saved:
            self.icon.showMessage(
                "WinDuo is ready",
                "Close the lid and the screen will lean away. WinDuo lives in "
                "the notification area; right-click it for settings.",
                tray_icon(True),
                6000,
            )
        else:
            self.icon.showMessage(
                "WinDuo is running uncalibrated",
                "The effect will still work, using an estimated scale. Calibrate "
                "from the notification area whenever you want it to match your "
                "own lid.",
                tray_icon(False),
                6000,
            )
        if self._settings is not None:
            self._settings._load_from_store()

        # On a fresh install, show the settings window once the wizard is done.
        # A tray icon and a balloon are both easy to miss, so without this the
        # app looks like it has no controls at all: the effect just happens, and
        # every slider in it stays undiscovered. Delayed slightly so it opens
        # after the wizard has actually closed rather than behind it.
        if self._first_run:
            self._first_run = False
            QTimer.singleShot(700, self.open_settings)

    def _announce_camera(self) -> None:
        self.store.update(has_seen_camera_notice=True)
        self.icon.showMessage(
            "WinDuo is watching the lid",
            "The camera indicator stays lit while WinDuo runs. Frames are compared "
            "and discarded; nothing is recorded or sent anywhere.",
            tray_icon(False),
            8000,
        )

    # --- Status ----------------------------------------------------------

    def _refresh(self) -> None:
        settings = self.store.settings
        self._effect_action.setChecked(settings.enabled)

        active = self.engine.is_effect_running
        if active != self._was_active:
            self._was_active = active
            self.icon.setIcon(tray_icon(active))

        problem = self.engine.problem
        if not settings.enabled:
            summary = "Effect off"
        elif problem:
            summary = problem
        elif active:
            summary = "Running"
        else:
            sample = self.engine.camera.latest(max_age=1.0)
            if sample is None:
                summary = "Waiting for the camera"
            elif sample.at_rest:
                summary = "Resting, ready"
            else:
                summary = f"{max(sample.travel, 0.0):.0f}\u00b0 from resting"

        self._status_action.setText(summary)
        if settings.show_reading:
            self.icon.setToolTip(f"WinDuo \u2014 {summary}")
        else:
            self.icon.setToolTip("WinDuo")

    def _on_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.open_settings()

    def _quit(self) -> None:
        self._tooltip.stop()
        self.engine.stop()
        self.icon.hide()
        QApplication.quit()
