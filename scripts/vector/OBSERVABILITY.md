# Observability Stack

Local observability pipeline for pydantic-deep — no Docker required.

## Services

Ports are **dynamically allocated** by `ports_allocator` at startup — no fixed ports.
See [Discover Active Ports](#discover-active-ports) below to find the current assignments.

| Service | Role | Port variable |
|---|---|---|
| **Vector** | Log router (HTTP → VictoriaLogs) | `$VECTOR_INGEST_PORT` (ingest), `$VECTOR_API_PORT` (API) |
| **VictoriaMetrics** | Metrics storage, PromQL API | `$VICTORIA_METRICS_PORT` |
| **VictoriaLogs** | Log storage, LogQL API | `$VICTORIA_LOGS_PORT` |
| **Tempo** | Trace storage, TraceQL API | `$TEMPO_HTTP_PORT` (query), `$TEMPO_OTLP_GRPC_PORT` gRPC, `$TEMPO_OTLP_HTTP_PORT` HTTP |
| **Grafana** | Dashboards UI | `$GRAFANA_PORT` |

## Usage

```bash
# Start all services
bash scripts/vector/observability.sh start

# Stop all services
bash scripts/vector/observability.sh stop

# Check status
bash scripts/vector/observability.sh status

# Tail all logs
bash scripts/vector/observability.sh logs
```

## Discover Active Ports

After `make backend-start`, load current port assignments into your shell:

```bash
# Print all active port assignments
.venv/bin/python scripts/vector/alloc_ports.py print

# Load them as shell variables (use in subsequent commands below)
eval $(.venv/bin/python scripts/vector/alloc_ports.py print)
```

Or inspect the discovery file directly:

```bash
grep -A2 '"obs\.' ~/.ports-allocator/*.discovery | grep allocated_port
```

Ports persist across restarts of `observability.sh` — they only change after
`make backend-stop` (which calls `alloc_ports.py free`) followed by `make backend-start`.

## Sending Data

> Run `eval $(.venv/bin/python scripts/vector/alloc_ports.py print)` first to set the port variables.

| Signal | Endpoint | Notes |
|---|---|---|
| Logs (HTTP JSON) | `http://localhost:$VECTOR_INGEST_PORT` | Routed via Vector → VictoriaLogs |
| Traces (OTLP HTTP) | `http://localhost:$TEMPO_OTLP_HTTP_PORT/v1/traces` | Direct to Tempo |
| Traces (OTLP gRPC) | `localhost:$TEMPO_OTLP_GRPC_PORT` | Direct to Tempo |
| Metrics (OTLP HTTP) | `http://localhost:$VICTORIA_METRICS_PORT/opentelemetry/v1/metrics` | Direct to VictoriaMetrics |

## pydantic-deep Integration

Enable Vector tracing with the `--vector` flag or config:

```bash
# One-shot
pydantic-deep --vector run "Hello"

# Permanent (config.toml)
pydantic-deep config set vector true
```

Environment variables (optional overrides — auto-discovered via `ports_allocator` when not set):

| Variable | Description |
|---|---|
| `TEMPO_OTLP_LOCAL` | OTLP traces endpoint (localhost, avoids proxy) |
| `VECTOR_INGEST_LOCAL` | Log ingest endpoint (localhost) |
| `OTEL_SERVICE_NAME` | Service name in traces (default: `pydantic-deep`) |

The `--vector` flag uses logfire with `send_to_logfire=False` and sets:
- `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` → Vector/Tempo
- `OTEL_METRICS_EXPORTER=none` (suppresses metrics 404s)

## Grafana Verification

After `pydantic-deep --vector run "hello"`, find the Grafana URL:

```bash
eval $(.venv/bin/python scripts/vector/alloc_ports.py print)
echo "http://$(hostname -s):$GRAFANA_PORT"
```

### Traces

1. **Explore** (compass icon) → select **Tempo** datasource
2. Switch to the **TraceQL** tab
3. Enter the query and click **Run query**:
   ```
   { .service.name = "pydantic-deep" }
   ```
4. Traces appear in the table; click any row to open the span waterfall

> The **Search** tab also works but requires clicking **Run query** — it shows nothing without an explicit query run.

### Logs

1. **Explore** → select **VictoriaLogs** datasource
2. Enter the query and click **Run query**:
   ```
   {service="pydantic-deep"}
   ```
3. Log lines appear below the query bar

> Same as Tempo: without entering a query and running it, the panel stays blank.

### Metrics (TraceQL metrics / spans)

1. **Explore** → select **Tempo** datasource
2. Switch to the **TraceQL** tab
3. Enter a metrics query:
   ```
   { .service.name = "pydantic-deep" } | rate()
   ```
4. Switch to **Metrics** view to see the time-series chart

For raw Prometheus-style metrics (from Tempo's metrics generator):

1. **Explore** → select **VictoriaMetrics** datasource
2. Enter a PromQL query:
   ```
   {__name__=~"traces_.*"}
   ```

---

## Querying Traces

```bash
# Load active ports first
eval $(.venv/bin/python scripts/vector/alloc_ports.py print)

# Find recent pydantic-deep traces
curl "http://localhost:$TEMPO_HTTP_PORT/api/search?tags=service.name%3Dpydantic-deep&limit=10"

# Fetch a specific trace and extract messages
TRACE_ID=<traceID>
curl -s "http://localhost:$TEMPO_HTTP_PORT/api/traces/$TRACE_ID" | python3 -c "
import json, sys
for batch in json.load(sys.stdin)['batches']:
  for ss in batch['scopeSpans']:
    for span in ss['spans']:
      attrs = {a['key']: a['value'] for a in span.get('attributes', [])}
      for key in ('gen_ai.input.messages', 'gen_ai.output.messages'):
        v = attrs.get(key, {}).get('stringValue')
        if v:
          print(f'--- {key} ---')
          for msg in json.loads(v):
            role = msg.get('role', '?')
            for part in msg.get('parts', []):
              print(f'[{role}] {part.get(\"content\", \"\")[:200]}')
"
```

Key span attributes stored by logfire's pydantic-ai instrumentation:

| Attribute | Content |
|---|---|
| `gen_ai.input.messages` | User messages sent to the model |
| `gen_ai.output.messages` | Assistant response + finish reason |
| `gen_ai.system_instructions` | Full system prompt |
| `gen_ai.usage.input_tokens` | Input token count |
| `gen_ai.usage.output_tokens` | Output token count |
| `gen_ai.response.model` | Model used |

Note: logfire scrubs values matching sensitive keywords (`session`, `auth`, `secret`, `credential`). Set `LOGFIRE_SCRUBBING_PATTERNS=` to disable.

## Architecture

```
pydantic-deep
  │
  ├─ traces (OTLP HTTP) ──────────────────→ Tempo :$TEMPO_OTLP_HTTP_PORT → query :$TEMPO_HTTP_PORT
  │
  └─ logs (HTTP JSON) ──→ Vector :$VECTOR_INGEST_PORT ──→ VictoriaLogs :$VICTORIA_LOGS_PORT

App / other services
  └─ metrics (OTLP HTTP) ─────────────────→ VictoriaMetrics :$VICTORIA_METRICS_PORT
```

Vector's `opentelemetry` sink does not emit standard OTLP wire format, so
traces bypass Vector and go directly to Tempo. Vector handles log routing only.

## What We Discovered

### Vector limitations
- Vector's `opentelemetry` source binds ports 4317/4318 — same as Tempo's OTLP receiver, causing `Address in use` on startup. Fixed by using offset ports (4327/4328) or removing the OTLP source entirely.
- Vector's `opentelemetry` sink (`codec: json`, `codec: native_json`, `codec: otlp`) all fail against Tempo with 400/415 errors. The sink emits Vector's internal event format, not standard OTLP JSON or protobuf. Traces must go directly to Tempo.
- The `log_to_metric` transform's `all_metrics: true` option is documented but not compiled into Vector 0.43.0 — it rejects the config with `missing field 'metrics'`.
- The `opentelemetry` source only exposes `.logs` and `.traces` output ports — there is no `.metrics` port. OTLP metrics must go directly to VictoriaMetrics.

### logfire + OTLP
- logfire respects `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` for custom backends.
- Use `send_to_logfire=False` to suppress logfire.dev upload entirely.
- Use `OTEL_METRICS_EXPORTER=none` to suppress the metrics batch exporter (avoids 404s when the endpoint has no metrics pipeline).
- `OTEL_EXPORTER_OTLP_ENDPOINT` (base URL) causes logfire to POST to both `/v1/traces` and `/v1/metrics` — prefer the signal-specific vars.

### Tempo
- Tempo's OTLP HTTP receiver on `:4318` accepts both `application/json` and `application/x-protobuf`.
- The TraceQL query API is at `:3200/api/traces/{id}` and `:3200/api/search`.
- Tempo's ingester needs ~15s after start before it reports `ready`.

### VictoriaLogs
- Loki-compatible push endpoint: `POST /insert/loki/api/v1/push` (returns 200 with empty body on success).
- Vector's loki sink healthcheck probes a different endpoint and gets 400 — disable with `healthcheck.enabled: false`.

## Files

```
scripts/vector/
├── observability.sh      # Start/stop/status/logs script
├── observability.yaml    # Vector config
├── tempo.yaml            # Tempo config
├── alloc_ports.py        # Port allocation via ports_allocator
├── OBSERVABILITY.md      # This file
├── bin/                  # Downloaded binaries (gitignored)
├── data/                 # Runtime data (gitignored)
├── logs/                 # Service logs (gitignored)
└── pids/                 # PID files — *.pid only (gitignored)

~/.ports-allocator/       # Port session store (managed by ports_allocator)
```
