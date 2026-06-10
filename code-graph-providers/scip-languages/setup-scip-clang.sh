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
VERSION="v0.1.0"

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
    TARBALL="$SCRIPT_DIR/scip-clang.zip"
    DEST="$BIN_DIR/scip-clang"

    [[ -f "$TARBALL" ]] && { info "Removing existing tarball: $TARBALL"; rm -f "$TARBALL"; }
    [[ -f "$DEST"    ]] && { info "Removing existing binary:  $DEST";    rm -f "$DEST";    }

    info "Downloading scip-clang v${VERSION}..."
    info "  to:   $TARBALL"

   if command -v gh &>/dev/null; then
        gh release download $VERSION --repo intel-sandbox/scip-clang --pattern 'scip-clang.zip' --output "$TARBALL"
    elif command -v curl &>/dev/null && command -v wget &>/dev/null; then
        [[ -n "${GITHUB_TOKEN:-}" ]] || die "GITHUB_TOKEN must be set for curl/wget download."
        ASSET_ID=$(curl -fsSL \
            -H "Authorization: token $GITHUB_TOKEN" \
            -H "Accept: application/vnd.github+json" \
            "https://api.github.com/repos/intel-sandbox/scip-clang/releases/tags/${VERSION}" \
            | jq '.assets[] | select(.name=="scip-clang.zip") | .id')
        [[ -n "$ASSET_ID" ]] || die "Failed to resolve asset ID for scip-clang.zip"
        wget -q \
            --header="Authorization: token $GITHUB_TOKEN" \
            --header="Accept: application/octet-stream" \
            -O "$TARBALL" \
            "https://api.github.com/repos/intel-sandbox/scip-clang/releases/assets/$ASSET_ID"
    else
        die "Need 'gh' or both 'curl' and 'wget' to download. Install one and retry."
    fi

    unzip -q "$TARBALL" -d "$BIN_DIR"
    chmod +x "$DEST"

    [[ -x "$DEST" ]] || die "Expected binary not found at $DEST after extraction."
    info "Extracted: $("$DEST" --version 2>&1 | head -1 || echo 'version check failed')"

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
