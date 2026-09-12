"""Record camera clips and replay them through the estimator.

Tuning an angle estimator by repeatedly closing a real lid does not work. No two
closes are the same, so a change that looks like an improvement may just be a
different close, and the slow ones are the interesting ones precisely because
they are hard to repeat.

Recording a handful of real closes once and replaying them after every change
turns that into a measurement.

    python -m winduo.tools.replay record --out clips/slow-close.npz
    python -m winduo.tools.replay play clips/slow-close.npz

Clips hold downscaled grayscale frames, so a ten-second close is a couple of
megabytes rather than a couple of hundred, and they carry no recognisable image
of the room or the person in front of it.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np

from winduo.angle.estimator import TravelEstimator
from winduo.angle.tracker import TRACK_WIDTH, ShiftTracker, prepare
from winduo.config import Store
from winduo.log import get_logger, setup_logging

log = get_logger("replay")

__all__ = ["record", "play"]


def record(out: Path, seconds: float, camera_index: int, width: int) -> Path:
    import cv2

    capture = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    if not capture.isOpened():
        raise SystemExit(f"could not open camera {camera_index}")
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    capture.set(cv2.CAP_PROP_FPS, 30)
    capture.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
    capture.set(cv2.CAP_PROP_EXPOSURE, -7)

    frames: list[np.ndarray] = []
    stamps: list[float] = []
    started = time.monotonic()
    print(f"Recording for {seconds:.0f} s. Close the lid now.")
    try:
        while time.monotonic() - started < seconds:
            ok, frame = capture.read()
            now = time.monotonic()
            if not ok or frame is None:
                continue
            frames.append(prepare(frame, width).astype(np.float16))
            stamps.append(now - started)
    finally:
        capture.release()

    if len(frames) < 4:
        raise SystemExit("the camera produced almost nothing; is it in use?")

    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out,
        frames=np.stack(frames),
        stamps=np.asarray(stamps, dtype=np.float64),
        width=width,
    )
    size = out.stat().st_size / 1e6
    print(f"Wrote {len(frames)} frames over {stamps[-1]:.1f} s to {out} ({size:.1f} MB)")
    return out


def play(clip: Path, store: Store, csv: bool) -> int:
    data = np.load(clip)
    frames = data["frames"]
    stamps = data["stamps"]
    width = int(data["width"]) if "width" in data else TRACK_WIDTH

    estimator = TravelEstimator(
        store.calibration,
        settle_seconds=store.settings.neutral_settle_seconds,
        settle_tolerance=store.settings.neutral_settle_tolerance,
        track_width=width,
    )
    tracker = ShiftTracker(width)
    # The estimator owns a tracker of its own; drive that one directly so the
    # replay walks exactly the path the live camera walks.
    estimator._tracker = tracker

    if csv:
        print("time_s,shift_px,travel_deg,velocity_deg_s,confidence,at_rest")

    peak = 0.0
    triggered_at: float | None = None
    trigger = store.settings.trigger_travel

    for index in range(len(frames)):
        frame = frames[index].astype(np.float32)
        reading = tracker.feed(frame)
        if reading is None:
            continue
        now = float(stamps[index])
        sample = estimator.feed_reading(reading, now)
        peak = max(peak, sample.travel)
        if triggered_at is None and sample.travel >= trigger:
            triggered_at = now
        if csv:
            print(
                f"{now:.3f},{tracker.total:.2f},{sample.travel:.3f},"
                f"{sample.velocity:.2f},{sample.confidence:.3f},"
                f"{int(sample.at_rest)}"
            )

    if not csv:
        print(f"Clip:            {clip.name}")
        print(f"Frames:          {len(frames)} over {stamps[-1]:.1f} s")
        print(f"Total shift:     {tracker.total:.1f} px at {width} wide")
        print(f"Peak travel:     {peak:.1f} deg")
        if triggered_at is None:
            print(f"Trigger:         never reached {trigger:.0f} deg")
        else:
            print(f"Trigger:         {trigger:.0f} deg reached at {triggered_at:.2f} s")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record", help="record a clip from the camera")
    rec.add_argument("--out", type=Path, required=True)
    rec.add_argument("--seconds", type=float, default=8.0)
    rec.add_argument("--camera", type=int, default=0)
    rec.add_argument("--width", type=int, default=TRACK_WIDTH)

    rep = sub.add_parser("play", help="replay a clip through the estimator")
    rep.add_argument("clip", type=Path)
    rep.add_argument("--csv", action="store_true", help="print every frame as CSV")

    options = parser.parse_args(argv)
    setup_logging(verbose=False)

    if options.command == "record":
        record(options.out, options.seconds, options.camera, options.width)
        return 0
    return play(options.clip, Store(), options.csv)


if __name__ == "__main__":
    raise SystemExit(main())
