# WinDuo

Close your laptop lid and the screen leans away, blurring and dimming as it goes, the way an iPhone Duo does as it folds shut.

Apple has a hinge to read. [Mac Duo](https://github.com/sumimakito/Mac-Duo) has the MacBook's lid angle sensor. Your laptop has neither, so WinDuo watches the webcam instead.

**[winduo.baselashraf.com](https://winduo.baselashraf.com)** · Windows 10 (2004+) and 11 · Apache 2.0

## Install

```sh
pip install git+https://github.com/BaselAshraf81/winduo
python -m winduo
```

The calibration wizard opens the first time. It takes about twenty seconds: set the lid where you normally have it, drag a silhouette to match, bring it halfway down, then close it.

After that WinDuo sits in the notification area. Right-click it for settings, or to calibrate again.

Nothing to hand to test with? `python -m winduo --preview` plays the effect once on whatever is on screen.

## How it follows the lid

The effect is continuous, not a one-shot animation. It fades in once you have closed about 10°, grows as you keep closing, and reverses if you open back up. Both thresholds are adjustable.

The webcam is mounted in the lid, so closing the lid slides the whole camera image down the frame by about 15 pixels per degree. That slide is the measurement.

Adding those slides up would drift, so WinDuo never tries to know the real angle. Whenever the lid holds still, that position becomes zero, and the effect runs on movement away from it. This is also why it works with the laptop on a desk, on your lap, or held at any angle.

## Known limits

- **The camera light stays on while WinDuo runs.** It has to see the lid before it starts moving. Frames are compared with the previous frame and discarded; nothing is recorded or sent anywhere.
- **Another app can take the camera.** A video call will stop WinDuo reading the lid. It says so in the tray.
- **Windows turns the screen off when the lid shuts,** so you only see the effect during the closing movement.
- **Picking the laptop up can trigger it.** Rotating the whole machine looks like closing the lid to a camera. Using a laptop on a train will produce false positives.
- **A dark room costs accuracy.** Below a usable threshold the effect stays off rather than guessing.
- Windows only, primary display only.

## Contributing

`pip install -e ".[dev]"` then `pytest`. The tests need no camera, screen, or lid.

A Linux port is the biggest thing missing and the angle estimation carries over unchanged. [CONTRIBUTING.md](CONTRIBUTING.md) has the details, along with the tools for working on the estimator and the shader.

## Credit

[Mac Duo](https://github.com/sumimakito/Mac-Duo) by [Makito](https://github.com/sumimakito) is the reference implementation. Its geometry, shader, and state machine are ported here rather than reinvented; [NOTICE](NOTICE) lists which files. The webcam angle estimation is the new part, because the sensor Mac Duo reads is the part that is missing.
