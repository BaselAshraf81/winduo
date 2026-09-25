#!/usr/bin/env bash
# Remove what install.sh added. Leaves system packages and your settings in
# ~/.config/winduo alone; delete that directory too for a clean slate.
set -euo pipefail

DATA="${XDG_DATA_HOME:-$HOME/.local/share}/winduo"
HYPR="${XDG_CONFIG_HOME:-$HOME/.config}/hypr"

pkill -f "python -m winduo" 2>/dev/null || true
rm -rf "$DATA"
rm -f "$HOME/.local/bin/winduo" "${XDG_DATA_HOME:-$HOME/.local/share}/applications/winduo.desktop"
for file in "$HYPR/autostart.lua" "$HYPR/hyprland.conf"; do
    [ -f "$file" ] || continue
    sed -i '/added by the WinDuo installer/d;/winduo/d' "$file"
done
echo "WinDuo removed."
