"""Rich terminal renderer for session traces.jsonl files."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _ns_to_dt(ns: int | None) -> datetime | None:
    if ns is None:
        return None
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).astimezone()


def _duration_ms(start: int | None, end: int | None) -> str:
    if start is None or end is None:
        return "?"
    ms = (end - start) / 1e6
    if ms >= 1000:
        return f"{ms/1000:.1f}s"
    return f"{ms:.0f}ms"


def _short(text: str, max_len: int = 100) -> str:
    return str(text).strip()


def _parse_json(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return None
    return raw


def _tool_calls_from_output(output_messages: Any) -> list[dict]:
    """Extract tool_call parts from gen_ai.output.messages."""
    msgs = _parse_json(output_messages)
    if not msgs:
        return []
    calls = []
    for msg in msgs:
        for part in msg.get("parts", []):
            if part.get("type") == "tool_call":
                calls.append(part)
    return calls


def _text_from_output(output_messages: Any) -> list[str]:
    """Extract text content from gen_ai.output.messages."""
    msgs = _parse_json(output_messages)
    if not msgs:
        return []
    texts = []
    for msg in msgs:
        for part in msg.get("parts", []):
            if part.get("type") == "text" and part.get("content", "").strip():
                texts.append(part["content"].strip())
    return texts


def _user_message(input_messages: Any) -> str | None:
    """Extract the first user message (only from the first chat span)."""
    msgs = _parse_json(input_messages)
    if not msgs:
        return None
    for msg in msgs:
        if msg.get("role") == "user":
            for part in msg.get("parts", []):
                content = part.get("content", "")
                if isinstance(content, str) and content.strip():
                    return content.strip()
    return None


def render_traces(session_id: str, traces_path: Path) -> None:
    from rich.console import Console
    from rich.panel import Panel
    from rich.rule import Rule

    console = Console()

    if not traces_path.exists():
        console.print(f"[red]No traces found at {traces_path}[/red]")
        return

    spans = []
    for line in traces_path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                spans.append(json.loads(line))
            except Exception:
                pass

    if not spans:
        console.print("[yellow]traces.jsonl is empty[/yellow]")
        return

    # Index spans by id
    by_id: dict[str, dict] = {s["span_id"]: s for s in spans if s.get("span_id")}

    # Sort by start_time
    spans.sort(key=lambda s: s.get("start_time") or 0)

    # Find root agent run (no parent in our span set, or parent is the session root)
    def _in_set(pid: str | None) -> bool:
        return bool(pid and pid in by_id)

    # Build children map
    children: dict[str, list[dict]] = {}
    roots: list[dict] = []
    for s in spans:
        pid = s.get("parent_span_id")
        if _in_set(pid):
            children.setdefault(pid, []).append(s)
        else:
            roots.append(s)

    # Header
    start_times = [s["start_time"] for s in spans if s.get("start_time")]
    session_start = _ns_to_dt(min(start_times)) if start_times else None
    time_str = session_start.strftime("%Y-%m-%d %H:%M:%S") if session_start else "?"

    console.print()
    console.print(
        Panel(
            f"[bold cyan]Session:[/bold cyan] {session_id}   "
            f"[bold cyan]Started:[/bold cyan] {time_str}   "
            f"[bold cyan]Spans:[/bold cyan] {len(spans)}",
            title="[bold]Trace Viewer[/bold]",
            border_style="cyan",
            padding=(0, 1),
        )
    )
    console.print()

    def _render_span(span: dict, depth: int, first_chat: bool) -> bool:
        """Render one span. Returns True if this was the first chat span."""
        attrs = span.get("attributes", {})
        name = span.get("name", "?")
        status = span.get("status", "UNSET")
        dur = _duration_ms(span.get("start_time"), span.get("end_time"))
        start_dt = _ns_to_dt(span.get("start_time"))
        time_str = start_dt.strftime("%H:%M:%S.%f")[:-3] if start_dt else "?"
        indent = "  " * depth
        is_error = status == "ERROR"

        # ── agent run ──────────────────────────────────────────────────────
        if name == "agent run":
            model = attrs.get("model_name", "")
            final = attrs.get("final_result")
            status_icon = "[red]✗[/red]" if is_error else "[green]✓[/green]"
            console.print(
                f"{indent}[bold blue]▶ agent run[/bold blue]  "
                f"[dim]{model}[/dim]  [dim]{dur}[/dim]  {status_icon}"
            )
            if is_error:
                for ev in span.get("events", []):
                    if ev.get("name") == "exception":
                        msg = ev.get("attributes", {}).get("exception.message", "")
                        console.print(f"{indent}  [red]{_short(msg, 120)}[/red]")
            if final and depth == 0:
                console.print()
                console.print(f"{indent}  [bold green]Result:[/bold green] {_short(str(final), 200)}")
            return first_chat

        # ── chat (LLM call) ────────────────────────────────────────────────
        if "chat" in name:
            model = attrs.get("gen_ai.request.model", name)
            out_msgs = attrs.get("gen_ai.output.messages")
            tool_calls = _tool_calls_from_output(out_msgs)
            texts = _text_from_output(out_msgs)

            # Only show user prompt on the very first chat span
            if first_chat:
                user_msg = _user_message(attrs.get("gen_ai.input.messages"))
                if user_msg:
                    console.print(f"{indent}[cyan]  user:[/cyan] {_short(user_msg, 150)}")
                first_chat = False

            if tool_calls:
                for tc in tool_calls:
                    tool_name = tc.get("name", "?")
                    args = _parse_json(tc.get("arguments", {})) or {}
                    args_str = _short(json.dumps(args), 80) if args else ""
                    console.print(
                        f"{indent}  [dim]{time_str}[/dim]  "
                        f"[magenta]⚙ {tool_name}[/magenta]"
                        + (f"  [dim]{args_str}[/dim]" if args_str else "")
                        + f"  [dim]{dur}[/dim]"
                    )
            elif texts:
                for t in texts:
                    console.print(
                        f"{indent}  [dim]{time_str}[/dim]  "
                        f"[yellow]✎ thinking:[/yellow] [dim]{_short(t, 120)}[/dim]"
                    )
            return first_chat

        # ── running tool ───────────────────────────────────────────────────
        if name == "running tool":
            tool_name = attrs.get("gen_ai.tool.name", "?")
            tool_args = _parse_json(attrs.get("tool_arguments", {})) or {}
            tool_resp = attrs.get("tool_response", "")
            is_err = status == "ERROR"

            args_str = _short(json.dumps(tool_args), 80) if tool_args else ""
            resp_str = _short(str(tool_resp), 120)
            resp_style = "red" if is_err else "dim"

            console.print(
                f"{indent}  [dim]{time_str}[/dim]  "
                f"[magenta]  → {tool_name}[/magenta]"
                + (f"  [dim]{args_str}[/dim]" if args_str else "")
                + f"  [dim]{dur}[/dim]"
            )
            if resp_str:
                console.print(f"{indent}     [{resp_style}]{resp_str}[/{resp_style}]")
            return first_chat

        return first_chat

    def _render_tree(span: dict, depth: int, first_chat: bool) -> bool:
        first_chat = _render_span(span, depth, first_chat)
        for child in sorted(children.get(span["span_id"], []), key=lambda s: s.get("start_time") or 0):
            first_chat = _render_tree(child, depth + 1, first_chat)
        return first_chat

    for root in roots:
        _render_tree(root, 0, first_chat=True)
        console.print()
