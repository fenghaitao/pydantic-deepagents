"""BridgeRunner — async loop that drives an agent from bridge messages.

Architecture:
    poll thread → on_message() → asyncio.Queue → _dispatch() → agent.iter()
                                                              → send_fn(uid, chunk)

Sends are dispatched through ``asyncio.to_thread`` so the synchronous transport
HTTP calls never block the event loop. Conversation history is tracked per-uid
so each WeChat user has an independent, continuous conversation.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from apps.bridge import jobs as _jobs

logger = logging.getLogger(__name__)

SendFn = Callable[[str, str], None]           # (uid, text) → None (sync transport call)


@dataclass
class _UserQueue:
    """Per-user job queue, busy flag, and running-task handle."""
    queue: asyncio.Queue[tuple[str, str]] = field(default_factory=asyncio.Queue)  # (job_id, prompt)
    busy: bool = False
    current_task: asyncio.Task[None] | None = None
    queued_ids: set[str] = field(default_factory=set)


class BridgeRunner:
    """Consumes inbound messages from bridge transports and drives an agent.

    Usage::

        runner = BridgeRunner(agent=agent, deps=deps, send_fn=wx_send)
        await runner.run()         # blocks until stop() is called

    The ``send_fn(uid, text)`` is the transport-specific send function
    (e.g. ``wx_send``). It is synchronous; the runner offloads it to a thread.
    """

    def __init__(
        self,
        agent: Any,
        deps: Any,
        send_fn: SendFn,
        *,
        stream_interval_s: float = 3.0,
        stream_min_len: int = 80,
        max_turns: int | None = None,
    ) -> None:
        self._agent = agent
        self._deps = deps
        self._send_fn = send_fn
        self._stream_interval_s = stream_interval_s
        self._stream_min_len = stream_min_len
        self._max_turns = max_turns
        self._user_queues: dict[str, _UserQueue] = {}
        self._histories: dict[str, list[Any]] = {}   # uid → message history
        self._stop_event = asyncio.Event()

    # ── send helper ─────────────────────────────────────────────────────────

    async def _asend(self, uid: str, text: str) -> None:
        """Send a message off the event loop so blocking HTTP never stalls it."""
        try:
            await asyncio.to_thread(self._send_fn, uid, text)
        except Exception:
            logger.exception("Failed to send message to %s", uid)

    # ── inbound ─────────────────────────────────────────────────────────────

    async def on_message(self, uid: str, text: str) -> None:
        """Receive an inbound message (scheduled by the poll thread)."""
        # User commands are handled locally, not sent to the agent.
        if await self._handle_command(uid, text):
            return

        if uid not in self._user_queues:
            self._user_queues[uid] = _UserQueue()
        uq = self._user_queues[uid]

        job = _jobs.create(text, source="wechat")

        if uq.busy:
            uq.queued_ids.add(job.id)
            await uq.queue.put((job.id, text))
            queue_pos = uq.queue.qsize()
            await self._asend(
                uid,
                f"⏳ Queued #{job.id} (position {queue_pos})\n{job.title}\nSend !jobs to check progress",
            )
            return

        await self._dispatch(uid, job, text)

    async def _handle_command(self, uid: str, text: str) -> bool:
        """Handle ``!jobs`` / ``!job`` / ``!cancel`` locally. Returns True if consumed."""
        cmd = text.strip().lower()

        if cmd in ("!jobs", "!j", "!status"):
            await self._asend(uid, _jobs.format_dashboard())
            return True

        if cmd.startswith("!job "):
            jid = text.strip().split(None, 1)[1].lstrip("#").strip()
            await self._asend(uid, _jobs.format_detail(jid))
            return True

        if cmd in ("!cancel", "!kill"):
            uq = self._user_queues.get(uid)
            n = 0
            if uq:
                for jid in list(uq.queued_ids):
                    _jobs.cancel(jid)
                    n += 1
                uq.queued_ids.clear()
                if uq.current_task and not uq.current_task.done():
                    uq.current_task.cancel()
                    n += 1
            await self._asend(uid, f"🚫 Cancelled {n} job(s)" if n else "ℹ No jobs to cancel")
            return True

        return False

    # ── dispatch & drain ────────────────────────────────────────────────────

    async def _dispatch(self, uid: str, job: _jobs.Job, text: str) -> None:
        """Mark busy and fire the job as a background task."""
        uq = self._user_queues[uid]
        uq.busy = True
        uq.current_task = asyncio.create_task(self._run_job(uid, job, text))

    async def _run_job(self, uid: str, job: _jobs.Job, text: str) -> None:
        """Run one agent turn for a user, then hand off to the next queued job."""
        try:
            await self._execute(uid, job, text)
        except asyncio.CancelledError:
            _jobs.cancel(job.id)
            await self._asend(uid, f"🚫 Job #{job.id} cancelled")
            raise
        finally:
            await self._next_or_idle(uid)

    async def _next_or_idle(self, uid: str) -> None:
        """Start the next non-cancelled queued job, or go idle.

        ``busy`` stays True across the handoff so a concurrently-arriving
        message can never slip in between jobs and spawn a second runner.
        Uses ``get_nowait`` so there is no await point that could open a race.
        """
        uq = self._user_queues.get(uid)
        if uq is None:
            return
        while not uq.queue.empty():
            job_id, prompt = uq.queue.get_nowait()
            uq.queued_ids.discard(job_id)
            job = _jobs.get(job_id)
            if not job or job.status == "cancelled":
                continue
            remaining = uq.queue.qsize()
            pos_msg = f" ({remaining} more queued)" if remaining else ""
            await self._asend(uid, f"▶ Starting #{job_id}{pos_msg}:\n{job.title}")
            await self._dispatch(uid, job, prompt)
            return
        uq.busy = False
        uq.current_task = None

    # ── execution ───────────────────────────────────────────────────────────

    async def _execute(self, uid: str, job: _jobs.Job, text: str) -> None:
        """Run agent.iter() for one message, streaming chunks back to the user."""
        from pydantic_ai import Agent
        from pydantic_ai.messages import FunctionToolCallEvent, PartDeltaEvent, TextPartDelta

        from pydantic_deep.capabilities.bridge import current_bridge_sender
        from pydantic_deep.deps import DEFAULT_USAGE_LIMITS

        # Tag this task with the sender so BridgeCapability can read it
        current_bridge_sender.set(uid)

        _jobs.start(job.id)
        await self._asend(uid, f"⏳ Job #{job.id} running…")

        chunks: list[str] = []
        result_buf: list[str] = []
        last_send = time.monotonic()

        async def _flush() -> None:
            nonlocal last_send
            text_so_far = "".join(chunks)
            if len(text_so_far) >= self._stream_min_len:
                await self._asend(uid, text_so_far)  # wx_send splits at 2000 chars
                result_buf.append(text_so_far)
                chunks.clear()
            last_send = time.monotonic()

        run_kwargs: dict[str, Any] = {
            "usage_limits": DEFAULT_USAGE_LIMITS,
            "message_history": self._histories.get(uid),
        }
        if self._max_turns is not None:
            run_kwargs["max_turns"] = self._max_turns

        try:
            async with self._agent.iter(text, deps=self._deps, **run_kwargs) as run:
                async for node in run:
                    if Agent.is_model_request_node(node):
                        async with node.stream(run.ctx) as stream:
                            async for event in stream:
                                if (
                                    isinstance(event, PartDeltaEvent)
                                    and isinstance(event.delta, TextPartDelta)
                                ):
                                    chunks.append(event.delta.content_delta or "")
                                    if time.monotonic() - last_send >= self._stream_interval_s:
                                        await _flush()

                    elif Agent.is_call_tools_node(node):
                        async with node.stream(run.ctx) as handle:
                            async for event in handle:
                                if isinstance(event, FunctionToolCallEvent):
                                    await self._report_tool_call(uid, job, event)

            # Persist conversation history for this user
            if run.result is not None:
                self._histories[uid] = run.result.all_messages()

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _jobs.fail(job.id, str(exc))
            await self._asend(uid, f"❌ Job #{job.id} failed: {exc}\n↩ Try again later")
            logger.exception("Job %s failed for uid %s", job.id, uid)
            return

        # Flush remaining
        remaining_text = "".join(chunks).strip()
        if remaining_text:
            await self._asend(uid, remaining_text)
            result_buf.append(remaining_text)

        full_result = "".join(result_buf)
        _jobs.complete(job.id, full_result)

        j = _jobs.get(job.id)
        if j and j.step_count > 0:
            dur = f"  {j.duration_s:.0f}s" if j.duration_s else ""
            await self._asend(uid, f"✅ Job #{job.id} done ({j.step_count} steps{dur})")

    async def _report_tool_call(self, uid: str, job: _jobs.Job, event: Any) -> None:
        """Record a tool call and send a compact progress notice (batched).

        To avoid one WeChat message per tool call, only the first call and
        every third call thereafter are surfaced. All calls still count toward
        the job's step total shown in the completion summary.
        """
        name = event.part.tool_name
        args = event.part.args if isinstance(event.part.args, dict) else {}
        preview = str(
            args.get("command", args.get("file_path", args.get("query", "")))
        ).strip()[:60]
        _jobs.add_step(job.id, name, preview)

        j = _jobs.get(job.id)
        step = j.step_count if j else 1
        if step == 1 or step % 3 == 0:
            label = f"🔧 {name}" + (f": {preview}" if preview else "")
            await self._asend(uid, label)

    # ── lifecycle ───────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Block until stop() is called."""
        await self._stop_event.wait()

    def stop(self) -> None:
        self._stop_event.set()
