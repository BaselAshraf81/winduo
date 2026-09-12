# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

<!--
Two surfaces live in this repo:
- The desktop app (Windows, Python + PyQt6 + OpenGL). Not a web surface, but its
  windows are designed with the same tokens.
- The project site (GitHub Pages, static HTML/CSS). This is the `web` surface the
  Platform field names.
-->

## Stack

Delegated. Chosen and recorded here so later work does not reopen it.

**Desktop app:** Python 3.12, PyQt6 (`QOpenGLWidget` + GLSL 3.3), OpenCV, `windows-capture`
(Windows.Graphics.Capture) with `dxcam` (DXGI Desktop Duplication) and `mss` fallbacks, ctypes
against user32/kernel32/powrprof.

Chosen because five requirements have to coexist and this is the only stack where none of them
needs a hand-written native module: GPU-backed screen capture, a GLSL shader for the perspective
and blur pass, a click-through topmost overlay that excludes itself from capture via
`SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`, real-time computer vision on the webcam, and a
calibration wizard. Electron was rejected because it has no per-window capture exclusion, so the
overlay would be captured and fed back into itself. C#/.NET and C++ both work but cost
significantly more time at the same visual fidelity.

**Project site:** static HTML and CSS, no framework, no build step. Deployed to GitHub Pages from
`docs/`. A single page whose job is to explain the effect and hand over a download.

## Users

Primary: people with a Windows laptop who saw the iPhone Duo effect, or saw Mac Duo, and want it on
their own machine. They are not developers by default. They will download a release, run it, and
expect it to work without reading anything.

Secondary: developers who want the angle-estimation technique. The camera-as-hinge-sensor approach
is reusable, and the repository is laid out so `winduo/angle/` can be lifted out on its own.

Situation: a laptop on a desk or a lap, in an ordinary room, with ordinary lighting. Sometimes with
another app already holding the camera.

## Product Purpose

When the lid closes, the screen contents tilt away, blur, and dim, as though the picture were a
sheet of paper hinged at the bottom edge of the display that stays put in the room while the glass
rotates away from it.

Mac Duo does this by reading a hinge angle sensor over HID. Almost no laptop outside recent
MacBooks has that sensor. WinDuo estimates the same quantity from the webcam instead.

Success: the effect triggers when the user closes the lid and does not trigger when they do not.
Timing and smoothness matter far more than accuracy. A 3 degree bias is invisible; a 150 ms hitch
is not.

## Positioning

The lid angle is recovered from the webcam, so the effect runs on hardware that has no hinge
sensor. The camera is bolted into the lid, so lid rotation is pure camera pitch with no yaw and no
roll, and the image translates vertically by a predictable amount.

The rest position defines neutral. When the lid holds still long enough, that position becomes
zero, and the effect is driven by travel away from it. Nothing needs to know the true angle, so
integration drift never accumulates, and the app works at any lid position without knowing where
the hinge is.

## Operating Context

- Windows 10 version 2004 or later. `WDA_EXCLUDEFROMCAPTURE` requires it, and there is no
  workaround on older builds.
- Windows turns the display off on lid close, so the effect only ever plays during the closing
  travel. That is the interesting part of the motion anyway, and it means no power settings need
  changing.
- The camera privacy indicator lights while the app is armed. This is expected and disclosed, not
  hidden.
- Another application can hold the camera exclusively. The app degrades instead of failing.
- Calibration is a three-position wizard: normal viewing position, roughly halfway, closed.

## Capabilities and Constraints

Confirmed:

- Live screen capture of the primary display, rendered under perspective, blur, and dimming.
- A tray icon owns the app. There is no main window.
- Webcam angle estimation, with a scripted preview sweep so the effect can be seen and tuned
  without moving the lid.
- Settings persist as JSON under `%APPDATA%\WinDuo\`.
- A record and replay harness, so estimator changes are measured against recorded clips rather
  than by moving a real lid.

Constraints:

- Windows only. Linux needs a different capture and overlay path (PipeWire portal, wlroots
  layer-shell) and is documented as a contribution opportunity, not shipped.
- Primary display only.
- Motion blur in the camera destroys the features the correlator tracks, so exposure is forced
  short with high gain while armed. In low light this costs image quality, and below a usable
  threshold the estimator reports low confidence rather than guessing.
- Rotating the whole laptop looks identical to closing the lid from the camera's point of view.
  Roll and yaw components are used to reject it, imperfectly.
- The camera adds roughly 50 to 100 ms of latency, comparable to the 100 ms refresh of the sensor
  Mac Duo reads. Velocity extrapolation hides it.

Terminology:

- **Travel** is degrees of closing away from neutral. The quantity the effect is driven by.
- **Neutral** is the lid position most recently held still long enough to count as at rest.
- **Confidence** is the estimator's own assessment, 0 to 1. Low confidence blocks triggering.

## Brand Commitments

Name: WinDuo. Licensed Apache 2.0, matching Mac Duo, whose geometry, shader structure, and state
machine this project ports. Attribution to Makito and Mac Duo is required and permanent, in both
NOTICE and the project site.

## Evidence on Hand

- `mac-duo-ref/`, a shallow clone of sumimakito/Mac-Duo, read as the reference implementation.
  Apache 2.0.
- No users, no testimonials, no benchmarks, no press. None may be invented. The project site
  shows the effect and the mechanism, and claims nothing about adoption.
- No recorded demo video exists yet. The site must work without one and improve with one.

## Product Principles

1. **Timing over accuracy.** The angle drives a warp and a blur ramp, not a measurement. Ship
   smooth and correctly timed before precise.
2. **Relative, never absolute.** Neutral is wherever the lid last rested. Anything that needs to
   know the true angle is a mistake.
3. **Degrade, never guess.** No camera, no light, or no confidence means no effect. A wrong effect
   is worse than none.
4. **Disclose the camera.** The indicator light is explained in the interface, before it surprises
   anyone.
5. **The reference implementation is a source, not a target.** Mac Duo's math is ported honestly
   and credited; its platform assumptions are not.

## Accessibility & Inclusion

The effect is decorative and fully optional, off with one click from the tray. Settings windows
meet WCAG 2.2 AA for contrast and are fully keyboard operable. The project site works without
JavaScript, respects `prefers-reduced-motion`, and does not autoplay motion.
