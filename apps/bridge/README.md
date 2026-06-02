# Bridge App — WeChat Integration for pydantic-deep Agents

Connects a pydantic-deep agent to WeChat via the Tencent iLink Bot API.
Inbound messages from WeChat are fed to the agent; responses stream back
in real time. Multiple users are supported simultaneously via per-user
job queues.

## Quick Start

```bash
# First-time login (scan QR code with WeChat)
python -m apps.bridge --wechat --login

# Subsequent runs (token saved in ~/.pydantic-deep/bridge.json)
python -m apps.bridge --wechat

# Override model or working directory
python -m apps.bridge --wechat --model anthropic:claude-sonnet-4-6 --working-dir /path/to/workspace
```

Enable the **ClawBot** plugin in WeChat before first use:
`WeChat → Me → Settings → Plugins → ClawBot`

## Configuration

Credentials are stored in `~/.pydantic-deep/bridge.json` after login:

```json
{
  "wechat_token": "...",
  "wechat_base_url": "https://ilinkai.weixin.qq.com",
  "model": "anthropic:claude-sonnet-4-6",
  "working_dir": "/path/to/workspace"
}
```

You can also supply the token via environment variable:

```bash
export WECHAT_BOT_TOKEN=your_token
```

**Token precedence:** a fresh `--login` always wins (it carries the
redirected `base_url` from iLink). Otherwise `WECHAT_BOT_TOKEN` takes
priority over the saved `bridge.json`.

## In-Chat Commands

These are handled locally by the bridge and are **not** sent to the agent:

| Command            | Effect                                        |
| ------------------ | --------------------------------------------- |
| `!jobs` / `!j`     | Show the recent job dashboard                 |
| `!job <id>`        | Show details for one job                      |
| `!cancel` / `!kill`| Cancel your running job and any queued jobs   |

Anything else is treated as a prompt for the agent.

## Limitations

- **Single shared workspace.** All WeChat users share one agent instance and
  one `LocalBackend` rooted at `working_dir`. File operations are not isolated
  per user. This suits a personal assistant; for true multi-tenancy you would
  need a backend (and history store) per `uid`.
- **Conversation history is in-memory.** Per-user history lives in the process
  and is lost on restart. It is not persisted to disk like the CLI's
  `messages.json`.
- **No interactive approval.** The bridge runs with `non_interactive=True`, so
  plan mode, memory, and subagents are disabled and `deps.ask_user` is unset.
  Tools that would prompt for confirmation auto-proceed; there is no WeChat
  equivalent of the CLI's approval dialog.
- **Text only.** Inbound images, voice, and file uploads are not handled
  (the cheetahclaws transport supported these; they were not ported).

## End-to-End Flow

### Startup

**Step 1 — Configure credentials**

Either set `WECHAT_BOT_TOKEN` in the environment, or run the QR login:
```bash
python -m apps.bridge --wechat --login
```
`qr_login()` in `wechat.py` hits the iLink API, renders a QR code in the
terminal, polls `get_qrcode_status` until the user confirms in WeChat, then
saves `wechat_token` + `wechat_base_url` to `~/.pydantic-deep/bridge.json`.

**Step 2 — Acquire single-instance lock**

`_acquire_lock()` writes the current PID to `~/.pydantic-deep/wechat.lock`.
If a second process tries to start, it reads the lock, finds the PID alive,
and exits. This prevents double-dispatch (the iLink API re-serves the same
message to all long-pollers).

**Step 3 — Create the agent**

`main.py` calls `create_cli_agent(extra_capabilities=[BridgeCapability(send_fn=...)])`.

This builds a full pydantic-ai agent with:
- All the standard CLI toolsets (filesystem, execute, web, memory, etc.)
- `BridgeCapability` registered — which adds the `send_bridge_message` tool
  and wires the `after_tool_execute` hook for file write notifications.

**Step 4 — Start the poll thread**

`start_poll()` spawns a daemon thread running `_supervisor()` → `_poll_loop()`.
It holds a reference to the asyncio event loop so it can schedule coroutines
onto it from the thread.

**Step 5 — Run the asyncio event loop**

`asyncio.run(runner.run())` blocks, waiting on `_stop_event`. The poll thread
and the runner loop operate concurrently — the thread pushes work in, the loop
consumes it.

---

### Per-Message Flow

**Step 6 — Poll thread receives a message**

`_poll_loop()` calls `_wx_get_updates()` (37-second long-poll to iLink).
When a message arrives:
- Extracts `from_uid` and `text` from the JSON payload
- Saves `context_token` for the user (required by WeChat's reply API)
- Deduplicates via a rolling set of 2000 message IDs (the API can re-serve
  messages on reconnect)
- Calls `asyncio.run_coroutine_threadsafe(on_message(from_uid, text), loop)`
  — this safely crosses the thread→asyncio boundary

**Step 7 — Runner receives the message**

`BridgeRunner.on_message(uid, text)` runs in the asyncio event loop:
- Creates a job record via `jobs.create(text)` — assigns an ID, stores the
  prompt title
- Checks `_user_queues[uid].busy`:
  - **If busy**: puts the job in `asyncio.Queue` and sends a queue position
    message back to the user: `"⏳ Queued #3 (position 2)"`
  - **If free**: calls `_dispatch(uid, job, text)` immediately

Inbound text starting with `!` (e.g. `!jobs`, `!cancel`) is intercepted by
`_handle_command()` first and never reaches the agent.

**Step 8 — Dispatch as a background task**

`_dispatch()` sets `busy = True` synchronously (before the task starts, to
close the race window), then fires `asyncio.create_task(_run_job(...))`. This
is critical — setting busy before yielding prevents a second message arriving
in the same event-loop tick from spawning a concurrent runner for the same user.

**Step 9 — Set the ContextVar**

At the top of `_execute()`, the runner calls:
```python
current_bridge_sender.set(uid)
```
This tags the current asyncio task with the sender's identity. Because
`ContextVar` is isolated per-task, two users being processed concurrently each
carry their own `uid` without interference.

**Step 10 — Run the agent**

`agent.iter(text, deps=deps)` starts the pydantic-ai agent loop. The runner
iterates over nodes:

- **`ModelRequestNode`**: streams the LLM response. Each `TextPartDelta` chunk
  is appended to a buffer. Every 3 seconds (`stream_interval_s`), if the buffer
  has ≥ 80 chars, it is flushed via `_asend(uid, text)` — a new WeChat message
  each time (WeChat has no message-edit API). All sends go through
  `asyncio.to_thread` so the blocking HTTP call never stalls the event loop.

- **`CallToolsNode`**: when the agent calls a tool, `FunctionToolCallEvent`
  fires. `_report_tool_call()` counts the step and sends a progress message
  like `"🔧 write: /workspace/result.py"`. To avoid spamming one message per
  call, only the 1st call and every 3rd thereafter are surfaced; all calls
  still count toward the final step total.

**Step 11 — BridgeCapability intercepts file writes**

When the agent calls the `write` tool, after it succeeds, pydantic-ai fires
`after_tool_execute` on every registered capability.
`BridgeCapability.after_tool_execute()`:
- Checks `call.tool_name == "write"` — skips everything else
- Reads `current_bridge_sender.get()` → gets `uid` from the ContextVar
- Checks the file exists on the real filesystem, reads its size
- Calls `send_fn` (via `asyncio.to_thread`) with
  `"📄 Wrote result.py (4.2 KB)\nPath: /workspace/result.py"`

**Step 12 — Agent sends a message proactively (optional)**

If the agent decides to notify the user mid-turn, it calls the
`send_bridge_message` tool (registered by `_BridgeSendToolset`). The tool
reads `current_bridge_sender.get()` as the default recipient if none is
specified, calls `send_fn(uid, message)`, and returns
`"Message sent to <uid>."` back to the agent.

**Step 13 — Turn completion**

After `agent.iter()` finishes:
- The per-user conversation history is updated with `run.result.all_messages()`
- Remaining buffered chunks are flushed
- `jobs.complete(job.id, full_result)` records the result
- If the job had tool steps: `"✅ Job #2 done (5 steps  12s)"`

**Step 14 — Hand off to the next job**

In `_run_job`'s finally block, `_next_or_idle()` checks the user's queue using
`queue.get_nowait()` (no await point, so no race). If a non-cancelled job is
waiting, it sends `"▶ Starting #3…"` and calls `_dispatch()` again — `busy`
stays `True` across the handoff. When the queue is empty, `busy` is set to
`False` and `current_task` cleared.

---

### Failure Paths

- **Agent exception**: `_execute()` catches it, calls `jobs.fail()`, sends
  `"❌ Job #2 failed: <error>"` to the user.
- **Poll thread crash**: `_supervisor()` catches the exception, waits with
  exponential backoff (2s → 4s → … → 120s), and restarts `_poll_loop()`.
- **Auth expiry** (iLink returns `ret == -14`): `_poll_loop()` returns
  `"auth_error"`, `_supervisor()` logs the error and exits — the user must
  re-run `--login`.
- **Stop**: `Ctrl+C` → `KeyboardInterrupt` → `runner.stop()` sets
  `_stop_event` → `asyncio.run()` exits → `stop_event.set()` signals the poll
  thread → `poll_thread.join(5)` → `_release_lock()`.

---

## Component Map

```
python -m apps.bridge --wechat
        │
        ├── main.py            orchestrates startup and shutdown
        │
        ├── wechat.py          transport layer
        │   ├── qr_login()     one-time interactive auth
        │   ├── _poll_loop()   long-poll thread → asyncio via run_coroutine_threadsafe
        │   └── wx_send()      sends messages back to WeChat
        │
        ├── runner.py          agent execution layer
        │   ├── on_message()   entry point from poll thread
        │   ├── _dispatch()    per-user busy flag + asyncio.Task
        │   ├── _execute()     agent.iter() + streaming + ContextVar
        │   └── _next_or_idle() sequential queue handoff per user
        │
        ├── jobs.py            lightweight job tracker
        │   └── create/start/complete/fail/cancel/format_dashboard
        │
        └── pydantic_deep/capabilities/bridge.py   capability layer
            ├── current_bridge_sender  ContextVar (uid per task)
            ├── BridgeCapability       after_tool_execute → file notify
            └── _BridgeSendToolset     send_bridge_message tool for agent
```

## File Structure

```
apps/bridge/
├── __init__.py
├── __main__.py          # enables: python -m apps.bridge
├── main.py              # entry point, config loading, startup/shutdown
├── runner.py            # BridgeRunner: asyncio queue + agent.iter() loop
├── jobs.py              # thread-safe job tracker
├── wechat.py            # iLink transport: HTTP helpers, QR login, poll loop
└── README.md            # this file

pydantic_deep/capabilities/
└── bridge.py            # BridgeCapability + _BridgeSendToolset
```
