#!/usr/bin/env bash
# install.sh — Installer/Uninstaller for Atomic Image Wizard
#
# ── One-liner install (no git required) ──────────────────────────────────────
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/cvcassdev/atomic-image-wizard/main/install.sh)
#
# ── Traditional install ───────────────────────────────────────────────────────
#
#   git clone https://github.com/cvcassdev/atomic-image-wizard
#   cd atomic-image-wizard
#   bash install.sh
#
# ── Uninstall ─────────────────────────────────────────────────────────────────
#
#   bash install.sh --uninstall
#
# ─────────────────────────────────────────────────────────────────────────────

set -e

REPO_RAW="https://raw.githubusercontent.com/cvcassdev/atomic-image-wizard/main"
BOOTC_DIR="$HOME/bootc"
SCRIPT_NAME="atomic_image_wizard.py"
ICON_NAME="atomic_image_wizard.svg"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
DESKTOP_FILE="$DESKTOP_DIR/atomic-image-wizard.desktop"
ICON_DEST="$ICON_DIR/atomic-image-wizard.svg"

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()    { echo -e "${CYAN}  →${NC} $*"; }
success() { echo -e "${GREEN}  ✓${NC} $*"; }
warn()    { echo -e "${YELLOW}  !${NC} $*"; }
error()   { echo -e "${RED}  ✗ ERROR:${NC} $*"; exit 1; }

# ── Find a Python with gi/GTK4 available ─────────────────────────────────────

find_python() {
    for py in /usr/bin/python3 /usr/bin/python3.* python3; do
        if "$py" -c 'import gi' 2>/dev/null; then
            echo "$py"
            return 0
        fi
    done
    return 1
}

PYTHON=$(find_python) || PYTHON=""

# ── Uninstall ─────────────────────────────────────────────────────────────────

if [[ "${1}" == "--uninstall" ]]; then
    echo ""
    echo -e "${RED}╔════════════════════════════════════════╗${NC}"
    echo -e "${RED}║    Atomic Image Wizard  Uninstaller    ║${NC}"
    echo -e "${RED}╚════════════════════════════════════════╝${NC}"
    echo ""

    if [[ -f "$DESKTOP_FILE" ]]; then
        rm "$DESKTOP_FILE"
        success "Removed desktop entry"
    else
        info "Desktop entry not found, skipping."
    fi

    if [[ -f "$ICON_DEST" ]]; then
        rm "$ICON_DEST"
        success "Removed icon"
    else
        info "Icon not found, skipping."
    fi

    if command -v update-desktop-database &>/dev/null; then
        update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
    fi
    if command -v gtk-update-icon-cache &>/dev/null; then
        gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
    fi

    echo ""
    if [[ -d "$BOOTC_DIR" ]]; then
        read -rp "  Remove ~/bootc/ and all its contents (including any saved Containerfiles)? [y/N] " confirm
        if [[ "${confirm,,}" == "y" ]]; then
            rm -rf "$BOOTC_DIR"
            success "Removed ~/bootc/"
        else
            info "Leaving ~/bootc/ intact."
        fi
    fi

    echo ""
    echo -e "${GREEN}  Uninstall complete.${NC}"
    echo "  Atomic Image Wizard has been removed from your app launcher."
    echo ""
    exit 0
fi

# ── Install ───────────────────────────────────────────────────────────────────

echo ""
echo -e "${CYAN}╔════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     Atomic Image Wizard  Installer     ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════╝${NC}"
echo ""

# ── Detect whether we were invoked via curl (no local files present) ──────────

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CURL_MODE=false

if [[ ! -f "$SOURCE_DIR/$SCRIPT_NAME" ]]; then
    CURL_MODE=true
    info "Running in download mode — fetching files from GitHub..."
    if ! command -v curl &>/dev/null; then
        error "curl is required for one-liner install but was not found."
    fi
fi

# ── Check dependencies ────────────────────────────────────────────────────────

info "Checking dependencies..."

if [[ -z "$PYTHON" ]]; then
    error "python3 is not installed. On Fedora Atomic it should always be present — something is wrong."
fi

_gtk_check_err=$("$PYTHON" -c '
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
' 2>&1)
if [[ $? -ne 0 ]]; then
    echo ""
    warn "PyGObject / GTK4 Python bindings not found."
    warn "Check error: $_gtk_check_err"
    warn "This is required for the GUI to run."
    echo ""
    echo "  To install, add the following to your Containerfile and rebuild:"
    echo ""
    echo "      RUN dnf install -y python3-gobject gtk4 && dnf clean all"
    echo ""
    echo "  Or to install temporarily on this session (not persistent on atomic):"
    echo ""
    echo "      rpm-ostree install python3-gobject gtk4"
    echo ""
    error "Missing dependency — install python3-gobject and gtk4 then re-run this installer."
fi

success "Dependencies OK (using $PYTHON)"

# ── Create ~/bootc/ ───────────────────────────────────────────────────────────

if [[ -d "$BOOTC_DIR" ]]; then
    info "~/bootc/ already exists, skipping creation."
else
    mkdir -p "$BOOTC_DIR"
    success "Created $BOOTC_DIR"
fi

# ── Fetch or copy files ───────────────────────────────────────────────────────

if [[ "$CURL_MODE" == true ]]; then
    # Download directly from GitHub into ~/bootc/
    info "Downloading $SCRIPT_NAME..."
    curl -fsSL "$REPO_RAW/$SCRIPT_NAME" -o "$BOOTC_DIR/$SCRIPT_NAME" \
        || error "Failed to download $SCRIPT_NAME"
    success "Downloaded $SCRIPT_NAME to ~/bootc/"

    info "Downloading $ICON_NAME..."
    curl -fsSL "$REPO_RAW/$ICON_NAME" -o "$BOOTC_DIR/$ICON_NAME" \
        || warn "Failed to download $ICON_NAME — launcher will use a fallback system icon."
    [[ -f "$BOOTC_DIR/$ICON_NAME" ]] && success "Downloaded $ICON_NAME to ~/bootc/"
else
    # Local install — copy from alongside install.sh
    if [[ "$SOURCE_DIR/$SCRIPT_NAME" != "$BOOTC_DIR/$SCRIPT_NAME" ]]; then
        cp "$SOURCE_DIR/$SCRIPT_NAME" "$BOOTC_DIR/$SCRIPT_NAME"
        success "Copied $SCRIPT_NAME to ~/bootc/"
    else
        info "$SCRIPT_NAME already in ~/bootc/"
    fi

    if [[ -f "$SOURCE_DIR/$ICON_NAME" ]]; then
        if [[ "$SOURCE_DIR/$ICON_NAME" != "$BOOTC_DIR/$ICON_NAME" ]]; then
            cp "$SOURCE_DIR/$ICON_NAME" "$BOOTC_DIR/$ICON_NAME"
            success "Copied $ICON_NAME to ~/bootc/"
        else
            info "$ICON_NAME already in ~/bootc/"
        fi
    else
        warn "$ICON_NAME not found — launcher will use a fallback system icon."
    fi
fi

# ── Make script executable ────────────────────────────────────────────────────

chmod +x "$BOOTC_DIR/$SCRIPT_NAME"
success "Made $SCRIPT_NAME executable"

# ── Install icon ──────────────────────────────────────────────────────────────

mkdir -p "$ICON_DIR"

if [[ -f "$BOOTC_DIR/$ICON_NAME" ]]; then
    cp "$BOOTC_DIR/$ICON_NAME" "$ICON_DEST"
    success "Icon installed to ~/.local/share/icons/"
    if command -v gtk-update-icon-cache &>/dev/null; then
        gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
    fi
    ICON_REF="$BOOTC_DIR/$ICON_NAME"
else
    ICON_REF="utilities-system"
    warn "Using fallback system icon."
fi

# ── Write .desktop file ───────────────────────────────────────────────────────

mkdir -p "$DESKTOP_DIR"

cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Atomic Image Wizard
GenericName=Container Image Builder
Comment=Build custom Fedora Atomic / bootc container images
Exec=$PYTHON $BOOTC_DIR/$SCRIPT_NAME
Icon=$ICON_REF
Terminal=false
Categories=System;Settings;
Keywords=fedora;atomic;bootc;container;ostree;image;
StartupNotify=true
EOF

chmod +x "$DESKTOP_FILE"
success "Desktop entry installed to ~/.local/share/applications/"

# ── Refresh desktop database ──────────────────────────────────────────────────

if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
fi

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           Installation complete!       ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
echo ""
echo "  Files installed to:  ~/bootc/"
echo "  Containerfiles will also be saved to ~/bootc/"
echo ""
echo "  Atomic Image Wizard should now appear in your app launcher."
echo "  If it doesn't show up immediately, try logging out and back in."
echo ""
echo "  To uninstall at any time run:  bash install.sh --uninstall"
echo ""
