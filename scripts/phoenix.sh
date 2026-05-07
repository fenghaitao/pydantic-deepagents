#!/usr/bin/env bash
# scripts/phoenix.sh — Start/stop/health-check the Arize Phoenix tracing server
# at the pydantic-deepagents level (independent of the potpie backend).
#
# Phoenix is a general-purpose LLM observability server used by pydantic-deep's
# --phoenix flag; it does not belong exclusively to potpie.
#
# Usage:
#   bash scripts/phoenix.sh start    # Allocate ports, start phoenix, export vars
#   bash scripts/phoenix.sh stop     # Stop phoenix process
#   bash scripts/phoenix.sh health [RETRIES]  # Check phoenix HTTP health
#
# Port allocation uses scripts/vector/alloc_ports.py (obs.phoenix / obs.phoenix_grpc),
# the same PortManager session as the observability stack.
#
# In CI (GitHub Actions), PHOENIX_PORT and PHOENIX_GRPC_PORT are written to
# GITHUB_ENV so subsequent steps can use them as environment variables.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PID_DIR="${SCRIPT_DIR}/vector/pids"
LOG_DIR="${SCRIPT_DIR}/vector/logs"
PID_FILE="${PID_DIR}/phoenix.pid"

mkdir -p "${PID_DIR}" "${LOG_DIR}"

PYTHON="${REPO_ROOT}/.venv/bin/python"
PHOENIX_BIN="${REPO_ROOT}/.venv/bin/phoenix"

_alloc_ports() {
  eval "$("${PYTHON}" "${SCRIPT_DIR}/vector/alloc_ports.py" alloc)"
}

_get_phoenix_port() {
  "${PYTHON}" "${SCRIPT_DIR}/vector/alloc_ports.py" print 2>/dev/null \
    | grep '^PHOENIX_PORT=' | cut -d= -f2
}

case "${1:-start}" in
  start)
    _alloc_ports

    PHOENIX_PORT="${PHOENIX_PORT:-6006}"
    PHOENIX_GRPC_PORT="${PHOENIX_GRPC_PORT:-4317}"
    # Per-user working dir avoids collisions on shared machines.
    PHOENIX_WORKING_DIR="/tmp/.arize-phoenix-$(id -un)"

    echo "[phoenix] Starting on port ${PHOENIX_PORT} (gRPC: ${PHOENIX_GRPC_PORT})"
    mkdir -p "${PHOENIX_WORKING_DIR}"

    PHOENIX_PORT="${PHOENIX_PORT}" \
    PHOENIX_GRPC_PORT="${PHOENIX_GRPC_PORT}" \
    PHOENIX_WORKING_DIR="${PHOENIX_WORKING_DIR}" \
      "${PHOENIX_BIN}" serve \
        > "${LOG_DIR}/phoenix.log" 2>&1 &

    echo $! > "${PID_FILE}"
    echo "[phoenix] PID $(cat "${PID_FILE}") — logs: ${LOG_DIR}/phoenix.log"

    # Export to GITHUB_ENV so subsequent CI steps can read these as env vars.
    if [[ -n "${GITHUB_ENV:-}" ]]; then
      echo "PHOENIX_PORT=${PHOENIX_PORT}" >> "${GITHUB_ENV}"
      echo "PHOENIX_GRPC_PORT=${PHOENIX_GRPC_PORT}" >> "${GITHUB_ENV}"
    fi

    # Print for eval usage in non-CI contexts.
    echo "export PHOENIX_PORT=${PHOENIX_PORT}"
    echo "export PHOENIX_GRPC_PORT=${PHOENIX_GRPC_PORT}"
    ;;

  stop)
    if [[ -f "${PID_FILE}" ]]; then
      PID=$(cat "${PID_FILE}")
      if kill "${PID}" 2>/dev/null; then
        echo "[phoenix] Stopped (pid ${PID})"
      else
        echo "[phoenix] PID ${PID} was already gone"
      fi
      rm -f "${PID_FILE}"
    else
      pkill -f "${PHOENIX_BIN} serve" 2>/dev/null && echo "[phoenix] Killed orphaned process" || true
    fi
    ;;

  health)
    RETRIES="${2:-10}"
    PORT="$(_get_phoenix_port)"
    if [[ -z "${PORT}" ]]; then
      echo "[phoenix] health: no port allocated — run 'scripts/phoenix.sh start' first"
      exit 1
    fi
    for i in $(seq 1 "${RETRIES}"); do
      if curl -sf "http://127.0.0.1:${PORT}/" >/dev/null 2>&1; then
        echo "[phoenix] healthy on port ${PORT}"
        exit 0
      fi
      echo "[phoenix] not ready yet (attempt ${i}/${RETRIES}) — waiting 3s..."
      [[ "${i}" -lt "${RETRIES}" ]] && sleep 3
    done
    echo "[phoenix] unhealthy on port ${PORT} after ${RETRIES} attempts"
    exit 1
    ;;

  *)
    echo "Usage: $0 start | stop | health [RETRIES]" >&2
    exit 1
    ;;
esac
