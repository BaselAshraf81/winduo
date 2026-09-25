#!/usr/bin/env bash
# Install WinDuo on Omarchy (Arch + Hyprland).
#
#   curl -fsSL https://raw.githubusercontent.com/BaselAshraf81/winduo/main/packaging/omarchy/install.sh | bash
#   # or, from a checkout:
#   ./packaging/omarchy/install.sh
#
# What it does, all inside your home directory apart from the system packages:
#   1. installs the system packages WinDuo needs (Qt, OpenCV, grim) with pacman
#   2. creates a virtualenv in ~/.local/share/winduo/venv that reuses them
#   3. puts a `winduo` launcher in ~/.local/bin and a menu entry beside it
#   4. starts WinDuo with Hyprland, via Omarchy's autostart.lua when it exists
#      and an exec-once line in hyprland.conf otherwise
#
# Undo it all with packaging/omarchy/uninstall.sh.
set -euo pipefail

REPO="${WINDUO_REPO:-https://github.com/BaselAshraf81/winduo}"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/winduo"
BIN="$HOME/.local/bin"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
HYPR="${XDG_CONFIG_HOME:-$HOME/.config}/hypr"
MARKER="# added by the WinDuo installer"

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
die() { printf 'winduo: %s\n' "$*" >&2; exit 1; }

command -v pacman >/dev/null || die "this installer is for Arch-based systems such as Omarchy"
[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ] || say "Hyprland is not running; installing anyway"

packages=(python python-pyqt6 qt6-wayland python-opengl python-opencv python-numpy grim)
missing=()
for p in "${packages[@]}"; do pacman -Qq "$p" >/dev/null 2>&1 || missing+=("$p"); done
if [ ${#missing[@]} -gt 0 ]; then
    say "installing ${missing[*]}"
    if command -v omarchy-pkg-add >/dev/null; then
        omarchy-pkg-add "${missing[@]}"
    else
        sudo pacman -S --needed --noconfirm "${missing[@]}"
    fi
fi

# Source: this checkout when run from one, otherwise the repository.
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$here" ] && [ -f "$here/../../pyproject.toml" ]; then
    source_spec="$(cd "$here/../.." && pwd)"
else
    source_spec="git+$REPO"
fi

say "creating the environment in $DATA/venv"
mkdir -p "$DATA"
# System site packages, so the Arch builds of Qt and OpenCV are used rather
# than pip wheels that ship their own Qt without the Wayland plugin.
python -m venv --system-site-packages "$DATA/venv"
"$DATA/venv/bin/pip" install --quiet --upgrade pip
"$DATA/venv/bin/pip" install --quiet --no-deps "$source_spec"
"$DATA/venv/bin/python" -c "import PyQt6, OpenGL, cv2, numpy" \
    || die "a dependency failed to import; see the messages above"

say "adding the launcher and menu entry"
mkdir -p "$BIN" "$APPS"
cat >"$BIN/winduo" <<EOF
#!/usr/bin/env bash
exec "$DATA/venv/bin/python" -m winduo "\$@"
EOF
chmod +x "$BIN/winduo"
cat >"$APPS/winduo.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=WinDuo
Comment=Lean the screen back as the lid closes
Exec=$BIN/winduo --settings
Icon=video-display
Categories=Utility;
EOF

say "starting WinDuo with Hyprland"
if [ -f "$HYPR/autostart.lua" ]; then
    grep -q "winduo" "$HYPR/autostart.lua" \
        || printf '\n%s\no.launch_on_start("%s")\n' "-- ${MARKER#\# }" "$BIN/winduo" >>"$HYPR/autostart.lua"
elif [ -f "$HYPR/hyprland.conf" ]; then
    grep -q "winduo" "$HYPR/hyprland.conf" \
        || printf '\n%s\nexec-once = %s\n' "$MARKER" "$BIN/winduo" >>"$HYPR/hyprland.conf"
else
    say "no Hyprland config found; start $BIN/winduo yourself"
fi

say "done. Run 'winduo --preview' to see the effect, or 'winduo --calibrate' first."
case ":$PATH:" in *":$BIN:"*) ;; *) say "note: $BIN is not on your PATH" ;; esac
