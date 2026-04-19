# Browser Automation

`BrowserCapability` gives agents full control of a real browser via [Playwright](https://playwright.dev/python/) — navigate URLs, click elements, fill forms, run JavaScript, and take screenshots.

## Installation

```bash
pip install 'pydantic-deep[browser]'
playwright install chromium
```

Or install everything at once:

```bash
pip install 'pydantic-deep[all]'
playwright install chromium
```

## Quick Start

```python
from pydantic_deep import create_deep_agent
from pydantic_deep.capabilities.browser import BrowserCapability

agent = create_deep_agent(
    capabilities=[BrowserCapability()],
)
```

By default the browser window is **visible** (`headless=False`). To run without a window:

```python
agent = create_deep_agent(
    capabilities=[BrowserCapability(headless=True)],
)
```

## CLI

Browser automation is opt-in in the CLI:

```bash
# TUI with browser
pydantic-deep tui --browser

# Headless run with browser
pydantic-deep run "Go to example.com and summarize the content" --browser

# Use headless mode (no visible window)
pydantic-deep run "Scrape the table" --browser --browser-headless

# Explicitly disable browser
pydantic-deep run "Fix bug" --no-browser
```

Or set as the default in config:

```toml
include_browser = true
browser_headless = false   # visible window (default)
```

## BrowserCapability Options

```python
BrowserCapability(
    headless=False,            # Show browser window (default)
    allowed_domains=None,      # Restrict to these domains (None = all allowed)
    screenshot_on_navigate=False,  # Auto-screenshot on every navigate call
    max_content_tokens=4000,   # Truncate page content to ~N tokens
    timeout_ms=30_000,         # Default timeout for navigation/interactions
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `headless` | `bool` | `False` | Run browser without a visible window |
| `allowed_domains` | `list[str] \| None` | `None` | Restrict navigation to these domains. Subdomains are allowed. |
| `screenshot_on_navigate` | `bool` | `False` | Automatically take a screenshot after every `navigate` call |
| `max_content_tokens` | `int` | `4000` | Truncate page text content to approximately this many tokens |
| `timeout_ms` | `int` | `30000` | Default timeout in milliseconds for navigation and interactions |

## Available Tools

The agent gets 9 browser tools:

| Tool | Description |
|------|-------------|
| `navigate` | Go to a URL |
| `click` | Click an element by CSS selector or text |
| `type_text` | Type text into an input element |
| `get_text` | Get text content of the current page |
| `screenshot` | Take a screenshot (returns base64 PNG) |
| `scroll` | Scroll the page by pixels |
| `go_back` | Navigate to the previous page |
| `go_forward` | Navigate to the next page |
| `execute_js` | Execute arbitrary JavaScript and return result |

## Domain Allowlist

Restrict the agent to specific domains for security:

```python
BrowserCapability(
    allowed_domains=["docs.python.org", "github.com"],
)
```

Subdomains are automatically allowed — `github.com` also allows `api.github.com`, `gist.github.com`, etc.

## Lifecycle

The browser is started and stopped automatically around each agent run:

```
agent.run("...") starts
  → Playwright launches Chromium
  → BrowserCapability populates page reference
  → Agent tools use the page
  → Browser closes (on success, exception, or cancellation)
agent.run() returns
```

A single browser tab is used. If the page navigates to a popup/new tab, it is automatically redirected into the same tab.

## Examples

### Summarize a page

```python
result = await agent.run(
    "Go to https://docs.pydantic.dev and summarize the main features."
)
```

### Fill a form

```python
result = await agent.run(
    "Go to https://example.com/login, enter username 'test' and password 'pass', "
    "then click the login button and tell me what happens."
)
```

### Screenshot and describe

```python
result = await agent.run(
    "Take a screenshot of https://example.com and describe the layout."
)
```

### Scrape data

```python
result = await agent.run(
    "Go to https://example.com/table, extract all rows from the first table, "
    "and return them as a JSON list."
)
```

## Requirements

- `playwright>=1.40.0` (bundled in `pydantic-deep[browser]`)
- Chromium browser: `playwright install chromium`
- `html2text>=2020.1` (optional — improves page content extraction)

## Next Steps

- [Web Tools](web-tools.md) — Lightweight read-only web access (WebSearch, WebFetch)
- [Hooks](hooks.md) — Intercept browser tool calls for logging or access control
- [Capabilities](middleware.md) — Overview of the Capabilities API
