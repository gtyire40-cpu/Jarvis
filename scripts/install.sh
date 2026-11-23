#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
INSTALL_DIR="${JARVIS_INSTALL_DIR:-$HOME/.local/share/jarvis}"
BIN_DIR="${JARVIS_BIN_DIR:-$HOME/.local/bin}"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"
mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$ICON_DIR"
rsync -a --delete --exclude '.venv/' --exclude '__pycache__/' --exclude '*.pyc' --exclude '.env' --exclude 'tests/' "$PROJECT_DIR/" "$INSTALL_DIR/"
cat > "$BIN_DIR/jarvis" <<EOF
#!/usr/bin/env bash
exec "$INSTALL_DIR/executable_x86_64/jarvis-local.x86_64" "\$@"
EOF
chmod +x "$BIN_DIR/jarvis"
cp "$PROJECT_DIR/resources/assets/jarvis.svg" "$ICON_DIR/jarvis.svg"
cat > "$DESKTOP_DIR/jarvis.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Jarvis Local
Comment=Asistente local de IA para Linux
Exec=$BIN_DIR/jarvis
Icon=jarvis
Terminal=false
Categories=Utility;ArtificialIntelligence;
StartupNotify=true
EOF
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
echo "Jarvis Local instalado en $INSTALL_DIR"
echo "Lanzador: $BIN_DIR/jarvis"
