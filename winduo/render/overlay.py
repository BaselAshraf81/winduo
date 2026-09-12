"""The overlay window and its OpenGL renderer.

Structure follows Mac Duo's split between ``DepthOverlay`` and ``DepthRenderer``:
a window that knows about showing and fading, wrapping a renderer that knows
about textures and uniforms.

The picture lives in one texture with a black margin around it and a mip pyramid
over it. Every frame is a single full-screen pass, and the blur is a mip level
rather than a convolution, so the cost does not grow with the blur radius.
"""

from __future__ import annotations

import math

import numpy as np
from OpenGL import GL
from PyQt6.QtCore import QPropertyAnimation, Qt
from PyQt6.QtGui import QSurfaceFormat
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QWidget

from winduo.log import get_logger
from winduo.render import win32
from winduo.render.shaders import FRAGMENT, VERTEX

log = get_logger("overlay")

__all__ = ["DepthOverlay", "FrameParams", "configure_surface", "flip_safe_geometry"]

#: Black margin around the picture, in points. Kept above the largest blur
#: radius the settings allow, so the blur always reaches real black on every
#: side instead of smearing the edge pixel outward.
PADDING_POINTS = 120.0


def flip_safe_geometry(screen_rect):
    """The window rectangle to use, one pixel taller than the display.

    This looks like a superstition and is not. A window whose rectangle exactly
    matches the monitor gets promoted by the desktop compositor to an
    independent flip: its surface is handed to the display directly instead of
    being composited with everything else. DXGI Desktop Duplication then
    duplicates *that surface* rather than the composed desktop, and
    ``SetWindowDisplayAffinity`` never gets a say, because the composition it
    would have applied to is being bypassed.

    The result is a feedback loop. The app captures its own transparent overlay,
    draws that, captures the result, and the screen goes black and stays black.

    One pixel of mismatch is enough to keep the window composited. Measured on
    Intel UHD 630: an exactly fullscreen overlay duplicates its own surface,
    while one a pixel taller duplicates the desktop. Growing downward puts the
    extra row below the visible area, so nothing on screen is uncovered; the
    alternative of shrinking by a pixel leaves a visible strip of untouched
    desktop along one edge.

    The exclusion is still doing the real work: without it, a correctly
    composited overlay is captured like any other window.
    """
    return screen_rect.adjusted(0, 0, 0, 1)


def configure_surface() -> None:
    """Ask for the context the shader needs. Must run before any Qt window exists."""
    surface = QSurfaceFormat()
    surface.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    surface.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    surface.setVersion(3, 3)
    surface.setAlphaBufferSize(8)
    surface.setDepthBufferSize(0)
    surface.setStencilBufferSize(0)
    surface.setSwapInterval(0)
    QSurfaceFormat.setDefaultFormat(surface)


class FrameParams:
    """Everything one drawn frame needs. Plain object; rebuilt every frame."""

    __slots__ = (
        "corners",
        "blur_strength",
        "dim_strength",
        "blur_floor",
        "dim_floor",
        "dim_reach",
        "max_blur_radius",
        "max_dim",
    )

    def __init__(
        self,
        corners,
        blur_strength: float = 0.0,
        dim_strength: float = 0.0,
        blur_floor: float = 0.0,
        dim_floor: float = 0.2,
        dim_reach: float = 0.5,
        max_blur_radius: float = 135.0,
        max_dim: float = 1.0,
    ) -> None:
        self.corners = corners
        self.blur_strength = blur_strength
        self.dim_strength = dim_strength
        self.blur_floor = blur_floor
        self.dim_floor = dim_floor
        self.dim_reach = dim_reach
        self.max_blur_radius = max_blur_radius
        self.max_dim = max_dim


class _DepthView(QOpenGLWidget):
    """Draws the picture. Owns the GL objects and nothing else."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._program = None
        self._vao = None
        self._texture = None
        self._uniforms: dict[str, int] = {}

        #: Display size in points, which is also the geometry's coordinate space.
        self._screen_size = (0.0, 0.0)
        #: Captured frame size in pixels. Never larger than the display.
        self._picture_size = (0, 0)
        #: Captured pixels per point. 1.0 when capturing at native resolution.
        self._picture_scale = 1.0
        self._texture_size = (0, 0)
        self._inset = 0
        self._max_level = 0.0

        self._pending: np.ndarray | None = None
        self._params: FrameParams | None = None
        self._has_picture = False
        self._failed = False

    # --- Setup -----------------------------------------------------------

    def configure(
        self, screen_size: tuple[float, float], picture_size: tuple[int, int]
    ) -> None:
        """Set the geometry space and the resolution the picture arrives at."""
        self._screen_size = (float(screen_size[0]), float(screen_size[1]))
        self._picture_size = (int(picture_size[0]), int(picture_size[1]))
        self._picture_scale = (
            self._picture_size[0] / self._screen_size[0]
            if self._screen_size[0] > 0
            else 1.0
        )
        padded_w = self._screen_size[0] + 2 * PADDING_POINTS
        padded_h = self._screen_size[1] + 2 * PADDING_POINTS
        self._padded_points = (padded_w, padded_h)
        self._texture_size = (
            max(int(round(padded_w * self._picture_scale)), 2),
            max(int(round(padded_h * self._picture_scale)), 2),
        )
        self._inset = int(round(PADDING_POINTS * self._picture_scale))
        self._max_level = float(
            int(math.floor(math.log2(max(self._texture_size))))
        )
        self._has_picture = False
        self._texture_dirty = True

    @property
    def has_picture(self) -> bool:
        return self._has_picture

    @property
    def is_usable(self) -> bool:
        return not self._failed

    def submit(self, frame: np.ndarray | None, params: FrameParams) -> None:
        """Hand over the newest captured frame, if any, and this frame's uniforms."""
        if frame is not None:
            self._pending = frame
        self._params = params
        self.update()

    def release_picture(self) -> None:
        self._pending = None
        self._has_picture = False

    # --- GL --------------------------------------------------------------

    def initializeGL(self) -> None:  # noqa: N802 - Qt naming
        try:
            self._program = _build_program()
            self._vao = GL.glGenVertexArrays(1)
            self._allocate_texture()
            self._uniforms = _uniform_locations(self._program)
            GL.glDisable(GL.GL_DEPTH_TEST)
            GL.glDisable(GL.GL_BLEND)
            log.info(
                "GL ready: %s, %s",
                GL.glGetString(GL.GL_VERSION).decode(errors="replace"),
                GL.glGetString(GL.GL_RENDERER).decode(errors="replace"),
            )
        except Exception:
            self._failed = True
            log.exception("the renderer could not start")

    def _allocate_texture(self) -> None:
        width, height = self._texture_size
        if width < 2 or height < 2:
            return
        if self._texture is None:
            self._texture = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._texture)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        # Filled with zeros, so the margin is black from the start. Only the
        # interior is overwritten per frame, which is why this happens once.
        GL.glTexImage2D(
            GL.GL_TEXTURE_2D,
            0,
            GL.GL_SRGB8_ALPHA8,
            width,
            height,
            0,
            GL.GL_BGRA,
            GL.GL_UNSIGNED_BYTE,
            np.zeros((height, width, 4), dtype=np.uint8),
        )
        GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
        self._texture_dirty = False

    def paintGL(self) -> None:  # noqa: N802 - Qt naming
        if self._failed or self._program is None:
            return
        if getattr(self, "_texture_dirty", False):
            self._allocate_texture()

        GL.glClearColor(0.0, 0.0, 0.0, 0.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)

        if self._pending is not None:
            self._upload(self._pending)
            self._pending = None

        params = self._params
        if params is None or not self._has_picture or self._texture is None:
            return

        matrix = _screen_to_picture(self._screen_size, params.corners)
        if matrix is None:
            return

        GL.glUseProgram(self._program)
        GL.glBindVertexArray(self._vao)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._texture)

        u = self._uniforms
        GL.glUniform1i(u["uPicture"], 0)
        # Column-major, which is what GL wants and what the matrix already is.
        GL.glUniformMatrix3fv(u["uScreenToPicture"], 1, GL.GL_FALSE, matrix)
        GL.glUniform2f(u["uScreenSize"], *self._screen_size)
        GL.glUniform2f(u["uPaddedOrigin"], -PADDING_POINTS, -PADDING_POINTS)
        GL.glUniform2f(u["uPaddedSize"], *self._padded_points)
        GL.glUniform1f(
            u["uMaxRadius"], params.max_blur_radius * self._picture_scale
        )
        GL.glUniform1f(u["uBlurStrength"], params.blur_strength)
        GL.glUniform1f(u["uBlurFloor"], params.blur_floor)
        GL.glUniform1f(u["uMaxLevel"], self._max_level)
        GL.glUniform1f(u["uMaxDim"], params.max_dim)
        GL.glUniform1f(u["uDimStrength"], params.dim_strength)
        GL.glUniform1f(u["uDimFloor"], params.dim_floor)
        GL.glUniform1f(u["uDimReach"], params.dim_reach)

        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)
        GL.glBindVertexArray(0)
        GL.glUseProgram(0)

    def _upload(self, frame: np.ndarray) -> None:
        if self._texture is None:
            return
        height, width = frame.shape[:2]
        texture_w, texture_h = self._texture_size
        if width + 2 * self._inset > texture_w or height + 2 * self._inset > texture_h:
            # The display changed size under us. The controller will reconfigure
            # on the screen-change notification; skip this frame rather than
            # writing outside the texture.
            return
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._texture)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 4)
        GL.glTexSubImage2D(
            GL.GL_TEXTURE_2D,
            0,
            self._inset,
            self._inset,
            width,
            height,
            GL.GL_BGRA,
            GL.GL_UNSIGNED_BYTE,
            frame,
        )
        GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
        self._has_picture = True


class DepthOverlay:
    """Owns the overlay window.

    The window is built once and reused for every run, which matters more than
    it sounds. Creating it costs a Win32 window, an OpenGL context, a shader
    compile, and a padded texture with its mip chain, and on integrated graphics
    that adds up to a stall measured in seconds. Doing that when the effect
    triggers would freeze the frame loop through exactly the movement the effect
    exists to follow. Built at startup, the trigger path is a fade and a texture
    upload.
    """

    FADE_IN_MS = 70
    FADE_OUT_MS = 220

    def __init__(self) -> None:
        self._window: QWidget | None = None
        self._view: _DepthView | None = None
        self._fade: QPropertyAnimation | None = None
        self._shown = False
        self._revealed = False
        self._excluded = False
        self._configured: tuple[tuple[float, float], tuple[int, int]] | None = None
        self._built = False

    # --- State -----------------------------------------------------------

    @property
    def is_visible(self) -> bool:
        return self._shown

    @property
    def has_picture(self) -> bool:
        return bool(self._view and self._view.has_picture)

    @property
    def excludes_itself_from_capture(self) -> bool:
        """False means a live picture would capture the overlay and recurse."""
        return self._excluded

    @property
    def is_usable(self) -> bool:
        return bool(self._view and self._view.is_usable)

    # --- Building --------------------------------------------------------

    def warm_up(self, geometry_rect, screen_size, picture_size) -> bool:
        """Build the window and compile the shader, ahead of any lid movement.

        Left at zero opacity and hidden afterwards. Called once at startup and
        again whenever the display configuration changes.
        """
        if self._built:
            self._reconfigure(geometry_rect, screen_size, picture_size)
            return self.is_usable

        window = QWidget(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.BypassWindowManagerHint,
        )
        window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        window.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        window.setWindowOpacity(0.0)
        window.setGeometry(flip_safe_geometry(geometry_rect))

        # The view stays exactly the size of the display, anchored at the top of
        # a window that is one pixel taller. The spare row falls below the
        # visible area, so the drawn picture lines up with the screen and
        # gl_FragCoord needs no offset.
        view = _DepthView(window)
        view.setGeometry(0, 0, geometry_rect.width(), geometry_rect.height())
        view.configure(screen_size, picture_size)

        self._window = window
        self._view = view
        self._configured = (screen_size, picture_size)
        self._built = True

        # Shown once, at zero opacity, and never hidden again.
        #
        # This is not just about the shader compile. A full-screen topmost
        # window appearing invalidates the display's duplication, and the
        # capture backend's recovery from that blocks for the better part of a
        # second. Doing it when the lid starts moving stalls the frame loop
        # through the movement being tracked. Showing the window once at startup
        # pays that cost while nothing is happening, and from then on running the
        # effect is only an opacity animation.
        #
        # An always-present window is safe here because it is excluded from
        # capture, transparent to input, and fully transparent until there is
        # something to draw.
        window.show()
        self._excluded = win32.exclude_from_capture(window, True)
        win32.make_click_through(window)
        win32.raise_topmost(window)
        self._shown = False

        if not view.is_usable:
            log.warning("the renderer could not start; the effect is unavailable")
            return False
        log.info("overlay warmed up")
        return True

    def _reconfigure(self, geometry_rect, screen_size, picture_size) -> None:
        if self._window is None or self._view is None:
            return
        if self._configured == (screen_size, picture_size):
            self._window.setGeometry(flip_safe_geometry(geometry_rect))
            self._view.setGeometry(0, 0, geometry_rect.width(), geometry_rect.height())
            return
        log.info(
            "overlay reconfigured for %s at %s", screen_size, picture_size
        )
        self._window.setGeometry(flip_safe_geometry(geometry_rect))
        self._view.setGeometry(0, 0, geometry_rect.width(), geometry_rect.height())
        self._view.configure(screen_size, picture_size)
        self._configured = (screen_size, picture_size)

    # --- Showing ---------------------------------------------------------

    def show(
        self,
        geometry_rect,
        screen_size: tuple[float, float],
        picture_size: tuple[int, int],
    ) -> bool:
        """Bring the prepared window up, still transparent, ready for a frame."""
        if not self._built and not self.warm_up(geometry_rect, screen_size, picture_size):
            return False
        self._reconfigure(geometry_rect, screen_size, picture_size)
        if self._window is None or self._view is None or not self._view.is_usable:
            return False

        self._stop_fade()
        self._revealed = False
        self._window.setWindowOpacity(0.0)
        self._shown = True
        if not self._excluded:
            self._excluded = win32.exclude_from_capture(self._window, True)
        # Raised each run, so a window that has since gone topmost above us
        # does not end up in front of the effect.
        win32.raise_topmost(self._window)
        return True

    def submit(self, frame: np.ndarray | None, params: FrameParams) -> None:
        if self._view is None or not self._shown:
            return
        self._view.submit(frame, params)
        if self._view.has_picture:
            self._reveal()

    def _reveal(self) -> None:
        """Fade in once, and only once there is something to draw.

        Revealing before the first frame lands would flash a transparent
        full-screen window over the desktop.
        """
        if self._revealed or self._window is None:
            return
        self._revealed = True
        self._animate_to(1.0, self.FADE_IN_MS)

    def dismiss(self, animated: bool = True) -> None:
        window = self._window
        if window is None or not self._shown:
            return
        self._shown = False
        self._revealed = False
        self._stop_fade()

        if not animated:
            window.setWindowOpacity(0.0)
            if self._view is not None:
                self._view.release_picture()
            return

        fade = QPropertyAnimation(window, b"windowOpacity", window)
        fade.setDuration(self.FADE_OUT_MS)
        fade.setStartValue(window.windowOpacity())
        fade.setEndValue(0.0)

        def finished() -> None:
            # The window stays up; only the picture is freed, and only if
            # nothing has started another run in the meantime.
            if not self._shown and self._view is not None:
                self._view.release_picture()

        fade.finished.connect(finished)
        fade.start()
        self._fade = fade

    def destroy(self) -> None:
        """Tear the window down for good. Only at shutdown."""
        self._stop_fade()
        window, self._window = self._window, None
        self._view = None
        self._built = False
        self._shown = False
        self._configured = None
        if window is not None:
            window.hide()
            window.deleteLater()

    def _stop_fade(self) -> None:
        fade, self._fade = self._fade, None
        if fade is not None:
            fade.stop()

    def _animate_to(self, value: float, duration_ms: int) -> None:
        if self._window is None:
            return
        self._stop_fade()
        fade = QPropertyAnimation(self._window, b"windowOpacity", self._window)
        fade.setDuration(duration_ms)
        fade.setStartValue(self._window.windowOpacity())
        fade.setEndValue(value)
        fade.start()
        self._fade = fade


# --- Helpers -------------------------------------------------------------


def _build_program() -> int:
    program = GL.glCreateProgram()
    for stage, source in ((GL.GL_VERTEX_SHADER, VERTEX), (GL.GL_FRAGMENT_SHADER, FRAGMENT)):
        shader = GL.glCreateShader(stage)
        GL.glShaderSource(shader, source)
        GL.glCompileShader(shader)
        if not GL.glGetShaderiv(shader, GL.GL_COMPILE_STATUS):
            message = GL.glGetShaderInfoLog(shader)
            raise RuntimeError(f"shader failed to compile: {_text(message)}")
        GL.glAttachShader(program, shader)
        GL.glDeleteShader(shader)
    GL.glLinkProgram(program)
    if not GL.glGetProgramiv(program, GL.GL_LINK_STATUS):
        raise RuntimeError(f"shader failed to link: {_text(GL.glGetProgramInfoLog(program))}")
    return program


_UNIFORM_NAMES = (
    "uPicture",
    "uScreenToPicture",
    "uScreenSize",
    "uPaddedOrigin",
    "uPaddedSize",
    "uMaxRadius",
    "uBlurStrength",
    "uBlurFloor",
    "uMaxLevel",
    "uMaxDim",
    "uDimStrength",
    "uDimFloor",
    "uDimReach",
)


def _uniform_locations(program: int) -> dict[str, int]:
    return {name: GL.glGetUniformLocation(program, name) for name in _UNIFORM_NAMES}


def _screen_to_picture(screen_size, corners):
    """The inverse projection, laid out the way ``glUniformMatrix3fv`` wants it."""
    from winduo.effect.homography import screen_to_picture

    try:
        matrix = screen_to_picture(screen_size[0], screen_size[1], corners)
    except (ValueError, np.linalg.LinAlgError):
        # A degenerate quad, which the geometry's clamps should prevent. Skipping
        # the frame is better than a division by zero across the whole screen.
        return None
    if not np.all(np.isfinite(matrix)):
        return None
    # GL reads 3x3 uniforms column-major; numpy hands out row-major.
    return np.ascontiguousarray(matrix.T, dtype=np.float32)


def _text(message) -> str:
    if isinstance(message, bytes):
        return message.decode(errors="replace").strip()
    return str(message).strip()
