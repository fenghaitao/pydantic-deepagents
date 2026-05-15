#!/usr/bin/env bash
# setup-scip-clang.sh — Obtain the scip-clang binary.
#
# Usage:
#   bash setup-scip-clang.sh            # download pre-built release (default)
#   bash setup-scip-clang.sh --build    # build from source (requires Bazel/npm)
#
# The binary is placed at:
#   code-graph-providers/scip-languages/bin/scip-clang
#
# To make CGC's scip_indexer.py find it without adding to PATH, set:
#   export SCIP_CLANG_BIN="<repo-root>/code-graph-providers/scip-languages/bin/scip-clang"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$SCRIPT_DIR/bin"
DEST="$BIN_DIR/scip-clang"

# ── Defaults ──────────────────────────────────────────────────────────────────
MODE="download"
VERSION="0.3.3"  # pinned — v0.4.0+ requires glibc not available on this machine

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --build)   MODE="build"; shift ;;
        -h|--help)
            sed -n '2,12p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

mkdir -p "$BIN_DIR"

# ── Helpers ───────────────────────────────────────────────────────────────────
info()  { echo "[setup-scip-clang] $*"; }
die()   { echo "[setup-scip-clang] ERROR: $*" >&2; exit 1; }

# ── Download mode (default) ───────────────────────────────────────────────────
if [[ "$MODE" == "download" ]]; then
    # Detect platform
    ARCH="$(uname -m)"
    OS="$(uname -s)"

    case "$OS-$ARCH" in
        Linux-x86_64)  ASSET="scip-clang-x86_64-linux" ;;
        Darwin-arm64)  ASSET="scip-clang-arm64-macos" ;;
        Darwin-x86_64) ASSET="scip-clang-x86_64-macos" ;;
        *)
            die "No pre-built release for $OS-$ARCH. Use --build to compile from source."
            ;;
    esac

    URL="https://github.com/sourcegraph/scip-clang/releases/download/v${VERSION}/${ASSET}"
    info "Downloading scip-clang v${VERSION} for ${OS}-${ARCH}..."
    info "  from: $URL"
    info "  to:   $DEST"

    if command -v curl &>/dev/null; then
        curl -fsSL --retry 3 -o "$DEST" "$URL"
    elif command -v wget &>/dev/null; then
        wget -q -O "$DEST" "$URL"
    else
        die "Neither 'curl' nor 'wget' found. Install one and retry."
    fi

    chmod +x "$DEST"
    info "Downloaded: $("$DEST" --version 2>&1 | head -1 || echo 'version check failed')"

# ── Build mode ────────────────────────────────────────────────────────────────
else
    SOURCE_DIR="$SCRIPT_DIR/scip-clang"

    if [[ ! -f "$SOURCE_DIR/WORKSPACE" ]]; then
        die "scip-clang submodule not initialized at $SOURCE_DIR." \
            $'\nRun: git submodule update --init code-graph-providers/scip-languages/scip-clang'
    fi

    info "Building scip-clang from source at $SOURCE_DIR ..."

    BUILD_SCRIPT="$SOURCE_DIR/build_with_llvm18.sh"
    [[ -f "$BUILD_SCRIPT" ]] || die "Build script not found: $BUILD_SCRIPT"

    # build_with_llvm18.sh installs to ~/.local/bin/scip-clang — run it directly.
    bash "$BUILD_SCRIPT"

    BUILT_BIN="$HOME/.local/bin/scip-clang"
    [[ -x "$BUILT_BIN" ]] || die "Build finished but binary not found at $BUILT_BIN"

    cp "$BUILT_BIN" "$DEST"
    chmod +x "$DEST"
    info "Built: $("$DEST" --version 2>&1 | head -1 || echo 'version check failed')"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
info ""
info "Binary ready at:"
info "  $DEST"
info ""
info "To use with CGC's scip_indexer, set:"
info "  export SCIP_CLANG_BIN=\"$DEST\""
info ""
info "Or add to PATH:"
info "  export PATH=\"$BIN_DIR:\$PATH\""
