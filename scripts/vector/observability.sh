#!/usr/bin/env bash
# setup-observability.sh
# Downloads and sets up Vector, VictoriaLogs, VictoriaMetrics, and Grafana Tempo
# as native binaries — no Docker required.
#
# Usage:
#   chmod +x setup-observability.sh
#   ./setup-observability.sh          # install + start all services
#   ./setup-observability.sh stop     # stop all running services
#   ./setup-observability.sh status   # show process status
#   ./setup-observability.sh logs     # tail all log files

set -euo pipefail

# ─── Versions (override via env vars if needed) ───────────────────────────────
VECTOR_VERSION="${VECTOR_VERSION:-0.43.0}"
VICTORIA_METRICS_VERSION="${VICTORIA_METRICS_VERSION:-1.101.0}"
# VictoriaLogs moved to its own repo at v1.x; set to "latest" to auto-resolve
VICTORIA_LOGS_VERSION="${VICTORIA_LOGS_VERSION:-1.50.0}"
TEMPO_VERSION="${TEMPO_VERSION:-2.4.1}"
GRAFANA_VERSION="${GRAFANA_VERSION:-12.0.0}"

# ─── Dirs ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$SCRIPT_DIR/bin"
DATA_DIR="$SCRIPT_DIR/data"
LOG_DIR="$SCRIPT_DIR/logs"
PID_DIR="$SCRIPT_DIR/pids"

mkdir -p "$BIN_DIR" "$DATA_DIR/metrics" "$DATA_DIR/vlogs" "$DATA_DIR/tempo/blocks" \
         "$DATA_DIR/tempo/wal" "$DATA_DIR/grafana" "$LOG_DIR" "$PID_DIR"

# ─── Platform detection ───────────────────────────────────────────────────────
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"   # linux | darwin
ARCH="$(uname -m)"                               # x86_64 | aarch64 | arm64

case "$ARCH" in
  x86_64)  ARCH_VM="amd64";  ARCH_VECTOR="x86_64" ;;
  aarch64) ARCH_VM="arm64";  ARCH_VECTOR="aarch64" ;;
  arm64)   ARCH_VM="arm64";  ARCH_VECTOR="aarch64" ;;
  *)       echo "Unsupported architecture: $ARCH"; exit 1 ;;
esac

# ─── Helpers ──────────────────────────────────────────────────────────────────
log()  { echo "[$(date '+%H:%M:%S')] $*"; }
ok()   { echo "[$(date '+%H:%M:%S')] ✓ $*"; }
skip() { echo "[$(date '+%H:%M:%S')] – $* (already present, skipping)"; }

download() {
  local url="$1" dest="$2"
  if [[ -f "$dest" ]]; then
    skip "$(basename "$dest")"
    return
  fi
  log "Downloading $(basename "$dest") ..."
  curl -fsSL "$url" -o "$dest"
  ok "Downloaded $(basename "$dest")"
}

extract_tar() {
  local archive="$1" binary_name="$2" dest="$3"
  log "Extracting $binary_name ..."
  tar -xzf "$archive" -C "$BIN_DIR" "$binary_name" 2>/dev/null \
    || tar -xzf "$archive" -C "$BIN_DIR" --wildcards "*/$binary_name" --strip-components=1 2>/dev/null \
    || tar -xzf "$archive" -C "$BIN_DIR"
  # Flatten: move any nested binary to BIN_DIR root
  find "$BIN_DIR" -name "$binary_name" -not -path "$BIN_DIR/$binary_name" -exec mv {} "$BIN_DIR/$binary_name" \; 2>/dev/null || true
  chmod +x "$dest"
  ok "$binary_name ready"
}

start_service() {
  local name="$1"
  local cmd="$2"
  local pidfile="$PID_DIR/$name.pid"
  local logfile="$LOG_DIR/$name.log"
  if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    ok "$name already running (pid $(cat "$pidfile"))"
    return
  fi
  log "Starting $name ..."
  # shellcheck disable=SC2086
  nohup $cmd >> "$logfile" 2>&1 &
  echo $! > "$pidfile"
  sleep 1
  if kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    ok "$name started (pid $(cat "$pidfile")) — logs: $logfile"
  else
    echo "ERROR: $name failed to start. Check $logfile"
    tail -20 "$logfile"
    exit 1
  fi
}

stop_service() {
  local name="$1"
  local pidfile="$PID_DIR/$name.pid"
  if [[ -f "$pidfile" ]]; then
    local pid
    pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      sleep 1
      # Force kill if still running
      kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
      rm -f "$pidfile"
      ok "Stopped $name (pid $pid)"
    else
      rm -f "$pidfile"
      log "$name was not running"
    fi
  else
    log "$name pidfile not found"
  fi
}

# ─── Commands ─────────────────────────────────────────────────────────────────
cmd_stop() {
  log "Stopping all services..."
  stop_service vector
  stop_service victoria-metrics
  stop_service victoria-logs
  stop_service tempo
  stop_service grafana
  ok "All services stopped"
}

cmd_status() {
  for name in vector victoria-metrics victoria-logs tempo grafana; do
    local pidfile="$PID_DIR/$name.pid"
    if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
      echo "  ● $name  running  (pid $(cat "$pidfile"))"
    else
      echo "  ○ $name  stopped"
    fi
  done
}

cmd_logs() {
  tail -f "$LOG_DIR"/*.log
}

cmd_install_and_start() {
  # ── 1. Vector ──────────────────────────────────────────────────────────────
  VECTOR_BIN="$BIN_DIR/vector"
  if [[ ! -f "$VECTOR_BIN" ]]; then
    if [[ "$OS" == "linux" ]]; then
      VECTOR_URL="https://packages.timber.io/vector/${VECTOR_VERSION}/vector-${VECTOR_VERSION}-${ARCH_VECTOR}-unknown-linux-musl.tar.gz"
    else
      VECTOR_URL="https://packages.timber.io/vector/${VECTOR_VERSION}/vector-${VECTOR_VERSION}-${ARCH_VECTOR}-apple-darwin.tar.gz"
    fi
    VECTOR_ARCHIVE="$BIN_DIR/vector.tar.gz"
    download "$VECTOR_URL" "$VECTOR_ARCHIVE"
    extract_tar "$VECTOR_ARCHIVE" "vector" "$VECTOR_BIN"
    rm -f "$VECTOR_ARCHIVE"
  else
    skip "vector binary"
  fi

  # ── 2. VictoriaMetrics ────────────────────────────────────────────────────
  VM_BIN="$BIN_DIR/victoria-metrics-prod"
  if [[ ! -f "$VM_BIN" ]]; then
    VM_URL="https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/v${VICTORIA_METRICS_VERSION}/victoria-metrics-${OS}-${ARCH_VM}-v${VICTORIA_METRICS_VERSION}.tar.gz"
    VM_ARCHIVE="$BIN_DIR/victoria-metrics.tar.gz"
    download "$VM_URL" "$VM_ARCHIVE"
    log "Extracting victoria-metrics-prod ..."
    tar -xzf "$VM_ARCHIVE" -C "$BIN_DIR"
    chmod +x "$VM_BIN"
    rm -f "$VM_ARCHIVE"
    ok "victoria-metrics-prod ready"
  else
    skip "victoria-metrics-prod binary"
  fi

  # ── 3. VictoriaLogs ───────────────────────────────────────────────────────
  # VictoriaLogs moved to its own repo (VictoriaMetrics/VictoriaLogs) at v1.x
  # Binary inside the archive is now named "victoria-logs" (no -prod suffix)
  VL_BIN="$BIN_DIR/victoria-logs"
  if [[ ! -f "$VL_BIN" ]]; then
    VL_URL="https://github.com/VictoriaMetrics/VictoriaLogs/releases/download/v${VICTORIA_LOGS_VERSION}/victoria-logs-${OS}-${ARCH_VM}-v${VICTORIA_LOGS_VERSION}.tar.gz"
    VL_ARCHIVE="$BIN_DIR/victoria-logs.tar.gz"
    download "$VL_URL" "$VL_ARCHIVE"
    log "Extracting victoria-logs ..."
    tar -xzf "$VL_ARCHIVE" -C "$BIN_DIR"
    # Binary may be named victoria-logs or victoria-logs-prod depending on version
    if [[ -f "$BIN_DIR/victoria-logs-prod" && ! -f "$BIN_DIR/victoria-logs" ]]; then
      mv "$BIN_DIR/victoria-logs-prod" "$VL_BIN"
    fi
    chmod +x "$VL_BIN"
    rm -f "$VL_ARCHIVE"
    ok "victoria-logs ready"
  else
    skip "victoria-logs binary"
  fi

  # ── 4. Tempo ──────────────────────────────────────────────────────────────
  TEMPO_BIN="$BIN_DIR/tempo"
  if [[ ! -f "$TEMPO_BIN" ]]; then
    if [[ "$OS" == "linux" ]]; then
      TEMPO_ARCH="$ARCH_VM"
    else
      TEMPO_ARCH="$ARCH_VM"
    fi
    TEMPO_URL="https://github.com/grafana/tempo/releases/download/v${TEMPO_VERSION}/tempo_${TEMPO_VERSION}_${OS}_${TEMPO_ARCH}.tar.gz"
    TEMPO_ARCHIVE="$BIN_DIR/tempo.tar.gz"
    download "$TEMPO_URL" "$TEMPO_ARCHIVE"
    extract_tar "$TEMPO_ARCHIVE" "tempo" "$TEMPO_BIN"
    rm -f "$TEMPO_ARCHIVE"
  else
    skip "tempo binary"
  fi

  # ── 5. Grafana ────────────────────────────────────────────────────────────
  GRAFANA_DIR="$BIN_DIR/grafana"
  GRAFANA_BIN="$GRAFANA_DIR/bin/grafana"
  if [[ ! -f "$GRAFANA_BIN" ]]; then
    if [[ "$OS" == "linux" ]]; then
      GRAFANA_URL="https://dl.grafana.com/oss/release/grafana-${GRAFANA_VERSION}.linux-${ARCH_VM}.tar.gz"
    else
      GRAFANA_URL="https://dl.grafana.com/oss/release/grafana-${GRAFANA_VERSION}.darwin-${ARCH_VM}.tar.gz"
    fi
    GRAFANA_ARCHIVE="$BIN_DIR/grafana.tar.gz"
    download "$GRAFANA_URL" "$GRAFANA_ARCHIVE"
    log "Extracting grafana ..."
    tar -xzf "$GRAFANA_ARCHIVE" -C "$BIN_DIR"
    # Rename versioned dir to plain "grafana"
    find "$BIN_DIR" -maxdepth 1 -name "grafana-*" -type d -exec mv {} "$GRAFANA_DIR" \; 2>/dev/null || true
    rm -f "$GRAFANA_ARCHIVE"
    ok "grafana ready"
  else
    skip "grafana binary"
  fi

  # Copy provisioning config into Grafana's expected location
  cp "$SCRIPT_DIR/grafana/provisioning/datasources/datasources.yaml" \
     "$GRAFANA_DIR/conf/provisioning/datasources/datasources.yaml"

  # ── 6. Start services ─────────────────────────────────────────────────────
  echo ""
  log "Starting services..."

  start_service "victoria-metrics" \
    "$VM_BIN -storageDataPath=$DATA_DIR/metrics -retentionPeriod=30d -httpListenAddr=0.0.0.0:8428"

  start_service "victoria-logs" \
    "$VL_BIN -storageDataPath=$DATA_DIR/vlogs -retentionPeriod=7d -httpListenAddr=0.0.0.0:9428"

  start_service "tempo" \
    "$TEMPO_BIN -config.file=$SCRIPT_DIR/tempo.yaml"

  # Give Tempo a moment before Vector tries to connect
  sleep 2

  start_service "vector" \
    "$VECTOR_BIN --config $SCRIPT_DIR/observability.yaml"

  start_service "grafana" \
    "$GRAFANA_BIN server \
      --homepath=$GRAFANA_DIR \
      --config=$GRAFANA_DIR/conf/defaults.ini \
      cfg:default.paths.data=$DATA_DIR/grafana \
      cfg:default.paths.logs=$LOG_DIR \
      cfg:default.paths.provisioning=$SCRIPT_DIR/grafana/provisioning \
      cfg:default.server.http_port=3000 \
      cfg:default.security.admin_password=admin \
      cfg:default.auth.anonymous.enabled=true \
      cfg:default.auth.anonymous.org_role=Viewer"

  # ── 7. Summary ────────────────────────────────────────────────────────────
  echo ""
  echo "┌─────────────────────────────────────────────────────────────┐"
  echo "│  Observability stack is up                                │"
  echo "├────────────────────────────┬──────────────────────────────┤"
  echo "│  Grafana UI                │  http://localhost:3000       │"
  echo "│    admin / admin           │                              │"
  echo "├────────────────────────────┼──────────────────────────────┤"
  echo "│  Send logs (HTTP)          │  http://localhost:9880       │"
  echo "│  Send traces (OTLP gRPC)   │  localhost:4317              │"
  echo "│  Send traces (OTLP HTTP)   │  http://localhost:4318       │"
  echo "│  Send metrics (OTLP HTTP)  │  http://localhost:8428/      │"
  echo "│                            │    opentelemetry/v1/metrics  │"
  echo "├────────────────────────────┼──────────────────────────────┤"
  echo "│  LogQL API                 │  http://localhost:9428       │"
  echo "│  PromQL API                │  http://localhost:8428       │"
  echo "│  TraceQL API               │  http://localhost:3200       │"
  echo "│  Vector API                │  http://localhost:8686       │"
  echo "└────────────────────────────┴──────────────────────────────┘"
  echo ""
  echo "Run the agent:"
  echo "  cd pydantic-deepagents"
  echo "  VICTORIA_LOGS_URL=http://localhost:9428 \\"
  echo "  VICTORIA_METRICS_URL=http://localhost:8428 \\"
  echo "  VICTORIA_TRACES_URL=http://localhost:3200 \\"
  echo "  python examples/observability_agent.py"
  echo ""
  echo "Stop:   $0 stop"
  echo "Status: $0 status"
  echo "Logs:   $0 logs"
}

# ─── Dispatch ─────────────────────────────────────────────────────────────────
case "${1:-start}" in
  stop)   cmd_stop ;;
  status) cmd_status ;;
  logs)   cmd_logs ;;
  start)  cmd_install_and_start ;;
  *)      echo "Usage: $0 [start|stop|status|logs]"; exit 1 ;;
esac
