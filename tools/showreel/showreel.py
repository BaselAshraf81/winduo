"""A 15-second motion-graphics reel for WinDuo, rendered frame by frame.

Every frame of the laptop screen goes through WinDuo's own fragment shader, so
the lean, the blur ramp and the dimming are the real effect, not a mock-up.
Everything around it is drawn with QPainter.

    python tools/showreel/showreel.py --out build/reel            # full reel
    python tools/showreel/showreel.py --out build/reel --gif      # Windhawk readme GIF
    python tools/showreel/showreel.py --out build/reel --frame 400  # one still

Needs ffmpeg on PATH for the video files.
"""

from __future__ import annotations

import argparse
import math
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

W, H = 1080, 1440
FPS = 60
DURATION = 15.0
SUBFRAMES = 8  # motion blur samples per frame

# Brand, from DESIGN.md.
BLUE_DEEP = "#0d2135"
BLUE = "#123049"
BLUE_LIFT = "#1a3d59"
BLUE_LINE = "#2d5875"
CHALK = "#f4f0e6"
CHALK_SOFT = "#c6cdd2"
CHALK_FAINT = "#93a3af"
OXIDE = "#d2542c"
OXIDE_LIFT = "#ea6c3f"
LINEN = "#d9cdb4"

SCREEN_W, SCREEN_H = 1280, 800


# --- Easing ------------------------------------------------------------------


def clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def span(t: float, a: float, b: float) -> float:
    return clamp01((t - a) / (b - a))


def ease_out(x: float) -> float:
    """cubic-bezier(0.16, 1, 0.3, 1), the site's one easing, approximated."""
    x = clamp01(x)
    return 1 - (1 - x) ** 4


def ease_in_out(x: float) -> float:
    x = clamp01(x)
    return 4 * x**3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def ease_back(x: float, s: float = 1.6) -> float:
    x = clamp01(x) - 1
    return x * x * ((s + 1) * x + s) + 1


def mix(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


# --- The lid, and the effect's own mapping from travel to shader inputs -------

TRIGGER = 10.0
SPAN = 75.0


def lid_travel(t: float) -> float:
    """Degrees closed from a 100-degree rest during the hero shot."""
    close_a, close_b, hold_b, open_b = 5.0, 7.7, 8.5, 10.1
    if t < close_a:
        return 0.0
    if t < close_b:
        return 78.0 * ease_in_out(span(t, close_a, close_b))
    if t < hold_b:
        return 78.0
    return 78.0 * (1 - ease_in_out(span(t, hold_b, open_b)))


# --- Qt / GL -----------------------------------------------------------------

_APP = None
FONT = {}


def setup_qt():
    global _APP
    from PyQt6.QtGui import QFontDatabase
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication(sys.argv[:1])
    for path in sorted((HERE / "fonts").glob("*.ttf")):
        index = QFontDatabase.addApplicationFont(str(path))
        families = QFontDatabase.applicationFontFamilies(index)
        FONT[path.stem] = families[0] if families else "Arial"


def font(key: str, px: float, weight=None, spacing: float = 0.0):
    from PyQt6.QtGui import QFont

    f = QFont(FONT.get(key, "Arial"))
    f.setPixelSize(max(1, int(px)))
    if weight is not None:
        f.setWeight(weight)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


class EffectRenderer:
    """WinDuo's shader in an offscreen framebuffer."""

    PADDING = 120

    def __init__(self, width: int, height: int) -> None:
        from OpenGL import GL
        from PyQt6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat

        from winduo.render.overlay import _build_program, _uniform_locations

        fmt = QSurfaceFormat()
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        fmt.setVersion(3, 3)
        self.surface = QOffscreenSurface()
        self.surface.setFormat(fmt)
        self.surface.create()
        self.context = QOpenGLContext()
        self.context.setFormat(fmt)
        if not self.context.create() or not self.context.makeCurrent(self.surface):
            raise RuntimeError("no OpenGL context")
        self.GL = GL
        self.w, self.h = width, height
        self.program = _build_program()
        self.u = _uniform_locations(self.program)
        self.vao = GL.glGenVertexArrays(1)
        tw, th = width + 2 * self.PADDING, height + 2 * self.PADDING
        self.padded = (float(tw), float(th))
        self.max_level = float(int(math.floor(math.log2(max(tw, th)))))
        self.texture = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        GL.glTexImage2D(
            GL.GL_TEXTURE_2D, 0, GL.GL_SRGB8_ALPHA8, tw, th, 0, GL.GL_BGRA,
            GL.GL_UNSIGNED_BYTE, np.zeros((th, tw, 4), np.uint8),
        )
        self.colour = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.colour)
        GL.glTexImage2D(
            GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, width, height, 0, GL.GL_RGBA,
            GL.GL_UNSIGNED_BYTE, None,
        )
        self.fbo = GL.glGenFramebuffers(1)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.fbo)
        GL.glFramebufferTexture2D(
            GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0, GL.GL_TEXTURE_2D, self.colour, 0
        )

    def upload(self, bgra: np.ndarray) -> None:
        GL = self.GL
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
        GL.glTexSubImage2D(
            GL.GL_TEXTURE_2D, 0, self.PADDING, self.PADDING, self.w, self.h,
            GL.GL_BGRA, GL.GL_UNSIGNED_BYTE, np.ascontiguousarray(bgra),
        )
        GL.glGenerateMipmap(GL.GL_TEXTURE_2D)

    def render(self, travel: float, velocity: float = 0.0) -> np.ndarray:
        """RGBA, top row first, for ``travel`` degrees closed from neutral."""
        from winduo.config import Settings
        from winduo.effect.controller import tilt_knee
        from winduo.effect.geometry import DepthGeometry
        from winduo.effect.gradient import BlurGradient

        GL, u = self.GL, self.u
        s = Settings()
        g = BlurGradient()
        past = max(travel - s.trigger_travel, 0.0)
        progress = min(past / s.full_effect_travel, 1.0)
        held = travel if travel <= s.trigger_travel else s.trigger_travel + tilt_knee(
            min(past, s.full_effect_travel), s.tilt_limit
        )
        neutral = 100.0
        profile = DepthGeometry().profile(
            neutral - s.trigger_travel, neutral - held, s.viewing_distance, s.recession,
            s.top_lean, (float(self.w), float(self.h)),
        )
        table = np.asarray(profile.flat(), np.float32)
        blur = min(g.blur_strength(progress) + g.motion_boost(velocity) * progress, 1.0)

        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.fbo)
        GL.glViewport(0, 0, self.w, self.h)
        GL.glClearColor(0, 0, 0, 1)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        GL.glUseProgram(self.program)
        GL.glBindVertexArray(self.vao)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
        GL.glUniform1i(u["uPicture"], 0)
        GL.glUniform2fv(u["uProfile"], len(table) // 2, table)
        GL.glUniform1f(u["uProfileEnd"], profile.end)
        GL.glUniform1f(u["uProfileSlope"], profile.slope)
        GL.glUniform2f(u["uScreenSize"], float(self.w), float(self.h))
        GL.glUniform2f(u["uPaddedOrigin"], -self.PADDING, -self.PADDING)
        GL.glUniform2f(u["uPaddedSize"], *self.padded)
        GL.glUniform1f(u["uMaxRadius"], s.max_blur_radius)
        GL.glUniform1f(u["uBlurStrength"], blur)
        GL.glUniform1f(u["uBlurFloor"], s.blur_evenness)
        GL.glUniform1f(u["uMaxLevel"], self.max_level)
        GL.glUniform1f(u["uMaxDim"], s.max_dim)
        GL.glUniform1f(u["uDimStrength"], g.dim_strength(progress))
        GL.glUniform1f(u["uDimFloor"], g.dim_hinge_floor)
        GL.glUniform1f(u["uDimReach"], s.dim_reach)
        GL.glUniform1f(u["uHingeGlow"], s.hinge_glow)
        GL.glUniform1f(u["uReflectionIntensity"], s.reflection_intensity)
        GL.glUniform1f(u["uTurn"], g.turn_strength(progress))
        GL.glUniform1f(u["uOpacity"], 1.0)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)
        raw = GL.glReadPixels(0, 0, self.w, self.h, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
        return np.flipud(np.frombuffer(raw, np.uint8).reshape(self.h, self.w, 4)).copy()


# --- A clean, synthetic desktop ----------------------------------------------


def draw_desktop(width: int = SCREEN_W, height: int = SCREEN_H) -> np.ndarray:
    """A made-up desktop in the brand's colours. BGRA."""
    from PyQt6.QtCore import QPointF, QRectF, Qt
    from PyQt6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QRadialGradient

    img = QImage(width, height, QImage.Format.Format_ARGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Wallpaper: dusk over water, big soft shapes that read at any blur.
    sky = QLinearGradient(0, 0, 0, height)
    sky.setColorAt(0, QColor("#1e4a6e"))
    sky.setColorAt(0.55, QColor("#e2895f"))
    sky.setColorAt(1, QColor("#2a2340"))
    p.fillRect(0, 0, width, height, sky)
    sun = QRadialGradient(QPointF(width * 0.68, height * 0.52), height * 0.28)
    sun.setColorAt(0, QColor(255, 226, 170, 255))
    sun.setColorAt(0.35, QColor(255, 180, 120, 160))
    sun.setColorAt(1, QColor(255, 150, 100, 0))
    p.fillRect(0, 0, width, height, QBrush(sun))
    p.setPen(Qt.PenStyle.NoPen)
    for i, (y, c) in enumerate(((0.62, "#3b3657"), (0.7, "#2c2a46"), (0.8, "#1d1c33"))):
        p.setBrush(QColor(c))
        path_y = height * y
        p.drawEllipse(QRectF(-width * 0.3 + i * 180, path_y, width * 1.1, height * 0.6))

    def window(x, y, w, h, title, accent):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 70))
        p.drawRoundedRect(QRectF(x + 6, y + 14, w, h), 12, 12)
        p.setBrush(QColor("#f7f4ee"))
        p.drawRoundedRect(QRectF(x, y, w, h), 12, 12)
        p.setBrush(QColor("#e9e4da"))
        p.drawRoundedRect(QRectF(x, y, w, 38), 12, 12)
        p.drawRect(QRectF(x, y + 20, w, 18))
        for j, c in enumerate(("#e0664a", "#e8b64a", "#62b27a")):
            p.setBrush(QColor(c))
            p.drawEllipse(QPointF(x + 22 + j * 20, y + 19), 6, 6)
        p.setPen(QColor("#5b5750"))
        p.setFont(font("Archivo-600", 15))
        p.drawText(QRectF(x, y, w, 38), Qt.AlignmentFlag.AlignCenter, title)
        return accent

    # A code editor.
    window(70, 70, 560, 430, "lid.py", OXIDE)
    p.setPen(Qt.PenStyle.NoPen)
    widths = [0.55, 0.8, 0.35, 0.7, 0.62, 0.3, 0.84, 0.5, 0.74, 0.4, 0.66, 0.58]
    colours = ["#2d5875", "#d2542c", "#6a7a3a", "#2d5875", "#8a5ca0", "#d2542c"]
    for i, fw in enumerate(widths):
        y = 132 + i * 28
        p.setBrush(QColor("#c9c2b4"))
        p.drawRoundedRect(QRectF(92, y, 22, 12), 3, 3)
        indent = 0 if i % 4 == 0 else 34
        p.setBrush(QColor(colours[i % len(colours)]))
        p.drawRoundedRect(QRectF(132 + indent, y, 440 * fw * 0.35, 12), 4, 4)
        p.setBrush(QColor("#9aa4ad"))
        p.drawRoundedRect(QRectF(140 + indent + 440 * fw * 0.35, y, 440 * fw * 0.55, 12), 4, 4)

    # A photo card.
    window(680, 150, 500, 380, "Photos", LINEN)
    ph = QLinearGradient(700, 200, 1160, 510)
    ph.setColorAt(0, QColor("#f2c14e"))
    ph.setColorAt(1, QColor("#d2542c"))
    p.setBrush(QBrush(ph))
    p.drawRoundedRect(QRectF(700, 206, 460, 250), 8, 8)
    p.setBrush(QColor("#123049"))
    p.drawEllipse(QRectF(760, 280, 140, 140))
    p.setBrush(QColor("#f4f0e6"))
    p.drawRoundedRect(QRectF(700, 472, 220, 14), 4, 4)
    p.setBrush(QColor("#c6cdd2"))
    p.drawRoundedRect(QRectF(700, 496, 150, 12), 4, 4)

    # Taskbar.
    p.setBrush(QColor(12, 20, 32, 220))
    p.drawRect(QRectF(0, height - 54, width, 54))
    for i in range(6):
        p.setBrush(QColor(OXIDE if i == 2 else "#3c5a74"))
        p.drawRoundedRect(QRectF(width / 2 - 150 + i * 52, height - 44, 36, 36), 9, 9)
    p.setPen(QColor(CHALK))
    p.setFont(font("IBMPlexMono-500", 15))
    p.drawText(QRectF(width - 140, height - 54, 120, 54), Qt.AlignmentFlag.AlignCenter, "9:41")
    p.end()

    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    return np.frombuffer(ptr, np.uint8).reshape(height, width, 4).copy()


# --- Scenes ------------------------------------------------------------------


class Reel:
    def __init__(self) -> None:
        self.effect = EffectRenderer(SCREEN_W, SCREEN_H)
        self.effect.upload(draw_desktop())
        self._cache: dict[float, object] = {}

    def screen_image(self, t: float):
        from PyQt6.QtGui import QImage

        travel = lid_travel(t)
        key = round(travel, 2)
        if key not in self._cache:
            dt = 1 / 240
            velocity = (lid_travel(t + dt) - lid_travel(t - dt)) / (2 * dt)
            rgba = self.effect.render(travel, velocity)
            image = QImage(rgba.data, SCREEN_W, SCREEN_H, SCREEN_W * 4, QImage.Format.Format_RGBA8888).copy()
            if len(self._cache) > 64:
                self._cache.clear()
            self._cache[key] = image
        return self._cache[key]

    def paint(self, p, t: float) -> None:
        from PyQt6.QtCore import QPointF
        from PyQt6.QtGui import QBrush, QColor, QLinearGradient, QRadialGradient

        # Ground: the site's flat, lit from the top left.
        g = QLinearGradient(0, 0, W * 0.6, H)
        g.setColorAt(0, QColor(BLUE_LIFT))
        g.setColorAt(0.5, QColor(BLUE))
        g.setColorAt(1, QColor(BLUE_DEEP))
        p.fillRect(0, 0, W, H, g)
        self.grid(p, t)

        self.scene_title(p, t)
        self.scene_camera(p, t)
        self.scene_laptop(p, t)
        self.scene_platforms(p, t)
        self.scene_end(p, t)

        # Vignette.
        v = QRadialGradient(QPointF(W / 2, H / 2), H * 0.78)
        v.setColorAt(0.55, QColor(0, 0, 0, 0))
        v.setColorAt(1, QColor(0, 0, 0, 150))
        p.fillRect(0, 0, W, H, QBrush(v))

    # Snap lines, as on the site. They drift, very slowly.
    def grid(self, p, t: float) -> None:
        from PyQt6.QtGui import QColor, QPen

        pen = QPen(QColor(45, 88, 117, 70))
        pen.setWidthF(1.0)
        p.setPen(pen)
        offset = (t * 8) % 90
        for x in range(-90, W + 90, 90):
            p.drawLine(int(x + offset), 0, int(x + offset), H)
        for y in range(-90, H + 90, 90):
            p.drawLine(0, int(y + offset * 0.5), W, int(y + offset * 0.5))

    # 0 - 2.2 s: the wordmark falls back on a hinge.
    def scene_title(self, p, t: float) -> None:
        from PyQt6.QtCore import QPointF, QRectF, Qt
        from PyQt6.QtGui import QColor, QTransform

        if t > 2.4:
            return
        out = ease_in_out(span(t, 1.65, 2.3))
        hinge_y = H * 0.56
        # The hinge line draws out from the centre.
        draw = ease_out(span(t, 0.05, 0.7))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(OXIDE))
        half = W * 0.36 * draw
        p.drawRect(QRectF(W / 2 - half, hinge_y, 2 * half, 6 * (1 - out) + 0.01))

        # Letters rise from the hinge one by one, then lean back together.
        word = "WINDUO"
        f = font("BigShouldersDisplay-800", 230)
        p.setFont(f)
        metrics = p.fontMetrics()
        total = metrics.horizontalAdvance(word)
        x = W / 2 - total / 2
        lean = 72 * out
        for i, ch in enumerate(word):
            rise = ease_back(span(t, 0.25 + i * 0.06, 0.75 + i * 0.06))
            cw = metrics.horizontalAdvance(ch)
            transform = QTransform()
            transform.translate(x + cw / 2, hinge_y)
            # Perspective lean about the hinge: a projective squash toward it.
            transform.scale(1 - 0.35 * math.sin(math.radians(lean)), math.cos(math.radians(lean)))
            transform.translate(-cw / 2, 0)
            p.save()
            p.setTransform(transform)
            p.setOpacity((1 - out * 0.9) * clamp01(rise * 1.5))
            p.setPen(QColor(CHALK))
            clip = QRectF(-20, -metrics.ascent() - 40, cw + 40, metrics.ascent() + 40)
            p.setClipRect(clip)
            p.drawText(QPointF(0, (1 - rise) * metrics.ascent()), ch)
            p.restore()
            x += cw

        p.setOpacity(ease_out(span(t, 0.8, 1.2)) * (1 - out))
        p.setPen(QColor(CHALK_SOFT))
        p.setFont(font("Archivo-400", 38))
        p.drawText(QRectF(0, hinge_y + 40, W, 60), Qt.AlignmentFlag.AlignHCenter, "Close the lid. Watch it lean.")
        p.setOpacity(1)

    # 2.2 - 4.8 s: how it knows, with no sensor.
    def scene_camera(self, p, t: float) -> None:
        from PyQt6.QtCore import QPointF, QRectF, Qt
        from PyQt6.QtGui import QColor, QPen

        if t < 2.1 or t > 5.0:
            return
        enter = ease_out(span(t, 2.15, 2.8))
        leave = ease_in_out(span(t, 4.4, 4.95))
        p.save()
        p.translate(0, (1 - enter) * 120 - leave * 260)
        p.setOpacity(enter * (1 - leave))

        cx, cy = W / 2, H * 0.34
        # The lens: rings that breathe, and an oxide iris.
        for i, r in enumerate((150, 118, 84)):
            pen = QPen(QColor(CHALK if i == 0 else CHALK_FAINT))
            pen.setWidthF(6 if i == 0 else 2)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            wobble = 4 * math.sin(t * 5 + i)
            p.drawEllipse(QPointF(cx, cy), r + wobble, r + wobble)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(OXIDE))
        p.drawEllipse(QPointF(cx, cy), 44, 44)
        p.setBrush(QColor(CHALK))
        p.drawEllipse(QPointF(cx - 14, cy - 14), 10, 10)

        # Rows of the camera image, sliding up as the lid closes: the shift the
        # tracker measures.
        shift = 60 * ease_in_out(span(t, 3.0, 4.2))
        top = H * 0.52
        for i in range(9):
            y = top + i * 34 - shift
            if y < top - 40 or y > top + 300:
                continue
            w = W * (0.28 + 0.4 * abs(math.sin(i * 1.7)))
            fade = clamp01(1 - abs(y - (top + 140)) / 190)
            p.setOpacity(enter * (1 - leave) * fade)
            p.setBrush(QColor(BLUE_LINE if i % 3 else LINEN))
            p.drawRoundedRect(QRectF(W / 2 - w / 2, y, w, 16), 8, 8)
        p.setOpacity(enter * (1 - leave))
        pen = QPen(QColor(OXIDE_LIFT))
        pen.setWidthF(4)
        p.setPen(pen)
        ax = W * 0.84
        p.drawLine(QPointF(ax, top + 190), QPointF(ax, top + 190 - shift * 2.2))
        p.setFont(font("IBMPlexMono-500", 34))
        p.drawText(QRectF(ax - 200, top + 200, 230, 50), Qt.AlignmentFlag.AlignRight, f"{shift * 0.269 * 5:4.1f}\u00b0")

        p.setPen(QColor(CHALK))
        p.setFont(font("BigShouldersDisplay-800", 104))
        p.drawText(QRectF(0, H * 0.78, W, 120), Qt.AlignmentFlag.AlignHCenter, "NO HINGE SENSOR")
        p.setPen(QColor(CHALK_SOFT))
        p.setFont(font("Archivo-400", 36))
        p.drawText(QRectF(0, H * 0.78 + 118, W, 60), Qt.AlignmentFlag.AlignHCenter, "The webcam reads the lid instead.")
        p.restore()

    # 4.6 - 10.6 s: the effect itself, on a laptop that actually closes.
    def scene_laptop(self, p, t: float) -> None:
        from PyQt6.QtCore import QPointF, QRectF, Qt
        from PyQt6.QtGui import (
            QBrush,
            QColor,
            QLinearGradient,
            QPen,
            QPolygonF,
            QTransform,
        )

        if t < 4.5 or t > 10.55:
            return
        enter = ease_out(span(t, 4.55, 5.25))
        leave = ease_in_out(span(t, 10.05, 10.5))
        p.save()
        scale = mix(0.86, 1.0, enter) * mix(1.0, 0.8, leave)
        p.translate(W / 2, H * 0.47)
        p.scale(scale, scale)
        p.translate(-W / 2, -H * 0.47)
        p.setOpacity(enter * (1 - leave))

        travel = lid_travel(t)
        angle = 100.0 - travel  # lid angle from the keyboard
        # Seen from the front, a little above: the lid's apparent height is
        # its length times the sine of the angle between it and the viewing
        # direction; the keyboard deck foreshortens the other way.
        # Foreshortened, but gently: the eye follows the screen down.
        lid_len = 600
        lid_h = lid_len * (0.5 + 0.5 * math.sin(math.radians(angle)))
        hinge = QPointF(W / 2, H * 0.66)
        half_w = 470
        top_half = half_w * (1 - 0.06 * math.cos(math.radians(angle)))

        # Shadow under the machine.
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawEllipse(QRectF(W / 2 - 520, hinge.y() + 150, 1040, 60))

        # Deck.
        deck = QPolygonF([
            QPointF(W / 2 - half_w, hinge.y()), QPointF(W / 2 + half_w, hinge.y()),
            QPointF(W / 2 + half_w + 60, hinge.y() + 150), QPointF(W / 2 - half_w - 60, hinge.y() + 150),
        ])
        dg = QLinearGradient(0, hinge.y(), 0, hinge.y() + 150)
        dg.setColorAt(0, QColor("#3a4a58"))
        dg.setColorAt(1, QColor("#1f2a34"))
        p.setBrush(QBrush(dg))
        p.drawPolygon(deck)
        p.setBrush(QColor("#161f28"))
        p.drawRoundedRect(QRectF(W / 2 - 150, hinge.y() + 112, 300, 26), 6, 6)
        for row in range(4):
            y = hinge.y() + 16 + row * 22
            inset = row * 12
            p.setBrush(QColor(20, 28, 36, 200))
            p.drawRoundedRect(QRectF(W / 2 - half_w + 30 - inset + 20, y, 2 * (half_w - 50) + 2 * inset - 40, 16), 4, 4)

        # Lid, bezel and screen.
        lid = QPolygonF([
            QPointF(W / 2 - half_w, hinge.y()), QPointF(W / 2 + half_w, hinge.y()),
            QPointF(W / 2 + top_half, hinge.y() - lid_h), QPointF(W / 2 - top_half, hinge.y() - lid_h),
        ])
        p.setBrush(QColor("#0b0f14"))
        p.drawPolygon(lid)
        bezel = 22 * lid_h / lid_len
        inner = QPolygonF([
            QPointF(W / 2 - half_w + 22, hinge.y() - bezel), QPointF(W / 2 + half_w - 22, hinge.y() - bezel),
            QPointF(W / 2 + top_half - 22, hinge.y() - lid_h + bezel * 1.6),
            QPointF(W / 2 - top_half + 22, hinge.y() - lid_h + bezel * 1.6),
        ])
        source = QPolygonF([QPointF(0, SCREEN_H), QPointF(SCREEN_W, SCREEN_H), QPointF(SCREEN_W, 0), QPointF(0, 0)])
        transform = QTransform()
        if lid_h > 8 and QTransform.quadToQuad(source, inner, transform):
            p.save()
            p.setTransform(transform, True)
            p.setRenderHint(p.RenderHint.SmoothPixmapTransform)
            p.drawImage(0, 0, self.screen_image(t))
            p.restore()
        # Glass sheen.
        sheen = QLinearGradient(inner[3], inner[1])
        sheen.setColorAt(0.0, QColor(255, 255, 255, 26))
        sheen.setColorAt(0.45, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(sheen))
        p.drawPolygon(inner)
        # Camera dot, glowing while armed.
        cam = QPointF(W / 2, hinge.y() - lid_h + bezel * 0.8)
        p.setBrush(QColor(62, 220, 120, int(200 * enter)))
        p.drawEllipse(cam, 4, 4)

        # Angle gauge: an arc from the hinge, and the reading.
        gx, gy = W * 0.16, H * 0.11
        pen = QPen(QColor(BLUE_LINE))
        pen.setWidthF(3)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(gx - 90, gy - 90, 180, 180), 0, 180 * 16)
        pen = QPen(QColor(OXIDE_LIFT))
        pen.setWidthF(6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(QRectF(gx - 90, gy - 90, 180, 180), 0, int(angle * 16))
        a = math.radians(angle)
        p.drawLine(QPointF(gx, gy), QPointF(gx + 90 * math.cos(a), gy - 90 * math.sin(a)))
        p.setPen(QColor(CHALK))
        p.setFont(font("IBMPlexMono-500", 58))
        p.drawText(QRectF(gx + 120, gy - 70, 360, 80), Qt.AlignmentFlag.AlignLeft, f"{angle:5.1f}\u00b0")
        p.setPen(QColor(CHALK_FAINT))
        p.setFont(font("Archivo-600", 24, spacing=3))
        p.drawText(QRectF(gx - 90, gy + 24, 900, 40), Qt.AlignmentFlag.AlignLeft, "LID ANGLE, READ BY THE WEBCAM")

        # Caption that follows the phase of the close.
        phase = (
            "The picture leans back" if 5.2 < t < 8.5 and travel > TRIGGER
            else "and comes back up" if t >= 8.5 else "Close the lid"
        )
        p.setPen(QColor(CHALK))
        p.setFont(font("BigShouldersDisplay-800", 86))
        p.drawText(QRectF(0, H * 0.83, W, 110), Qt.AlignmentFlag.AlignHCenter, phase.upper())
        p.restore()

    # 10.4 - 12.9 s: where it runs.
    def scene_platforms(self, p, t: float) -> None:
        from PyQt6.QtCore import QRectF, Qt
        from PyQt6.QtGui import QColor

        if t < 10.4 or t > 13.0:
            return
        leave = ease_in_out(span(t, 12.4, 12.95))
        chips = (("WINDOWS", "10 and 11"), ("WINDHAWK", "native mod"), ("HYPRLAND", "Omarchy"))
        for i, (name, note) in enumerate(chips):
            k = ease_back(span(t, 10.45 + i * 0.16, 11.1 + i * 0.16), 1.3)
            y = H * 0.24 + i * 300
            x = mix(W + 200, W * 0.1, k) - leave * (W * 1.2)
            p.save()
            p.setOpacity(clamp01(k * 2))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(BLUE_DEEP))
            p.drawRect(QRectF(x, y, W * 0.8, 230))
            p.setBrush(QColor(OXIDE))
            p.drawRect(QRectF(x, y, 14, 230))
            p.setPen(QColor(CHALK))
            p.setFont(font("BigShouldersDisplay-800", 132))
            p.drawText(QRectF(x + 60, y + 10, W, 150), Qt.AlignmentFlag.AlignVCenter, name)
            p.setPen(QColor(CHALK_SOFT))
            p.setFont(font("Archivo-400", 36))
            p.drawText(QRectF(x + 64, y + 156, W, 50), Qt.AlignmentFlag.AlignLeft, note)
            p.restore()
        p.setOpacity(ease_out(span(t, 10.5, 11.0)) * (1 - leave))
        p.setPen(QColor(CHALK_FAINT))
        p.setFont(font("Archivo-600", 30, spacing=6))
        p.drawText(QRectF(0, H * 0.1, W, 50), Qt.AlignmentFlag.AlignHCenter, "RUNS ON")
        p.setOpacity(1)

    # 12.6 - 15 s: the end card.
    def scene_end(self, p, t: float) -> None:
        from PyQt6.QtCore import QRectF, Qt
        from PyQt6.QtGui import QColor

        if t < 12.6:
            return
        k = ease_out(span(t, 12.65, 13.5))
        hinge_y = H * 0.5
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(OXIDE))
        p.drawRect(QRectF(W / 2 - W * 0.36 * k, hinge_y + 40, W * 0.72 * k, 6))
        p.save()
        p.setOpacity(k)
        p.translate(0, (1 - k) * 60)
        p.setPen(QColor(CHALK))
        p.setFont(font("BigShouldersDisplay-800", 250))
        p.drawText(QRectF(0, hinge_y - 260, W, 300), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, "WINDUO")
        p.restore()
        k2 = ease_out(span(t, 13.1, 13.9))
        p.setOpacity(k2)
        p.setPen(QColor(OXIDE_LIFT))
        p.setFont(font("IBMPlexMono-500", 46))
        p.drawText(QRectF(0, hinge_y + 90, W, 70), Qt.AlignmentFlag.AlignHCenter, "baselashraf.com/winduo")
        p.setPen(QColor(CHALK_FAINT))
        p.setFont(font("Archivo-400", 32))
        p.drawText(QRectF(0, hinge_y + 170, W, 60), Qt.AlignmentFlag.AlignHCenter, "Free for noncommercial use")
        p.setOpacity(1)


def render_frame(reel: Reel, t: float) -> np.ndarray:
    from PyQt6.QtGui import QImage, QPainter

    acc = None
    samples = [t + (i - (SUBFRAMES - 1) / 2) / (FPS * SUBFRAMES) for i in range(SUBFRAMES)]
    for ts in samples:
        img = QImage(W, H, QImage.Format.Format_RGB32)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        reel.paint(p, max(0.0, min(ts, DURATION - 1e-6)))
        p.end()
        ptr = img.constBits()
        ptr.setsize(img.sizeInBytes())
        arr = np.frombuffer(ptr, np.uint8).reshape(H, W, 4)[:, :, :3].astype(np.float32)
        acc = arr if acc is None else acc + arr
    return (acc / SUBFRAMES).astype(np.uint8)


def encode(frames_dir: Path, out: Path, fps: int) -> None:
    pattern = str(frames_dir / "f%04d.png")
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(fps), "-i", pattern,
         "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(out.with_suffix(".mp4"))],
        check=True,
    )
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(fps), "-i", pattern,
         "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "34", "-row-mt", "1",
         str(out.with_suffix(".webm"))],
        check=True,
    )


def main(argv=None) -> int:
    import cv2

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("build/reel"))
    parser.add_argument("--frame", type=int, default=None, help="render one frame only")
    parser.add_argument("--gif", action="store_true", help="the Windhawk readme GIF")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    setup_qt()
    reel = Reel()

    if args.gif:
        # Just the screen: a close and a reopen, looping.
        frames = args.out / "gif_frames"
        shutil.rmtree(frames, ignore_errors=True)
        frames.mkdir()
        for i in range(90):
            t = 5.0 + i / 90 * 5.4
            rgba = reel.effect.render(lid_travel(t))
            small = cv2.resize(cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR), (640, 400), interpolation=cv2.INTER_AREA)
            cv2.imwrite(str(frames / f"f{i:04d}.png"), small)
        palette = args.out / "palette.png"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", "18", "-i", str(frames / "f%04d.png"),
                        "-vf", "palettegen=max_colors=128", str(palette)], check=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", "18", "-i", str(frames / "f%04d.png"),
                        "-i", str(palette), "-lavfi", "paletteuse=dither=bayer:bayer_scale=4",
                        "-loop", "0", str(args.out / "windhawk-preview.gif")], check=True)
        shutil.rmtree(frames)
        palette.unlink()
        print("wrote", args.out / "windhawk-preview.gif")
        return 0

    if args.frame is not None:
        cv2.imwrite(str(args.out / f"still-{args.frame:04d}.png"), render_frame(reel, args.frame / FPS))
        return 0

    frames = args.out / "frames"
    shutil.rmtree(frames, ignore_errors=True)
    frames.mkdir()
    total = int(DURATION * FPS)
    for i in range(total):
        cv2.imwrite(str(frames / f"f{i:04d}.png"), render_frame(reel, i / FPS))
        if i % 60 == 0:
            print(f"{i}/{total}", flush=True)
    encode(frames, args.out / "showreel", FPS)
    cv2.imwrite(str(args.out / "poster.jpg"), render_frame(reel, 7.4), [cv2.IMWRITE_JPEG_QUALITY, 88])
    shutil.rmtree(frames)
    print("wrote", args.out / "showreel.mp4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
