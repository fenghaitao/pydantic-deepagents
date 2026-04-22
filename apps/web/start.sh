#!/usr/bin/env bash
# Start the pydantic-deep web app.
# Requires the root venv to be set up first: make install
#
# Usage:  ./apps/web/start.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ── 1. Check root venv exists ─────────────────────────────────────────────────
if [ ! -f "${ROOT_DIR}/.venv/bin/python" ]; then
    echo "[error] Root venv not found. Run 'uv venv' from ${ROOT_DIR} first."
    exit 1
fi

# ── 2. Ensure Node dependencies are installed ─────────────────────────────────
if [ ! -d "${SCRIPT_DIR}/node_modules" ]; then
    echo "[setup] Installing Node dependencies..."
    npm --prefix "${SCRIPT_DIR}" install
fi

# ── 3. Find a free UI port (starting from 3000) ───────────────────────────────
UI_PORT=$(python3 - <<'EOF'
import socket
for p in range(3000, 3020):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("", p))
        s.close()
        print(p)
        break
    except OSError:
        continue
EOF
)
if [ -z "${UI_PORT}" ]; then
    echo "[error] No free port found in range 3000-3019."
    exit 1
fi
if [ "${UI_PORT}" != "3000" ]; then
    echo "[start] Port 3000 in use, using ${UI_PORT}"
fi

# ── 4. Start the app ──────────────────────────────────────────────────────────
echo "[start] Starting pydantic-deep web app on port ${UI_PORT}..."
export UI_PORT
exec npm --prefix "${SCRIPT_DIR}" run dev
