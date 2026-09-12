"""Entry point.

``python -m winduo`` starts the app. ``--preview`` plays the effect once and
exits, which is the quickest way to see whether the renderer works on a machine
without involving a camera or a lid at all.
"""

from __future__ import annotations

import argparse
import signal
import sys

from winduo import __version__
from winduo.log import get_logger, setup_logging

log = get_logger("main")

__all__ = ["main"]


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="winduo",
        description="Lean the screen away as the laptop lid closes.",
    )
    parser.add_argument("--version", action="version", version=f"WinDuo {__version__}")
    parser.add_argument(
        "--preview",
        action="store_true",
        help="play the effect once and exit, without using the camera",
    )
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="open the calibration wizard at launch",
    )
    parser.add_argument(
        "--settings",
        action="store_true",
        help="open the settings window at launch",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log more")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    options = _parse(argv)
    setup_logging(options.verbose)

    if sys.platform != "win32":
        print(
            "WinDuo needs Windows. The capture and overlay both use Windows-only "
            "APIs. See CONTRIBUTING.md for what a Linux port would involve.",
            file=sys.stderr,
        )
        return 2

    # Imported here so --version and the platform check cost nothing.
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

    from winduo.app import Engine
    from winduo.config import Store
    from winduo.render.overlay import configure_surface
    from winduo.ui.theme import STYLESHEET, app_icon, ui_font
    from winduo.ui.tray import TrayController

    # Must happen before any window exists, or the context is already chosen.
    configure_surface()

    app = QApplication(sys.argv[:1])
    app.setApplicationName("WinDuo")
    app.setApplicationDisplayName("WinDuo")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("WinDuo")
    app.setWindowIcon(app_icon())
    app.setStyleSheet(STYLESHEET)
    app.setFont(ui_font(9))
    # The tray owns the lifetime. Closing the last window must not quit.
    app.setQuitOnLastWindowClosed(False)

    store = Store()
    engine = Engine(store)

    if options.preview:
        return _run_preview(app, engine)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(
            None,
            "WinDuo",
            "Windows is not offering a notification area, so there would be no "
            "way to reach WinDuo's controls.",
        )
        return 3

    tray = TrayController(store, engine)
    engine.start()
    tray.show()

    if options.calibrate:
        QTimer.singleShot(300, tray.open_wizard)
    elif options.settings:
        QTimer.singleShot(0, tray.open_settings)

    # Ctrl+C from a terminal, which Qt otherwise swallows.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    heartbeat = QTimer()
    heartbeat.start(250)
    heartbeat.timeout.connect(lambda: None)

    log.info("WinDuo %s ready", __version__)
    code = app.exec()
    engine.stop()
    return code


def _run_preview(app, engine) -> int:
    """Play the scripted sweep once, then quit. No camera, no lid."""
    from PyQt6.QtCore import QTimer

    engine.start()
    QTimer.singleShot(400, engine.run_preview)

    def finish() -> None:
        engine.stop()
        app.quit()

    QTimer.singleShot(5200, finish)
    log.info("running the preview sweep")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
