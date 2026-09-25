# WinDuo for Windhawk

`winduo.wh.cpp` is the whole mod: one C++ file, as Windhawk requires. It is a
*tool mod*, so Windhawk runs it in a dedicated `windhawk.exe` process rather
than injecting it anywhere, and it hooks no functions.

It is a native port of the Python app's pipeline:

| Python | Here |
| --- | --- |
| OpenCV camera, DirectShow | Media Foundation source reader, RGB32 |
| 2D phase correlation (`tracker.py`) | correlation of high-passed row and column profiles |
| `estimator.py` | `Estimator` (same neutral re-zero, velocity fit, confidence blend) |
| `controller.py`, `geometry.py`, `gradient.py` | `Controller`, `BuildProfile`, the curve functions |
| dxcam | DXGI Desktop Duplication, copied on the GPU |
| Qt + OpenGL overlay | D3D11 swap chain on a DirectComposition visual |
| GLSL shader | the same shader in HLSL, compiled at startup |

There is no calibration wizard. The one number it would measure is the
*Degrees per pixel* setting, and the mod's readme explains how to tune it.

## Building and running it outside Windhawk

`harness/harness.cpp` supplies the few Windhawk API functions the mod calls
and includes the mod file unchanged:

```sh
cd windhawk/harness
g++ -std=c++23 -O2 -municode harness.cpp -o winduo-harness.exe \
    -ld3d11 -ldxgi -ldcomp -ld3dcompiler_47 -lmfplat -lmfreadwrite -lmf -lmfuuid -lole32 -luuid
./winduo-harness.exe --preview --seconds 8
```

Settings can be overridden as `Name=Value`, for example `TopLean=100`. With
`WINDUO_VISIBLE=1` set, the harness makes capture exclusion fail, so the mod
holds one frame and an ordinary screenshot can photograph the effect.

If your MinGW toolchain lives under a path with a space in it, the linker's
default manifest object will not be found; add
`-specs=nomanifest.specs`, where that file contains:

```
*endfile:
crtend.o%s
```

## Submitting

1. Fork [ramensoftware/windhawk-mods](https://github.com/ramensoftware/windhawk-mods).
2. Copy `winduo.wh.cpp` to `mods/winduo.wh.cpp`. The PR must contain only that file.
3. Open the PR from the account named in `@github`.
4. Comment `/ai-review`, address what it finds, then `/ready-for-reviewer`.

Bump `@version` for every update; the commit message becomes the changelog.
