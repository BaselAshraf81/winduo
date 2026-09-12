"""Compose the 1200x630 social card.

Drawn with the project's own geometry rather than by hand, so the perspective,
the blur ramp, and the dimming on the card are the ones the app actually
produces. A social card that misrepresents the effect is a small lie that
travels further than the page does.

    python -m winduo.tools.make_og --out docs/og.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

from winduo.config import Settings
from winduo.effect.geometry import DepthGeometry
from winduo.effect.gradient import BlurGradient
from winduo.effect.homography import square_to_quad

__all__ = ["compose"]

WIDTH, HEIGHT = 1200, 630

# The scene-flat palette, in BGR because that is what OpenCV writes.
BLUE = (69, 48, 18)
BLUE_DEEP = (53, 33, 13)
BLUE_LINE = (117, 88, 45)
CHALK = (230, 240, 244)
CHALK_SOFT = (210, 205, 198)
CHALK_FAINT = (175, 163, 147)
OXIDE = (44, 84, 210)
LINEN = (180, 205, 217)


def _screen_content(width: int, height: int) -> np.ndarray:
    """A plausible light document window.

    Light rather than dark on purpose. The effect's whole story is a picture
    losing light as it leans away, and a dark window on a dark blue card has no
    light to lose: it reads as a black rectangle before the dimming touches it.
    """
    panel = np.full((height, width, 3), (246, 244, 240), dtype=np.uint8)

    # Title bar.
    bar = int(height * 0.095)
    panel[:bar] = (232, 228, 222)
    cv2.line(panel, (0, bar), (width, bar), (208, 202, 194), 2)
    for index, shade in enumerate(((104, 104, 216), (86, 176, 226), (96, 186, 128))):
        cv2.circle(panel, (30 + index * 28, bar // 2), 8, shade, -1)

    # A heading, then body lines, then one oxide mark so the palette carries
    # through into the picture as well as around it.
    cv2.rectangle(
        panel,
        (48, int(height * 0.16)),
        (int(width * 0.62), int(height * 0.215)),
        (52, 44, 38),
        -1,
    )

    rng = np.random.default_rng(4)
    y = int(height * 0.30)
    while y < height - 34:
        run = int(rng.integers(int(width * 0.30), int(width * 0.84)))
        shade = int(rng.integers(120, 176))
        cv2.line(panel, (48, y), (48 + run, y), (shade, shade, shade), max(3, height // 78))
        y += int(height * 0.078)

    cv2.rectangle(panel, (48, height - 62), (52, height - 20), OXIDE, -1)
    cv2.line(panel, (68, height - 44), (int(width * 0.52), height - 44), (96, 92, 88), 4)
    return panel


def compose(out: Path, lettering: bool = True, size: tuple[int, int] | None = None) -> Path:
    """Draw the card.

    ``lettering=False`` and a 16:10 size produce the video poster instead: the
    same effect with no words on it. The social card cannot double as the poster,
    because its own headline would sit inside the video frame, cropped by
    object-fit and repeating the sentence directly above it.
    """
    global WIDTH, HEIGHT
    if size is not None:
        WIDTH, HEIGHT = size

    settings = Settings()
    gradient = BlurGradient()
    geometry = DepthGeometry()

    card = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    card[:] = BLUE
    # The lit corner of the flat, top left, matching the page.
    glow = np.zeros((HEIGHT, WIDTH), dtype=np.float32)
    cv2.circle(glow, (int(WIDTH * 0.16), int(HEIGHT * 0.10)), int(WIDTH * 0.52), 1.0, -1)
    glow = cv2.GaussianBlur(glow, (0, 0), WIDTH * 0.16)[..., None]
    card = np.clip(card + glow * 26, 0, 255).astype(np.uint8)

    # Canvas weave.
    card[:, ::3] = np.clip(card[:, ::3].astype(np.int16) + 4, 0, 255).astype(np.uint8)
    card[::3, :] = np.clip(card[::3, :].astype(np.int16) - 5, 0, 255).astype(np.uint8)

    # --- The screen, warped by the real geometry ------------------------

    # The poster has the whole frame to itself, so the panel fills more of it.
    if lettering:
        panel_w, panel_h = 560, 350
        origin_x, origin_y = 596, 112
    else:
        panel_w, panel_h = int(WIDTH * 0.62), int(WIDTH * 0.62 * 10 / 16)
        origin_x = (WIDTH - panel_w) // 2
        origin_y = int(HEIGHT * 0.16)
    panel = _screen_content(panel_w, panel_h)

    # Far enough into the close that the lean, the blur, and the dimming are all
    # unmistakable, while the document underneath is still clearly a document.
    travel = 27.0
    progress = min(
        max((travel - settings.trigger_travel) / settings.full_effect_travel, 0.0), 1.0
    )
    blur_strength = gradient.blur_strength(progress)
    dim_strength = gradient.dim_strength(progress)

    # Blur and dim in panel space, where "up the panel" is simply a row index.
    rows = np.linspace(1.0, 0.0, panel_h, dtype=np.float32)[:, None]
    blurred = panel.astype(np.float32)
    stack = [blurred]
    for radius in (5, 13, 30):
        stack.append(cv2.GaussianBlur(panel, (0, 0), radius).astype(np.float32))
    amount = blur_strength * (
        settings.blur_evenness + (1 - settings.blur_evenness) * rows
    )
    # Blend continuously between adjacent blur levels rather than picking one.
    # Hard bands leave visible steps across the picture, which the shader avoids
    # by trilinear mip filtering; this is the same idea in numpy.
    position = np.clip(amount, 0.0, 1.0) * (len(stack) - 1)
    lower = np.floor(position).astype(np.int32)
    upper = np.minimum(lower + 1, len(stack) - 1)
    weight = (position - lower)[..., None]
    levels = np.stack(stack)
    rows_index = np.arange(panel_h)[:, None]
    cols_index = np.arange(panel_w)[None, :]
    picked = (
        levels[lower[:, 0][:, None], rows_index, cols_index] * (1 - weight)
        + levels[upper[:, 0][:, None], rows_index, cols_index] * weight
    )

    spread = np.clip(rows / max(settings.dim_reach, 0.02), 0, 1)
    spread = spread * spread * (3 - 2 * spread)  # smoothstep
    fade = dim_strength * (gradient.dim_hinge_floor + (1 - gradient.dim_hinge_floor) * spread)
    lit = picked * np.power(1 - settings.max_dim * fade, 2.2)[..., None]
    panel = np.clip(lit, 0, 255).astype(np.uint8)

    corners = geometry.corners(
        start_angle=100.0 - settings.trigger_travel,
        current_angle=100.0 - travel,
        viewing_distance_ratio=1.9,
        recession=settings.recession,
        screen_size=(panel_w, panel_h),
    )

    # Two coordinate systems meet here, and getting it wrong flips the picture.
    #
    # The geometry works y-up and returns corners bottom-left, bottom-right,
    # top-right, top-left. warpPerspective reads the source image y-down, so
    # square_to_quad's rectangle corners are, in reading order, top-left,
    # top-right, bottom-right, bottom-left. The target list therefore has to be
    # reordered to match, not just flipped in y.

    def to_card(point: tuple[float, float]) -> tuple[float, float]:
        x, y = point
        return (origin_x + x, origin_y + (panel_h - y))

    bottom_left, bottom_right, top_right, top_left = corners
    target = [
        to_card(top_left),
        to_card(top_right),
        to_card(bottom_right),
        to_card(bottom_left),
    ]
    quad = np.array([to_card(c) for c in corners], dtype=np.float32)
    matrix = square_to_quad(panel_w, panel_h, target)

    warped = cv2.warpPerspective(
        panel,
        matrix.astype(np.float64),
        (WIDTH, HEIGHT),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    mask = cv2.warpPerspective(
        np.full((panel_h, panel_w), 255, dtype=np.uint8),
        matrix.astype(np.float64),
        (WIDTH, HEIGHT),
        flags=cv2.INTER_LINEAR,
    )
    alpha = (mask.astype(np.float32) / 255.0)[..., None]
    card = np.clip(card * (1 - alpha) + warped * alpha, 0, 255).astype(np.uint8)

    # The hinge, pinned along the panel's bottom edge.
    cv2.line(
        card,
        (int(quad[0][0]), int(quad[0][1])),
        (int(quad[1][0]), int(quad[1][1])),
        OXIDE,
        4,
        cv2.LINE_AA,
    )

    # --- Lettering -------------------------------------------------------

    if not lettering:
        out.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out), card)
        return out

    face = cv2.FONT_HERSHEY_DUPLEX
    cv2.putText(card, "WinDuo", (74, 214), face, 3.4, CHALK, 6, cv2.LINE_AA)
    cv2.line(card, (78, 244), (214, 244), OXIDE, 5, cv2.LINE_AA)
    cv2.line(card, (214, 244), (498, 244), BLUE_LINE, 2, cv2.LINE_AA)

    for index, line in enumerate(
        ("The iPhone Duo fold effect,", "on any Windows laptop.")
    ):
        cv2.putText(
            card, line, (76, 306 + index * 46), face, 1.05, CHALK_SOFT, 2, cv2.LINE_AA
        )

    for index, line in enumerate(
        ("Apple has a hinge to read.", "Mac Duo has a lid sensor.", "WinDuo has your webcam.")
    ):
        colour = LINEN if index == 2 else CHALK_FAINT
        cv2.putText(
            card, line, (76, 424 + index * 40), face, 0.78, colour, 1, cv2.LINE_AA
        )

    cv2.putText(
        card, "winduo.baselashraf.com", (76, 572), face, 0.66, CHALK_FAINT, 1, cv2.LINE_AA
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), card)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("docs/og.png"))
    parser.add_argument(
        "--poster",
        action="store_true",
        help="draw the 16:10 video poster instead: same effect, no words on it",
    )
    options = parser.parse_args(argv)
    if options.poster:
        path = compose(options.out, lettering=False, size=(1600, 1000))
    else:
        path = compose(options.out)
    print(f"wrote {path} ({path.stat().st_size / 1000:.0f} kB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
