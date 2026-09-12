"""The whole effect in one fragment shader.

Ported from ``DepthShaders.swift`` (Apache 2.0, Copyright 2026 Makito), with
Metal's implicit sRGB handling made explicit because a Qt default framebuffer is
not sRGB-capable.

Each screen pixel is mapped back into the picture through the inverse
perspective, then takes one sample from a mip pyramid at a level chosen by how
much blur belongs at that height. The picture already sits on a black margin, so
the two blur into each other and the picture's edge needs no special handling.

One sample per pixel, whatever the blur radius. A separable Gaussian at a
135-pixel radius would be hundreds of taps; picking a mip level is one.
"""

from __future__ import annotations

__all__ = ["VERTEX", "FRAGMENT"]

VERTEX = """
#version 330 core

// A single oversized triangle covering the viewport. Cheaper to set up than a
// quad and it needs no vertex buffer at all.
const vec2 CORNERS[3] = vec2[3](
    vec2(-1.0, -3.0),
    vec2(-1.0,  1.0),
    vec2( 3.0,  1.0)
);

void main() {
    gl_Position = vec4(CORNERS[gl_VertexID], 0.0, 1.0);
}
"""

FRAGMENT = """
#version 330 core

uniform sampler2D uPicture;

// Screen point to picture point. The inverse of the forward projection, because
// the shader walks destination pixels and needs to know where each came from.
uniform mat3 uScreenToPicture;

uniform vec2 uScreenSize;     // the display, in points
uniform vec2 uPaddedOrigin;   // top-left of the padded picture, in picture points
uniform vec2 uPaddedSize;     // the padded picture, in points

uniform float uMaxRadius;     // blur radius at full strength, in texture pixels
uniform float uBlurStrength;  // 0 to 1, from the closing travel
uniform float uBlurFloor;     // blur at the hinge edge, as a fraction of the far edge
uniform float uMaxLevel;      // highest mip level the texture has

uniform float uMaxDim;
uniform float uDimStrength;
uniform float uDimFloor;
uniform float uDimReach;

out vec4 fragColour;

// The picture is stored as sRGB and sampled to linear light, so the dimming has
// to be encoded back on the way out.
vec3 linearToSrgb(vec3 linear) {
    vec3 low = linear * 12.92;
    vec3 high = 1.055 * pow(max(linear, vec3(0.0)), vec3(1.0 / 2.4)) - 0.055;
    return mix(low, high, step(vec3(0.0031308), linear));
}

void main() {
    // gl_FragCoord already runs y-up from the bottom left, which is the same
    // convention the geometry uses. Metal needed a flip here; OpenGL does not.
    vec2 screenPoint = gl_FragCoord.xy;

    vec3 mapped = uScreenToPicture * vec3(screenPoint, 1.0);
    if (abs(mapped.z) < 1e-6) {
        fragColour = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }
    vec2 picturePoint = mapped.xy / mapped.z;

    vec2 unit = (picturePoint - uPaddedOrigin) / uPaddedSize;
    if (unit.x < 0.0 || unit.x > 1.0 || unit.y < 0.0 || unit.y > 1.0) {
        fragColour = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }
    // Texture row 0 is the top of the screen; picture y runs up.
    vec2 texCoord = vec2(unit.x, 1.0 - unit.y);

    // Height across the picture itself, 0 at the hinge edge and 1 at the far
    // edge. Not across the padded texture, so the margin does not shift it.
    float height = clamp(picturePoint.y / uScreenSize.y, 0.0, 1.0);

    float blur = uBlurStrength * (uBlurFloor + (1.0 - uBlurFloor) * height);
    float level = clamp(log2(max(blur * uMaxRadius, 1.0)), 0.0, uMaxLevel);

    vec3 colour = textureLod(uPicture, texCoord, level).rgb;

    // smoothstep rather than a clamped ratio, so the height where the dimming
    // reaches full strength leaves no visible seam across the picture.
    float spread = smoothstep(0.0, max(uDimReach, 0.02), height);
    float fade = uDimStrength * (uDimFloor + (1.0 - uDimFloor) * spread);
    colour *= pow(1.0 - uMaxDim * fade, 2.2);

    // Alpha 1 everywhere. The window is translucent so that the compositor
    // never treats the windows underneath as fully hidden, which would stop
    // them drawing and freeze the very picture being captured. Opaque pixels in
    // a translucent window give the same image without that side effect.
    fragColour = vec4(linearToSrgb(colour), 1.0);
}
"""
