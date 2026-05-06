"""Observability agent — queries VictoriaLogs/Metrics/Traces, reasons about issues,
implements fixes as PRs, and restarts the app. Implements the feedback loop from
the diagram: Query → Correlate → Reason → Implement change (PR) → Restart app → Re-run workload.

Usage:
    # Ports are resolved automatically from ports_allocator when running.
    # Fallback: set environment variables manually:
    export VICTORIA_LOGS_URL=http://localhost:9428
    export VICTORIA_METRICS_URL=http://localhost:8428
    export VICTORIA_TRACES_URL=http://localhost:3200
    python examples/observability_agent.py
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import httpx
from pydantic_ai import RunContext

from pydantic_deep import DeepAgentDeps, LocalBackend, create_deep_agent


# ─── Port resolution from top-level session file ─────────────────────────────

def _resolve_obs_urls() -> tuple[str, str, str]:
    """Return (victoria_logs_url, victoria_metrics_url, victoria_traces_url).

    Reads the top-level pydantic-deepagents port session file written by
    ``scripts/vector/alloc_ports.py`` (called from ``observability.sh``).
    Falls back to environment variables / hardcoded defaults when no session
    file exists.
    """
    try:
        repo_root = Path(__file__).parent.parent
        user = os.environ.get("USER") or os.environ.get("LOGNAME", "")
        host = socket.gethostname().split(".")[0]
        session_file = repo_root / ".pydantic-deep-sessions" / f"{user}@{host}.obs.json"
        if session_file.exists():
            ports = json.loads(session_file.read_text())
            return (
                f"http://localhost:{ports['victoria_logs']}",
                f"http://localhost:{ports['victoria_metrics']}",
                f"http://localhost:{ports['tempo_http']}",
            )
    except Exception:
        pass

    # Fall back to env vars / hardcoded defaults
    return (
        os.getenv("VICTORIA_LOGS_URL", "http://localhost:9428"),
        os.getenv("VICTORIA_METRICS_URL", "http://localhost:8428"),
        os.getenv("VICTORIA_TRACES_URL", "http://localhost:3200"),
    )


# ─── Config ───────────────────────────────────────────────────────────────────

VICTORIA_LOGS_URL, VICTORIA_METRICS_URL, VICTORIA_TRACES_URL = _resolve_obs_urls()

# ─── Observability query tools ────────────────────────────────────────────────


async def query_logs(
    ctx: RunContext[DeepAgentDeps],
    logql_query: str,
    start: str = "now-1h",
    end: str = "now",
    limit: int = 100,
) -> str:
    """Query VictoriaLogs using LogQL.

    Args:
        logql_query: LogQL query string, e.g. '{service="api"} |= "error"'
        start: Start time (RFC3339 or relative like "now-1h"). Default: now-1h.
        end: End time. Default: now.
        limit: Maximum number of log lines to return. Default: 100.

    Returns:
        JSON string with matching log lines.
    """
    params = {"query": logql_query, "start": start, "end": end, "limit": str(limit)}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{VICTORIA_LOGS_URL}/select/logsql/query", params=params)
        resp.raise_for_status()
        return resp.text


async def query_metrics(
    ctx: RunContext[DeepAgentDeps],
    promql_query: str,
    start: str | None = None,
    end: str | None = None,
    step: str = "60s",
) -> str:
    """Query VictoriaMetrics using PromQL.

    Args:
        promql_query: PromQL expression, e.g. 'rate(http_requests_total[5m])'
        start: Start time (Unix timestamp or RFC3339). None = instant query.
        end: End time. None = instant query.
        step: Resolution step for range queries. Default: 60s.

    Returns:
        JSON string with metric results.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        if start and end:
            # Range query
            params: dict[str, Any] = {
                "query": promql_query,
                "start": start,
                "end": end,
                "step": step,
            }
            resp = await client.get(
                f"{VICTORIA_METRICS_URL}/api/v1/query_range", params=params
            )
        else:
            # Instant query
            resp = await client.get(
                f"{VICTORIA_METRICS_URL}/api/v1/query", params={"query": promql_query}
            )
        resp.raise_for_status()
        return resp.text


async def query_traces(
    ctx: RunContext[DeepAgentDeps],
    traceql_query: str,
    start: str | None = None,
    end: str | None = None,
    limit: int = 20,
) -> str:
    """Query VictoriaTraces / Tempo using TraceQL.

    Args:
        traceql_query: TraceQL expression, e.g. '{ .http.status_code = 500 }'
        start: Start time (Unix nanoseconds or RFC3339). None = last hour.
        end: End time. None = now.
        limit: Maximum number of traces to return. Default: 20.

    Returns:
        JSON string with matching traces.
    """
    params: dict[str, Any] = {"q": traceql_query, "limit": str(limit)}
    if start:
        params["start"] = start
    if end:
        params["end"] = end

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{VICTORIA_TRACES_URL}/api/search", params=params)
        resp.raise_for_status()
        return resp.text


async def get_service_health(ctx: RunContext[DeepAgentDeps], service: str) -> str:
    """Get a quick health summary for a service: error rate, p99 latency, recent errors.

    Args:
        service: Service name label value (e.g. "api", "worker").

    Returns:
        Multi-section health summary string.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        # Error rate
        err_resp = await client.get(
            f"{VICTORIA_METRICS_URL}/api/v1/query",
            params={"query": f'rate(http_requests_total{{service="{service}",status=~"5.."}}[5m])'},
        )
        # p99 latency
        lat_resp = await client.get(
            f"{VICTORIA_METRICS_URL}/api/v1/query",
            params={
                "query": f'histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{{service="{service}"}}[5m]))'
            },
        )
        # Recent errors from logs
        log_resp = await client.get(
            f"{VICTORIA_LOGS_URL}/select/logsql/query",
            params={
                "query": f'{{service="{service}"}} | level = "error"',
                "start": "now-15m",
                "limit": "10",
            },
        )

    return (
        f"=== Health: {service} ===\n"
        f"Error rate (5m): {err_resp.text}\n\n"
        f"p99 latency (5m): {lat_resp.text}\n\n"
        f"Recent errors (15m):\n{log_resp.text}"
    )


async def reload_vector_config(ctx: RunContext[DeepAgentDeps]) -> str:
    """Signal Vector to reload its configuration without downtime.

    Returns:
        Reload status message.
    """
    vector_api = os.getenv("VECTOR_API_URL", "http://localhost:8686")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.put(f"{vector_api}/health")
        return f"Vector reload status: {resp.status_code}"


# ─── Agent ────────────────────────────────────────────────────────────────────

OBSERVABILITY_INSTRUCTIONS = """
You are an observability agent with full access to the application's telemetry stack.

## Your capabilities
- **query_logs**: LogQL queries against VictoriaLogs (errors, patterns, anomalies)
- **query_metrics**: PromQL queries against VictoriaMetrics (rates, latencies, saturation)
- **query_traces**: TraceQL queries against VictoriaTraces (slow spans, error traces)
- **get_service_health**: Quick health snapshot for any service
- **reload_vector_config**: Reload Vector pipeline config without downtime
- Plus full filesystem access to read and modify the codebase

## Feedback loop workflow
1. **Query** — use LogQL/PromQL/TraceQL to find anomalies or regressions
2. **Correlate** — cross-reference logs, metrics, and traces to pinpoint root cause
3. **Reason** — explain what is wrong and why
4. **Implement** — make the minimal code change that fixes the issue
5. **Restart** — run `docker compose restart <service>` or equivalent to apply the fix
6. **Re-run workload** — trigger the test/benchmark again to verify the fix

Always correlate across all three signal types before concluding root cause.
When implementing a fix, prefer the smallest change that addresses the root cause.
"""


def create_observability_agent(codebase_dir: str = ".") -> Any:
    """Create the observability agent bound to the local codebase."""
    backend = LocalBackend(root_dir=codebase_dir)
    return create_deep_agent(
        instructions=OBSERVABILITY_INSTRUCTIONS,
        backend=backend,
        tools=[
            query_logs,
            query_metrics,
            query_traces,
            get_service_health,
            reload_vector_config,
        ],
        include_filesystem=True,
        include_execute=True,
        include_plan=True,
        include_memory=True,
        web_search=False,  # No need for web search in this loop
        web_fetch=False,
        context_discovery=True,
    )


# ─── Entry point ──────────────────────────────────────────────────────────────


async def main() -> None:
    import sys

    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        "Check the health of the 'api' service. "
        "Query logs for errors in the last 15 minutes, check the error rate and p99 latency, "
        "then look for any slow traces. Correlate the signals and summarise what you find."
    )

    agent = create_observability_agent(codebase_dir=".")
    deps = DeepAgentDeps(backend=LocalBackend(root_dir="."))

    print(f"Task: {task}\n{'─' * 60}")
    result = await agent.run(task, deps=deps)
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())
