"""Find out which half of the pipeline is producing a black screen.

The overlay is excluded from screen capture, so no screenshot tool can photograph
it and "the screen went black" is ambiguous between two very different faults:

- the captured frame is already black, so there is nothing to draw, or
- the frame is fine and the renderer is putting it somewhere wrong.

This runs the real engine, triggers the real effect, and then writes out both
sides at the same moment: what the capture backend handed over, and what the
overlay actually rendered, read straight back off its framebuffer.

    python -m winduo.tools.diagnose --out build/diag
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from winduo.log import get_logger, setup_logging

log = get_logger("diagnose")


def _describe(name: str, image: np.ndarray | None) -> str:
    if image is None:
        return f"{name}: nothing at all"
    finite = image[..., :3]
    return (
        f"{name}: {image.shape[1]}x{image.shape[0]}, "
        f"mean {finite.mean():.1f}, min {finite.min()}, max {finite.max()}, "
        f"{'ALL BLACK' if finite.max() == 0 else 'has content'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("build/diag"))
    parser.add_argument("--at", type=float, default=1.1, help="seconds into the sweep")
    options = parser.parse_args(argv)

    setup_logging(verbose=True)
    if sys.platform != "win32":
        print("Windows only.", file=sys.stderr)
        return 2

    import cv2
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    from winduo.app import Engine
    from winduo.config import Store
    from winduo.render.overlay import configure_surface

    configure_surface()
    app = QApplication(sys.argv[:1])
    store = Store()
    engine = Engine(store)
    engine.start()

    options.out.mkdir(parents=True, exist_ok=True)
    report: list[str] = []

    def sample() -> None:
        # 1. What the capture backend has.
        captured = engine.capture.peek() if engine.capture else None
        if captured is not None:
            cv2.imwrite(str(options.out / "capture.png"), captured[..., :3])
        report.append(_describe("capture ", captured))

        # 2. What the overlay drew. grabFramebuffer reads the real framebuffer,
        #    so it sees exactly what the shader wrote, capture exclusion and all.
        view = getattr(engine.overlay, "_view", None)
        if view is not None:
            image = view.grabFramebuffer()
            image.save(str(options.out / "overlay.png"))
            width, height = image.width(), image.height()
            pointer = image.constBits()
            pointer.setsize(image.sizeInBytes())
            drawn = np.frombuffer(pointer, dtype=np.uint8).reshape(
                height, image.bytesPerLine() // 4, 4
            )[:, :width]
            report.append(_describe("overlay ", drawn))
            report.append(
                f"          framebuffer {width}x{height}, "
                f"view widget {view.width()}x{view.height()}, "
                f"devicePixelRatio {view.devicePixelRatioF():.3f}"
            )
            report.append(
                f"          configured screen {view._screen_size}, "
                f"picture {view._picture_size}, scale {view._picture_scale:.4f}, "
                f"texture {view._texture_size}, inset {view._inset}, "
                f"max level {view._max_level:.0f}, has_picture {view.has_picture}"
            )
        else:
            report.append("overlay : no view exists")

        report.append(
            f"          controller phase {engine.controller.phase.name}, "
            f"travel {engine.controller.travel:.1f}"
        )
        report.append(
            f"          overlay visible {engine.overlay.is_visible}, "
            f"excluded from capture {engine.overlay.excludes_itself_from_capture}"
        )

    def finish() -> None:
        engine.stop()
        app.quit()

    # Wait for the effect to actually be running rather than guessing at a wall
    # clock offset. Starting the capture can take several seconds, and the whole
    # preview sweep is under three, so a fixed delay samples the wrong moment.
    from winduo.effect.controller import Phase

    state = {"sampled": False, "waited": 0.0}
    poll = QTimer()

    def watch() -> None:
        state["waited"] += 0.05
        running = engine.controller.phase is Phase.RUNNING
        if running and engine.overlay.has_picture and not state["sampled"]:
            state["sampled"] = True
            sample()
            poll.stop()
            QTimer.singleShot(200, finish)
        elif state["waited"] > 25.0:
            report.append("gave up waiting for the effect to run")
            sample()
            poll.stop()
            QTimer.singleShot(200, finish)

    poll.timeout.connect(watch)
    QTimer.singleShot(300, engine.run_preview)
    poll.start(50)
    app.exec()

    print()
    print("\n".join(report))
    print(f"\nimages in {options.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
