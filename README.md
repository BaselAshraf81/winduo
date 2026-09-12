# WinDuo

Close your laptop lid and the screen leans away from you, blurring and dimming as it goes, like the picture is a sheet of paper hinged at the bottom of the display that stays put in the room while the glass swings away from it.

[Mac Duo](https://github.com/sumimakito/Mac-Duo) does this by reading a hinge angle sensor. Almost no laptop outside recent MacBooks has one. WinDuo works out the same number from the webcam.

**Windows 10 (2004 or later) and Windows 11.** Apache 2.0.

---

## How it knows where the lid is

The camera is bolted into the lid. When the lid rotates, the camera rotates with it, about the same axis, by the same amount. No panning, no rolling, just pitch. So closing the lid slides the whole camera image straight down the frame, and the top of the view disappears off the edge.

That slide is the measurement. Phase correlation on a pair of downscaled grayscale frames returns it in about 200 microseconds, and it is a big signal: a typical webcam moves roughly 15 pixels per degree.

The awkward part is that adding up per-frame shifts drifts, so the total is never a trustworthy angle. WinDuo sidesteps that instead of fighting it: **whenever the lid holds still, wherever it is, that position becomes zero.** The effect runs on travel away from that zero, so error only ever accumulates for the length of one lid movement, a second or two. Nothing needs to know the real hinge angle, which is also why it works with the laptop on a desk, on your lap, or held at any starting position.

Three details make it hold up in a real room:

- **Exposure is forced short while WinDuo is running.** A lid closing at 180°/s covers 6° inside a single frame at 30 fps, and at ordinary indoor exposure that smears the image by 80-odd pixels, wiping out the detail the correlator needs at the exact moment it is needed. Short shutter, high gain.
- **Rolling the whole laptop is rejected.** Picking the machine up looks the same as closing the lid to anything that only measures the frame as a whole. A hinge is one axis, so both halves of the image have to move together; when they disagree, the reading is distrusted.
- **Losing the picture is reported, not guessed at.** A dark room, a covered camera, or another app holding the camera all drive confidence to zero, and the effect stays off. A wrong effect is worse than none.

Windows' own lid switch (`GUID_LIDSWITCH_STATE_CHANGE`) is the one piece of hardware truth available. It cannot give an angle, but it says exactly when the lid is shut, which ends the calibration sweep at a known zero and stops the effect before the display goes off.

## Calibration

The camera measures pixels. Turning pixels into degrees needs one known angle, and no amount of image processing can supply it, so WinDuo asks. The wizard runs three positions and takes about twenty seconds:

1. **Your normal viewing position.** Drag a silhouette until it matches your actual lid. Eyeballing it against a door frame is close enough.
2. **Roughly halfway down.** This one anchor fits a second-order term.
3. **Closed.** The lid switch or the camera going dark ends the sweep.

The curve is not quite a straight line for two reasons. Image shift per degree grows toward the edges of the frame, because the projection is a tangent. And the camera swings on an arc about 20 cm from the hinge, so a degree of closing also shifts it about 3.5 mm sideways; against a wall one metre away that parallax adds around 20% to the apparent movement, and at three metres about 6%. Since the error depends on how far away the room is, the wizard asks you to sit where you normally sit rather than to measure anything.

You can skip calibration. WinDuo falls back to the scale of a typical 75° field of view, which is close enough to work and wrong enough to be worth the twenty seconds.

## Install

Prebuilt releases are on the [releases page](https://github.com/winduo/winduo/releases). From source:

```sh
git clone https://github.com/winduo/winduo
cd winduo
pip install -e .
python -m winduo
```

WinDuo lives in the notification area; there is no main window. Right-click the tray icon for settings and calibration.

To see whether the renderer works on your machine without involving a camera or a lid:

```sh
python -m winduo --preview
```

## What it does to your screen

The captured screen sits in one texture on a black margin, with a mip pyramid over it. One full-screen fragment shader pass per frame maps each screen pixel back through the inverse perspective and takes a single sample at whatever mip level matches the blur wanted at that height. The blur costs the same at a 10-pixel radius as at 200, which is how a 135-pixel Gaussian runs on integrated graphics.

Two Windows-specific things carry the whole approach:

- `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` keeps the overlay out of every screen capture API. Without it the overlay is captured, drawn into itself, and recurses. This is the Windows counterpart to ScreenCaptureKit's application exclusion, and it needs Windows 10 version 2004. There is no workaround on older builds.
- The overlay window is created once at startup and never hidden, only faded. A full-screen topmost window appearing invalidates the display's duplication, and recovering from that blocks for the better part of a second. Doing that when the lid starts moving stalls the frame loop through the movement being tracked.

Screen capture uses DXGI Desktop Duplication, which hands over frames the compositor already has in video memory. GDI copying is the fallback for the machines that refuse duplication, mostly multi-GPU laptops and some virtual displays.

Capture is downscaled to 1600 pixels wide by default. A 4K frame is 33 MB, and moving 60 of those per second through system memory to reach the GPU costs 2 GB/s for detail the blur throws away immediately. Raise it in settings if you would rather spend the bandwidth.

## Known limits

- **Windows only.** Capture and the overlay both use Windows-only APIs. See [CONTRIBUTING.md](CONTRIBUTING.md) for what a Linux port needs; the estimator ports unchanged.
- **The camera indicator stays lit while WinDuo runs.** It has to: the baseline has to exist before the lid starts moving. Frames are compared with the previous frame and discarded. Nothing is recorded and nothing leaves the machine.
- **Another app can take the camera.** Zoom, Teams, and anything else claiming it exclusively will stop WinDuo reading the lid. It reports that rather than failing quietly.
- **Primary display only.**
- **Windows turns the screen off on lid close,** so the effect only ever plays during the closing travel. That is the interesting part of the motion, and it means no power settings need changing.
- **Rotating the whole laptop can trigger it.** The roll and pan checks catch the common cases, not all of them. Using a laptop in a moving car will produce false positives.
- **Low light costs accuracy.** Short exposure in a dim room is a noisy image; below a usable threshold the estimator reports low confidence and the effect stays off.

## Development

```sh
pip install -e ".[dev]"
pytest                                    # 116 tests, no camera or screen needed
ruff check winduo tests
```

The estimator and the state machine are covered by tests that synthesise readings, so neither needs hardware. The shader cannot be unit tested for whether it looks right, so there is a tool that renders it offscreen to files, which also works around the overlay being invisible to screenshot tools:

```sh
python -m winduo.tools.render_still --out build/stills
python -m winduo.tools.render_still --out build/warp --viewing-distance 1.5
```

Tuning the estimator against a real lid does not work, because no two closes are the same and the slow ones are the interesting ones. Record clips once and replay them after every change:

```sh
python -m winduo.tools.replay record --out clips/slow-close.npz --seconds 10
python -m winduo.tools.replay play clips/slow-close.npz
python -m winduo.tools.replay play clips/slow-close.npz --csv > trace.csv
```

Clips hold downscaled grayscale frames, a couple of megabytes for ten seconds, with no recognisable image of the room or of anyone in it.

### Layout

```
winduo/angle/      camera to degrees of travel. No Windows dependency except lidswitch.
  tracker.py       one frame pair to one vertical shift, in pixels
  estimator.py     accumulated shift to travel from neutral
  camera.py        the camera thread
  calibration.py   the guided sweep and its fit
  lidswitch.py     Windows' own open/shut signal
winduo/effect/     geometry, easing, and when the effect runs. Pure, all tested.
winduo/render/     capture, the GLSL shader, the overlay window, the Win32 calls
winduo/ui/         tray icon, settings, calibration wizard
winduo/tools/      offscreen renders and clip replay
```

`winduo/angle/` is written to be liftable on its own. If you want camera-based lid angle for something else, that is the part to take.

## Credit

Mac Duo by [Makito](https://github.com/sumimakito) is the reference implementation. Its geometry, its shader structure, and its state machine are ported here rather than reinvented, and [NOTICE](NOTICE) lists which files came from which. The angle estimation is the part that is new, because the sensor Mac Duo reads is the part that is missing.
