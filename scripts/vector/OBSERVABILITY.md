# Observability Stack

Local observability pipeline for pydantic-deep — no Docker required.

## Services

| Service | Role | Port |
|---|---|---|
| **Vector** | Log router (HTTP → VictoriaLogs) | `9880` (ingest), `8686` (API) |
| **VictoriaMetrics** | Metrics storage, PromQL API | `8428` |
| **VictoriaLogs** | Log storage, LogQL API | `9428` |
| **Tempo** | Trace storage, TraceQL API | `3200` (query), `4317` gRPC, `4318` HTTP |

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

## Sending Data

| Signal | Endpoint | Notes |
|---|---|---|
| Logs (HTTP JSON) | `http://localhost:9880` | Routed via Vector → VictoriaLogs |
| Traces (OTLP HTTP) | `http://localhost:4318/v1/traces` | Direct to Tempo |
| Traces (OTLP gRPC) | `localhost:4317` | Direct to Tempo |
| Metrics (OTLP HTTP) | `http://localhost:8428/opentelemetry/v1/metrics` | Direct to VictoriaMetrics |

## pydantic-deep Integration

Enable Vector tracing with the `--vector` flag or config:

```bash
# One-shot
pydantic-deep --vector run "Hello"

# Permanent (config.toml)
pydantic-deep config set vector true
```

Environment variables:

| Variable | Default | Description |
|---|---|---|
| `VECTOR_OTLP_ENDPOINT` | `http://localhost:4318` | OTLP traces endpoint |
| `OTEL_SERVICE_NAME` | `pydantic-deep` | Service name in traces |

The `--vector` flag uses logfire with `send_to_logfire=False` and sets:
- `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` → Vector/Tempo
- `OTEL_METRICS_EXPORTER=none` (suppresses metrics 404s)

## Querying Traces

```bash
# Find recent pydantic-deep traces
curl "http://localhost:3200/api/search?tags=service.name%3Dpydantic-deep&limit=10"

# Fetch a specific trace and extract messages
TRACE_ID=<traceID>
curl -s "http://localhost:3200/api/traces/$TRACE_ID" | python3 -c "
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
  ├─ traces (OTLP HTTP) ──────────────────→ Tempo :4318 → storage :3200
  │
  └─ logs (HTTP JSON) ──→ Vector :9880 ──→ VictoriaLogs :9428

App / other services
  └─ metrics (OTLP HTTP) ─────────────────→ VictoriaMetrics :8428
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
├── OBSERVABILITY.md      # This file
├── bin/                  # Downloaded binaries (gitignored)
├── data/                 # Runtime data (gitignored)
├── logs/                 # Service logs (gitignored)
└── pids/                 # PID files (gitignored)
```
