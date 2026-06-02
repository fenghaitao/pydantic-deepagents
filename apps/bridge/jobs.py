"""Lightweight job tracker for bridge message processing."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Literal

JobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


@dataclass
class Job:
    id: str
    prompt: str
    source: str
    title: str
    status: JobStatus = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result: str = ""
    error: str = ""
    step_count: int = 0
    retry_of: str | None = None

    @property
    def duration_s(self) -> float | None:
        if self.started_at is None or self.finished_at is None:
            return None
        return self.finished_at - self.started_at


_lock = threading.Lock()
_jobs: dict[str, Job] = {}
_counter = 0


def _next_id() -> str:
    global _counter
    with _lock:
        _counter += 1
        return str(_counter)


def create(prompt: str, source: str = "bridge", retry_of: str | None = None) -> Job:
    job = Job(
        id=_next_id(),
        prompt=prompt,
        source=source,
        title=prompt[:60].replace("\n", " "),
        retry_of=retry_of,
    )
    with _lock:
        _jobs[job.id] = job
    return job


def get(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(job_id)


def start(job_id: str) -> None:
    with _lock:
        if j := _jobs.get(job_id):
            j.status = "running"
            j.started_at = time.time()


def add_step(job_id: str, tool_name: str, preview: str = "") -> None:
    with _lock:
        if j := _jobs.get(job_id):
            j.step_count += 1


def complete(job_id: str, result: str) -> None:
    with _lock:
        if j := _jobs.get(job_id):
            j.status = "completed"
            j.result = result
            j.finished_at = time.time()


def fail(job_id: str, error: str) -> None:
    with _lock:
        if j := _jobs.get(job_id):
            j.status = "failed"
            j.error = error
            j.finished_at = time.time()


def cancel(job_id: str) -> None:
    with _lock:
        if j := _jobs.get(job_id):
            j.status = "cancelled"
            j.finished_at = time.time()


def list_running() -> list[Job]:
    with _lock:
        return [j for j in _jobs.values() if j.status == "running"]


def format_dashboard() -> str:
    with _lock:
        jobs = sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)[:10]
    if not jobs:
        return "No jobs yet."
    lines = [f"Jobs (last {len(jobs)}):"]
    icons = {"queued": "⏳", "running": "▶", "completed": "✅", "failed": "❌", "cancelled": "🚫"}
    for j in jobs:
        icon = icons.get(j.status, "?")
        dur = f" {j.duration_s:.0f}s" if j.duration_s else ""
        lines.append(f"  {icon} #{j.id}{dur}: {j.title}")
    return "\n".join(lines)


def format_detail(job_id: str) -> str:
    j = get(job_id)
    if not j:
        return f"Job #{job_id} not found."
    lines = [
        f"Job #{j.id} [{j.status}]",
        f"  Source : {j.source}",
        f"  Prompt : {j.title}",
        f"  Steps  : {j.step_count}",
    ]
    if j.duration_s is not None:
        lines.append(f"  Time   : {j.duration_s:.1f}s")
    if j.error:
        lines.append(f"  Error  : {j.error[:200]}")
    elif j.result:
        lines.append(f"  Result : {j.result[:200]}")
    return "\n".join(lines)
