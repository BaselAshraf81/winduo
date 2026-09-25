"""Render the effect offscreen to image files.

The overlay is excluded from screen capture on purpose, which means no
screenshot tool can photograph it, including the ones used to check the work.
This renders the same shader through an offscreen framebuffer instead, so the
perspective, the blur ramp, and the dimming can be looked at directly.

    python -m winduo.tools.render_still --out build/stills

Also useful as a regression check: the shader is the one piece of this project
that cannot be unit tested for correctness, only for whether it compiles.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from winduo.config import Settings
from winduo.effect.controller import tilt_knee
from winduo.effect.geometry import DepthGeometry
from winduo.effect.gradient import BlurGradient
from winduo.log import get_logger, setup_logging

log = get_logger("stills")

PADDING = 120.0

_APP = None


def test_card(width: int, height: int) -> np.ndarray:
    """A calibration-style card, in BGRA.

    Deliberately not a screenshot. Straight lines show whether the perspective
    is projective rather than merely scaled, a fine grid shows the blur ramp
    honestly, and flat patches show the dimming without texture confusing it.
    """
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[:, :, 3] = 255
    # Light ground, so the picture's outline reads clearly against the black
    # margin it is composited onto and any error in the warp is obvious.
    image[:, :, :3] = 214

    # Grid, every 64 px, darker every 256.
    for x in range(0, width, 64):
        image[:, x : x + 1, :3] = 150 if x % 256 else 40
    for y in range(0, height, 64):
        image[y : y + 1, :, :3] = 150 if y % 256 else 40

    # Diagonals: any projective error shows up as a kink.
    for i in range(min(width, height)):
        image[i * height // min(width, height) - 1, i * width // min(width, height), :3] = 0
        image[
            i * height // min(width, height) - 1,
            width - 1 - i * width // min(width, height),
            :3,
        ] = 0

    # A grey step wedge along the bottom, for the dimming.
    band = height - 90
    for step in range(10):
        value = int(255 * step / 9)
        x0 = width * step // 10
        x1 = width * (step + 1) // 10
        image[band : band + 70, x0:x1, :3] = value

    # Colour blocks near the top, where blur and dimming are strongest.
    blocks = [(40, 60, 200), (60, 170, 70), (200, 90, 40)]
    for index, colour in enumerate(blocks):
        x0 = 60 + index * 260
        image[70:250, x0 : x0 + 220, 0] = colour[2]
        image[70:250, x0 : x0 + 220, 1] = colour[1]
        image[70:250, x0 : x0 + 220, 2] = colour[0]

    return image


def render(
    out_dir: Path,
    width: int,
    height: int,
    steps: int,
    viewing_distance: float | None = None,
    recession: float | None = None,
    span: float | None = None,
    max_dim: float | None = None,
    top_lean: float | None = None,
    max_blur_radius: float | None = None,
    picture_path: Path | None = None,
) -> list[Path]:
    from OpenGL import GL
    from PyQt6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat
    from PyQt6.QtWidgets import QApplication

    from winduo.render.overlay import _build_program, _uniform_locations

    # Held on the module so the application outlives this function. A collected
    # QApplication takes the OpenGL context with it.
    global _APP
    _APP = QApplication.instance() or QApplication(sys.argv[:1])

    surface_format = QSurfaceFormat()
    surface_format.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    surface_format.setVersion(3, 3)

    surface = QOffscreenSurface()
    surface.setFormat(surface_format)
    surface.create()
    if not surface.isValid():
        raise RuntimeError("could not create an offscreen surface")

    context = QOpenGLContext()
    context.setFormat(surface_format)
    if not context.create() or not context.makeCurrent(surface):
        raise RuntimeError("could not create an OpenGL context")

    settings = Settings()
    if viewing_distance is not None:
        settings.viewing_distance = viewing_distance
    if recession is not None:
        settings.recession = recession
    if span is not None:
        settings.full_effect_travel = span
    if max_dim is not None:
        settings.max_dim = max_dim
    if top_lean is not None:
        settings.top_lean = top_lean
    if max_blur_radius is not None:
        settings.max_blur_radius = max_blur_radius
    geometry = DepthGeometry()
    gradient = BlurGradient()
    screen_size = (float(width), float(height))
    if picture_path is not None:
        import cv2

        loaded = cv2.imread(str(picture_path), cv2.IMREAD_COLOR)
        if loaded is None:
            raise RuntimeError(f"could not read {picture_path}")
        loaded = cv2.resize(loaded, (width, height), interpolation=cv2.INTER_AREA)
        picture = np.ascontiguousarray(cv2.cvtColor(loaded, cv2.COLOR_BGR2BGRA))
    else:
        picture = test_card(width, height)

    program = _build_program()
    uniforms = _uniform_locations(program)
    vao = GL.glGenVertexArrays(1)

    padded = (width + 2 * PADDING, height + 2 * PADDING)
    texture_w, texture_h = int(padded[0]), int(padded[1])
    inset = int(PADDING)
    max_level = float(int(np.floor(np.log2(max(texture_w, texture_h)))))

    texture = GL.glGenTextures(1)
    GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
    GL.glTexImage2D(
        GL.GL_TEXTURE_2D, 0, GL.GL_SRGB8_ALPHA8, texture_w, texture_h, 0,
        GL.GL_BGRA, GL.GL_UNSIGNED_BYTE,
        np.zeros((texture_h, texture_w, 4), dtype=np.uint8),
    )
    GL.glTexSubImage2D(
        GL.GL_TEXTURE_2D, 0, inset, inset, width, height,
        GL.GL_BGRA, GL.GL_UNSIGNED_BYTE, picture,
    )
    GL.glGenerateMipmap(GL.GL_TEXTURE_2D)

    colour = GL.glGenTextures(1)
    GL.glBindTexture(GL.GL_TEXTURE_2D, colour)
    GL.glTexImage2D(
        GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, width, height, 0,
        GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, None,
    )
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)

    fbo = GL.glGenFramebuffers(1)
    GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
    GL.glFramebufferTexture2D(
        GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0, GL.GL_TEXTURE_2D, colour, 0
    )
    if GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER) != GL.GL_FRAMEBUFFER_COMPLETE:
        raise RuntimeError("the offscreen framebuffer is incomplete")

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    trigger = settings.trigger_travel
    span = settings.full_effect_travel
    neutral = 100.0

    for step in range(steps):
        progress = step / max(steps - 1, 1)
        travel = trigger + span * progress
        tilt = trigger + tilt_knee(span * progress, settings.tilt_limit)
        profile = geometry.profile(
            start_angle=neutral - trigger,
            current_angle=neutral - tilt,
            viewing_distance_ratio=settings.viewing_distance,
            recession=settings.recession,
            top_lean=settings.top_lean,
            screen_size=screen_size,
        )
        table = np.asarray(profile.flat(), dtype=np.float32)

        GL.glViewport(0, 0, width, height)
        GL.glClearColor(0.0, 0.0, 0.0, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        GL.glUseProgram(program)
        GL.glBindVertexArray(vao)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, texture)

        GL.glUniform1i(uniforms["uPicture"], 0)
        GL.glUniform2fv(uniforms["uProfile"], len(table) // 2, table)
        GL.glUniform1f(uniforms["uProfileEnd"], profile.end)
        GL.glUniform1f(uniforms["uProfileSlope"], profile.slope)
        GL.glUniform2f(uniforms["uScreenSize"], *screen_size)
        GL.glUniform2f(uniforms["uPaddedOrigin"], -PADDING, -PADDING)
        GL.glUniform2f(uniforms["uPaddedSize"], *padded)
        GL.glUniform1f(uniforms["uMaxRadius"], settings.max_blur_radius)
        GL.glUniform1f(uniforms["uBlurStrength"], gradient.blur_strength(progress))
        GL.glUniform1f(uniforms["uBlurFloor"], settings.blur_evenness)
        GL.glUniform1f(uniforms["uMaxLevel"], max_level)
        GL.glUniform1f(uniforms["uMaxDim"], settings.max_dim)
        GL.glUniform1f(uniforms["uDimStrength"], gradient.dim_strength(progress))
        GL.glUniform1f(uniforms["uDimFloor"], gradient.dim_hinge_floor)
        GL.glUniform1f(uniforms["uDimReach"], settings.dim_reach)
        # These have to be set here too. An unset uniform reads zero, so leaving
        # them out silently renders the pre-hinge-glow look, which makes this
        # tool useless for the exact thing it exists for.
        GL.glUniform1f(uniforms["uHingeGlow"], settings.hinge_glow)
        GL.glUniform1f(uniforms["uReflectionIntensity"], settings.reflection_intensity)
        GL.glUniform1f(uniforms["uTurn"], gradient.turn_strength(progress))
        GL.glUniform1f(uniforms["uOpacity"], 1.0)

        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)

        raw = GL.glReadPixels(0, 0, width, height, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
        pixels = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)
        # OpenGL reads bottom-up.
        pixels = np.flipud(pixels)

        import cv2

        path = out_dir / f"travel-{travel:05.1f}.png"
        cv2.imwrite(str(path), cv2.cvtColor(pixels, cv2.COLOR_RGBA2BGR))
        written.append(path)
        log.info(
            "%s: travel %.1f deg, blur %.2f, dim %.2f",
            path.name,
            travel,
            gradient.blur_strength(progress),
            gradient.dim_strength(progress),
        )

    context.doneCurrent()
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("build/stills"))
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=800)
    parser.add_argument("--steps", type=int, default=6)
    parser.add_argument(
        "--viewing-distance",
        type=float,
        default=None,
        help="eye distance in screen heights; 1 converges sharply, 6 barely at all",
    )
    parser.add_argument("--recession", type=float, default=None)
    parser.add_argument(
        "--span",
        type=float,
        default=None,
        help="degrees of further closing to reach full strength",
    )
    parser.add_argument("--max-dim", type=float, default=None)
    parser.add_argument("--top-lean", type=float, default=None)
    parser.add_argument("--max-blur-radius", type=float, default=None)
    parser.add_argument(
        "--picture",
        type=Path,
        default=None,
        help="an image to use instead of the test card, e.g. a desktop screenshot",
    )
    options = parser.parse_args(argv)

    setup_logging(verbose=True)
    written = render(
        options.out,
        options.width,
        options.height,
        options.steps,
        options.viewing_distance,
        options.recession,
        options.span,
        options.max_dim,
        options.top_lean,
        options.max_blur_radius,
        options.picture,
    )
    print(f"wrote {len(written)} files to {options.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
