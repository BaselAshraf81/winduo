# WinDuo

Close your laptop lid and the screen leans away, blurring and dimming as it goes, the way an iPhone Duo does as it folds shut.

Apple has a hinge to read. [Mac Duo](https://github.com/sumimakito/Mac-Duo) has the MacBook's lid angle sensor. Your laptop has neither, so WinDuo watches the webcam instead.

<p align="center">
  <a href="https://winduo.baselashraf.com">
    <img src="docs/demo.gif" alt="A laptop lid closing while the screen leans back, blurs and dims, rendered through WinDuo's own shader." width="270">
  </a>
</p>

**[winduo.baselashraf.com](https://winduo.baselashraf.com)** · Windows 10 (2004+) and 11, Windhawk, Linux on Hyprland · Free for noncommercial use, [PolyForm Noncommercial 1.0.0](LICENSE)

## Install

**Just want to use it:** download `WinDuo.exe` from the [latest release](https://github.com/BaselAshraf81/winduo/releases/latest). One file, nothing else to install, no Python. Windows will warn about an unrecognised app because the build is unsigned — choose *More info*, then *Run anyway*.

**From source:**

```sh
pip install git+https://github.com/BaselAshraf81/winduo
python -m winduo
```

The calibration wizard opens the first time. It takes about twenty seconds: set the lid where you normally have it, drag a silhouette to match, bring it halfway down, then close it.

After that WinDuo sits in the notification area. Right-click it for settings, or to calibrate again.

Nothing to hand to test with? `python -m winduo --preview` plays the effect once on whatever is on screen.

## How it follows the lid

The effect is continuous, not a one-shot animation. It fades in once you have closed about 10°, grows as you keep closing, reaches full strength at about 85°, and holds there for the rest of the way down. Open back up and it reverses. Both thresholds are adjustable.

The picture behaves like a sheet hinged at the bottom of the screen that stays where it is in the room while the glass turns under it, so for the first part of a close it tilts back exactly as far as the lid has moved. The top of the sheet tips forward toward you a little, which keeps whatever is near the top of the screen readable for longer, and the tilt levels off at about 55° past the trigger instead of stretching the picture into a smear as the lid nears flat. *Top lean* and *Tilt limit* in the settings adjust both.

The webcam is mounted in the lid, so closing the lid slides the whole camera image down the frame by about 15 pixels per degree. That slide is the measurement.

Adding those slides up would drift, so WinDuo never tries to know the real angle. Whenever the lid holds still, that position becomes zero, and the effect runs on movement away from it. This is also why it works with the laptop on a desk, on your lap, or held at any angle.

## Known limits

- **The camera light stays on while WinDuo runs.** It has to see the lid before it starts moving. Frames are compared with the previous frame and discarded; nothing is recorded or sent anywhere.
- **Another app can take the camera.** A video call will stop WinDuo reading the lid. It says so in the tray.
- **Windows turns the screen off when the lid shuts,** so you only see the effect during the closing movement.
- **Picking the laptop up can trigger it.** Rotating the whole machine looks like closing the lid to a camera. Using a laptop on a train will produce false positives.
- **A dark room costs accuracy.** Below a usable threshold the effect stays off rather than guessing.
- Primary display only.

## Windhawk

[windhawk/winduo.wh.cpp](windhawk/winduo.wh.cpp) is a native C++ build of the same effect packaged as a [Windhawk](https://windhawk.net) mod. It runs in its own process, injects into nothing, and needs no Python. It has no calibration wizard; its readme explains how to tune the one number the wizard would measure. [windhawk/README.md](windhawk/README.md) covers building it outside Windhawk and submitting it.

## Linux (Omarchy / Hyprland)

```sh
curl -fsSL https://raw.githubusercontent.com/BaselAshraf81/winduo/main/packaging/omarchy/install.sh | bash
```

This installs the Arch packages it needs, creates a virtualenv under `~/.local/share/winduo`, and starts WinDuo with Hyprland. `packaging/omarchy/uninstall.sh` undoes it. Differences from Windows:

- **The picture is held, not live.** Wayland has no way for the overlay to keep itself out of a screen capture, so WinDuo captures one frame as the lid starts to move (with `grim`) and animates that.
- **Hyprland only.** The overlay is floated, pinned and sized with `hyprctl dispatch`, which works under both Hyprland config formats. Other compositors are not supported.
- Exposure is left on auto, and the lid switch is read from `/proc/acpi/button/lid`.

The Linux port has been unit tested but not yet run on real Omarchy hardware. Reports are welcome.

## Contributing

`pip install -e ".[dev]"` then `pytest`. The tests need no camera, screen, or lid. [CONTRIBUTING.md](CONTRIBUTING.md) has the tools for working on the estimator and the shader.

## License

WinDuo is free for any noncommercial purpose — personal use, research, education, hobby projects, all of it — under the [PolyForm Noncommercial License 1.0.0](LICENSE). Commercial use is not permitted without a separate agreement. Any copy or derivative must keep the required attribution to Basel Ashraf and to Mac Duo intact; see [LICENSE](LICENSE) and [NOTICE](NOTICE).

## Credit

Built by **[Basel Ashraf](https://baselashraf.com)**.

[Mac Duo](https://github.com/sumimakito/Mac-Duo) by [Makito](https://github.com/sumimakito) is the reference implementation, originally released under Apache 2.0. Its geometry, shader, and state machine are ported here rather than reinvented; [NOTICE](NOTICE) lists which files and explains how a noncommercial license here stays compatible with that. The webcam angle estimation is the new part, because the sensor Mac Duo reads is the part that is missing.

## Support

WinDuo is free and always will be. If it is worth a coffee: [Ko-fi](https://ko-fi.com/baselashraf) · [PayPal](https://paypal.me/baselashrafusd) · [Liberapay](https://liberapay.com/BaselAshraf81/donate) · [Airtm](https://airtm.me/theprofitking)
