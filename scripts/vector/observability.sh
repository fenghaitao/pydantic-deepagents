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
TEMPO_VERSION="${TEMPO_VERSION:-2.7.1}"
GRAFANA_VERSION="${GRAFANA_VERSION:-12.0.0}"

# ─── Dirs ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$SCRIPT_DIR/bin"
export DATA_DIR="$SCRIPT_DIR/data"
LOG_DIR="$SCRIPT_DIR/logs"
PID_DIR="$SCRIPT_DIR/pids"

mkdir -p "$BIN_DIR" "$DATA_DIR/metrics" "$DATA_DIR/vlogs" "$DATA_DIR/tempo/blocks" \
         "$DATA_DIR/tempo/wal" "$DATA_DIR/grafana" "$LOG_DIR" "$PID_DIR"

# ─── Repo root (two levels up from scripts/vector/) ──────────────────────────
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ─── Default ports (overridden by Discovery Server when running) ──────────────
VECTOR_INGEST_PORT="${VECTOR_INGEST_PORT:-9880}"
VECTOR_API_PORT="${VECTOR_API_PORT:-8686}"
VECTOR_OTLP_HTTP_PORT="${VECTOR_OTLP_HTTP_PORT:-4328}"
VICTORIA_METRICS_PORT="${VICTORIA_METRICS_PORT:-8428}"
VICTORIA_LOGS_PORT="${VICTORIA_LOGS_PORT:-9428}"
TEMPO_HTTP_PORT="${TEMPO_HTTP_PORT:-3200}"
TEMPO_OTLP_GRPC_PORT="${TEMPO_OTLP_GRPC_PORT:-4317}"
TEMPO_OTLP_HTTP_PORT="${TEMPO_OTLP_HTTP_PORT:-4318}"
TEMPO_INTERNAL_GRPC_PORT="${TEMPO_INTERNAL_GRPC_PORT:-9095}"
GRAFANA_PORT="${GRAFANA_PORT:-3100}"

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

# ─── Port resolution from top-level port allocator ───────────────────────────
# Calls alloc_ports.py which uses ports_allocator.PortManager to atomically
# allocate free TCP ports and persist them in ~/.ports-allocator/.
# The call is idempotent: re-running returns the same ports.
load_ports_from_discovery() {
  local ports_env
  # Use the project venv Python so ports_allocator (a venv dependency) is importable.
  local PYTHON
  PYTHON="${REPO_ROOT}/.venv/bin/python"
  [[ -x "$PYTHON" ]] || PYTHON=python3
  ports_env=$(REPO_ROOT="$REPO_ROOT" "$PYTHON" "$SCRIPT_DIR/alloc_ports.py" alloc 2>/dev/null)

  if [[ -n "$ports_env" ]]; then
    while IFS='=' read -r var val; do
      [[ -n "$var" ]] && export "$var=$val"
    done <<< "$ports_env"
    log "Ports allocated (session: ~/.ports-allocator/)"
  else
    log "Port allocation failed — using default ports"
  fi

  # Export URL vars so Vector (which reads its config env at startup)
  # sees the correct dynamically allocated ports.
  # Use the short hostname for external-facing URLs (cross-node access).
  local BACKEND_HOST
  BACKEND_HOST=$(hostname -s 2>/dev/null || hostname | cut -d. -f1)

  export VICTORIA_LOGS_URL="http://$BACKEND_HOST:$VICTORIA_LOGS_PORT"
  export VICTORIA_METRICS_URL="http://$BACKEND_HOST:$VICTORIA_METRICS_PORT"
  export VICTORIA_TRACES_URL="http://$BACKEND_HOST:$TEMPO_HTTP_PORT"
  export VECTOR_API_URL="http://$BACKEND_HOST:$VECTOR_API_PORT"
  export VECTOR_OTLP_ENDPOINT="http://$BACKEND_HOST:$VECTOR_OTLP_HTTP_PORT"
  export VECTOR_INGEST_URL="http://$BACKEND_HOST:$VECTOR_INGEST_PORT"
  # Localhost variants for services talking to each other on the same machine.
  export VICTORIA_LOGS_SINK_URL="http://localhost:$VICTORIA_LOGS_PORT"
  # Localhost OTLP endpoint for the CLI when it runs on the same machine as Tempo.
  export TEMPO_OTLP_LOCAL="http://localhost:$TEMPO_OTLP_HTTP_PORT"
  # Localhost log ingest endpoint for the CLI when it runs on the same machine as Vector.
  export VECTOR_INGEST_LOCAL="http://localhost:$VECTOR_INGEST_PORT"
}

download() {
  local url="$1" dest="$2"
  if [[ -f "$dest" ]]; then
    skip "$(basename "$dest")"
    return
  fi
  log "Downloading $(basename "$dest") ..."
  curl -fsSL --retry 5 --retry-delay 5 --retry-all-errors "$url" -o "$dest"
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
  # Release the port session so the next start allocates fresh ports.
  local PYTHON="${REPO_ROOT}/.venv/bin/python"
  [[ -x "$PYTHON" ]] || PYTHON=python3
  REPO_ROOT="$REPO_ROOT" "$PYTHON" "$SCRIPT_DIR/alloc_ports.py" free 2>/dev/null || true
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
      VECTOR_URL="https://github.com/vectordotdev/vector/releases/download/v${VECTOR_VERSION}/vector-${VECTOR_VERSION}-${ARCH_VECTOR}-unknown-linux-musl.tar.gz"
    else
      VECTOR_URL="https://github.com/vectordotdev/vector/releases/download/v${VECTOR_VERSION}/vector-${VECTOR_VERSION}-${ARCH_VECTOR}-apple-darwin.tar.gz"
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

  # ── 6. Start services ─────────────────────────────────────────────────────
  echo ""
  log "Starting services..."

  # Resolve ports from Discovery Server (or keep defaults set at top of script).
  load_ports_from_discovery

  # Generate Grafana datasource config with actual ports substituted.
  # Written into PID_DIR/provisioning so Grafana is pointed at the rendered copy,
  # not the template file (which contains literal ${VAR} placeholders).
  GRAFANA_PROV_DIR="$PID_DIR/provisioning"
  mkdir -p "$GRAFANA_PROV_DIR/datasources"
  envsubst '${TEMPO_HTTP_PORT} ${VICTORIA_METRICS_PORT} ${VICTORIA_LOGS_PORT}' \
    < "$SCRIPT_DIR/grafana/provisioning/datasources/datasources.yaml" \
    > "$GRAFANA_PROV_DIR/datasources/datasources.yaml"
  # Copy static provisioning dirs (dashboards etc.) into the same tree.
  for d in "$SCRIPT_DIR/grafana/provisioning"/*/; do
    name="$(basename "$d")"
    [[ "$name" == "datasources" ]] && continue
    cp -r "$d" "$GRAFANA_PROV_DIR/$name"
  done

  start_service "victoria-metrics" \
    "$VM_BIN -storageDataPath=$DATA_DIR/metrics -retentionPeriod=30d -httpListenAddr=0.0.0.0:$VICTORIA_METRICS_PORT"

  start_service "victoria-logs" \
    "$VL_BIN -storageDataPath=$DATA_DIR/vlogs -retentionPeriod=7d -httpListenAddr=0.0.0.0:$VICTORIA_LOGS_PORT"

  # Render tempo.yaml with actual port values (Tempo doesn't support env-var substitution).
  TEMPO_RENDERED="$PID_DIR/tempo-rendered.yaml"
  envsubst '${TEMPO_HTTP_PORT} ${TEMPO_INTERNAL_GRPC_PORT} ${TEMPO_OTLP_GRPC_PORT} ${TEMPO_OTLP_HTTP_PORT} ${VICTORIA_METRICS_PORT} ${DATA_DIR}' \
    < "$SCRIPT_DIR/tempo.yaml" > "$TEMPO_RENDERED"

  start_service "tempo" \
    "$TEMPO_BIN -config.file=$TEMPO_RENDERED"

  # Give Tempo a moment before Vector tries to connect
  sleep 2

  # Render observability.yaml with actual port values (avoids Vector env-var expansion issues).
  VECTOR_RENDERED="$PID_DIR/observability-rendered.yaml"
  envsubst '${VECTOR_INGEST_PORT} ${VECTOR_API_PORT} ${VECTOR_OTLP_HTTP_PORT} ${TEMPO_OTLP_HTTP_PORT} ${VICTORIA_LOGS_SINK_URL}' \
    < "$SCRIPT_DIR/observability.yaml" > "$VECTOR_RENDERED"

  start_service "vector" \
    "$VECTOR_BIN --config $VECTOR_RENDERED"

  # Install native VictoriaLogs datasource plugin (avoids Loki compat /index/volume errors).
  VLOGS_PLUGIN_DIR="$DATA_DIR/grafana/plugins/victoriametrics-logs-datasource"
  if [[ ! -d "$VLOGS_PLUGIN_DIR" ]]; then
    log "Installing VictoriaLogs Grafana plugin..."
    GF_PATHS_DATA="$DATA_DIR/grafana" "$GRAFANA_BIN" cli \
      --pluginsDir "$DATA_DIR/grafana/plugins" \
      --homepath "$GRAFANA_DIR" \
      plugins install victoriametrics-logs-datasource 2>/dev/null || true
  fi

  start_service "grafana" \
    "$GRAFANA_BIN server \
      --homepath=$GRAFANA_DIR \
      cfg:paths.data=$DATA_DIR/grafana \
      cfg:paths.logs=$LOG_DIR \
      cfg:paths.plugins=$DATA_DIR/grafana/plugins \
      cfg:paths.provisioning=$GRAFANA_PROV_DIR \
      cfg:server.http_port=$GRAFANA_PORT \
      cfg:security.admin_password=admin \
      cfg:auth.anonymous.enabled=true \
      cfg:auth.anonymous.org_role=Viewer \
      cfg:plugins.allow_loading_unsigned_plugins=victoriametrics-logs-datasource"

  # ── 7. Summary ────────────────────────────────────────────────────────────
  echo ""
  echo "┌──────────────────────────────────────────────────────────────────────────┐"
  echo "│  Observability stack is up                                               │"
  echo "├────────────────────────────┬─────────────────────────────────────────────┤"
  printf "│  %-26s  │  http://localhost:%-23s  │\n" "Grafana UI" "$GRAFANA_PORT"
  echo "│    admin / admin           │                                             │"
  echo "├────────────────────────────┼─────────────────────────────────────────────┤"
  printf "│  %-26s  │  http://localhost:%-23s  │\n" "Send logs (HTTP)" "$VECTOR_INGEST_PORT"
  printf "│  %-26s  │  localhost:%-29s  │\n" "Send traces (OTLP gRPC)" "$TEMPO_OTLP_GRPC_PORT"
  printf "│  %-26s  │  http://localhost:%-23s  │\n" "Send traces (OTLP HTTP)" "$TEMPO_OTLP_HTTP_PORT"
  printf "│  %-26s  │  http://localhost:%-23s  │\n" "Send metrics (OTLP HTTP)" "$VICTORIA_METRICS_PORT"
  echo "├────────────────────────────┼─────────────────────────────────────────────┤"
  printf "│  %-26s  │  http://localhost:%-23s  │\n" "LogQL API" "$VICTORIA_LOGS_PORT"
  printf "│  %-26s  │  http://localhost:%-23s  │\n" "PromQL API" "$VICTORIA_METRICS_PORT"
  printf "│  %-26s  │  http://localhost:%-23s  │\n" "TraceQL API" "$TEMPO_HTTP_PORT"
  printf "│  %-26s  │  http://localhost:%-23s  │\n" "Vector API" "$VECTOR_API_PORT"
  echo "└────────────────────────────┴─────────────────────────────────────────────┘"
  echo ""
  echo "Ports stored in: ~/.ports-allocator/"
  echo ""
  echo "Run the agent:"
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
