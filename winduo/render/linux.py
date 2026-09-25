"""The Linux counterpart to ``win32.py``: Hyprland placement for the overlay.

Wayland gives a client no say over where its window goes or what stacks above
it, and Hyprland tiles a new toplevel like any other. So once the overlay maps,
this asks the compositor directly: float it, pin it to every workspace, cover
the monitor exactly, and switch off the decorations and animations that would
otherwise frame or slide it. Then focus goes back to wherever it was.

Only dispatchers are used, never ``hyprctl keyword``. Dispatchers work under
both config parsers, and Omarchy 4's Lua configuration rejects ``keyword``.

Everything here is best effort. A property a given Hyprland version does not
know is skipped, and on any other compositor the whole thing is a no-op.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

from winduo.log import get_logger

log = get_logger("linux")

__all__ = ["is_hyprland", "place_overlay", "overlay_commands"]

#: Window properties that would otherwise decorate, dim or animate the overlay.
#: Two spellings each: Hyprland renamed them from ``noanim`` style to
#: ``no_anim`` style, and an unknown name is simply rejected.
_PROPERTIES = (
    ("noanim", "no_anim"),
    ("noblur", "no_blur"),
    ("noshadow", "no_shadow"),
    ("nodim", "no_dim"),
    ("noborder", "no_border"),
    ("nofocus", "no_focus"),
    ("rounding", "rounding"),
)


def is_hyprland() -> bool:
    return bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")) and bool(shutil.which("hyprctl"))


def _hyprctl(*args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["hyprctl", *args], capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None


def _json(*args: str):
    result = _hyprctl(*args, "-j")
    if result is None or result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except ValueError:
        return None


def overlay_commands(address: str, rect: tuple[int, int, int, int]) -> list[str]:
    """The dispatches that turn a mapped window into the overlay. Pure, for tests."""
    x, y, width, height = rect
    target = f"address:{address}"
    commands = [
        f"dispatch setfloating {target}",
        f"dispatch resizewindowpixel exact {width} {height},{target}",
        f"dispatch movewindowpixel exact {x} {y},{target}",
        f"dispatch pin {target}",
    ]
    for old, new in _PROPERTIES:
        value = "0" if old == "rounding" else "1"
        commands.append(f"dispatch setprop {target} {old} {value}")
        if new != old:
            commands.append(f"dispatch setprop {target} {new} {value}")
    return commands


def place_overlay(title: str, rect: tuple[int, int, int, int]) -> bool:
    """Float, pin and size this process's window called ``title``."""
    if not is_hyprland():
        return False
    clients = _json("clients") or []
    ours = [c for c in clients if c.get("pid") == os.getpid() and c.get("title") == title]
    if not ours:
        log.info("overlay window not mapped yet")
        return False
    address = ours[0].get("address", "")
    previous = (_json("activewindow") or {}).get("address")

    for command in overlay_commands(address, rect):
        # hyprctl joins everything after the dispatcher with spaces itself.
        result = _hyprctl(*command.split())
        if result is not None and result.returncode == 0 and "ok" not in result.stdout.lower():
            log.debug("hyprctl %s: %s", command, result.stdout.strip())

    if previous and previous != address:
        _hyprctl("dispatch", "focuswindow", f"address:{previous}")
    log.info("overlay placed at %s via Hyprland", rect)
    return True
