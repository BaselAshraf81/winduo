"""The Linux pieces that can be checked without Linux: parsing and planning."""

from __future__ import annotations

import numpy as np

from winduo.angle.lidswitch import read_acpi_lid_state
from winduo.render import capture, linux


class TestAcpiLidState:
    def test_open(self, tmp_path):
        path = tmp_path / "state"
        path.write_text("state:      open\n")
        assert read_acpi_lid_state(path) is True

    def test_closed(self, tmp_path):
        path = tmp_path / "state"
        path.write_text("state:      closed\n")
        assert read_acpi_lid_state(path) is False

    def test_unreadable_or_unknown_is_none(self, tmp_path):
        assert read_acpi_lid_state(tmp_path / "missing") is None
        path = tmp_path / "state"
        path.write_text("state: ajar")
        assert read_acpi_lid_state(path) is None


class TestPpm:
    def test_decodes_a_binary_ppm_to_bgra(self):
        header = b"P6\n2 1\n255\n"
        pixels = bytes([255, 0, 0, 0, 0, 255])  # red, then blue, as RGB
        frame = capture.decode_ppm(header + pixels)
        assert frame is not None
        assert frame.shape == (1, 2, 4)
        assert frame[0, 0].tolist() == [0, 0, 255, 255]  # BGRA red
        assert frame[0, 1].tolist() == [255, 0, 0, 255]  # BGRA blue
        assert frame.flags["C_CONTIGUOUS"]

    def test_garbage_is_none(self):
        assert capture.decode_ppm(b"not an image") is None


class TestHyprlandPlacement:
    def test_covers_the_monitor_exactly_and_pins(self):
        commands = linux.overlay_commands("0xabc", (0, 0, 1920, 1080))
        assert "dispatch setfloating address:0xabc" in commands
        assert "dispatch resizewindowpixel exact 1920 1080,address:0xabc" in commands
        assert "dispatch movewindowpixel exact 0 0,address:0xabc" in commands
        assert "dispatch pin address:0xabc" in commands

    def test_never_uses_keyword_which_omarchy_lua_rejects(self):
        commands = linux.overlay_commands("0x1", (0, 0, 10, 10))
        assert all(command.startswith("dispatch ") for command in commands)

    def test_turns_off_decoration_under_both_property_spellings(self):
        commands = linux.overlay_commands("0x1", (0, 0, 10, 10))
        for name in ("noanim", "no_anim", "noborder", "no_border", "noshadow", "no_shadow"):
            assert f"dispatch setprop address:0x1 {name} 1" in commands
        assert "dispatch setprop address:0x1 rounding 0" in commands

    def test_is_a_no_op_off_hyprland(self, monkeypatch):
        monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
        assert linux.place_overlay("anything", (0, 0, 1, 1)) is False


class TestGrimBackend:
    def test_throttles_well_below_the_capture_rate(self):
        assert capture._GrimBackend.min_interval >= 0.25

    def test_reports_a_missing_grim_clearly(self, monkeypatch):
        import shutil

        import pytest

        monkeypatch.setattr(shutil, "which", lambda _name: None)
        with pytest.raises(capture.CaptureError, match="grim"):
            capture._GrimBackend(0).start(60)


def test_numpy_is_the_one_in_use():
    # Guards the decode path against an accidental second numpy import.
    assert capture.np is np
