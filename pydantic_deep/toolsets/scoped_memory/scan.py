"""Date-based memory age + staleness helpers.

Age is computed from the immutable ``created`` frontmatter date (never mtime,
never last_used_at). The staleness warning is a CODE-STATE caveat, gated on a
configurable threshold.
"""

from __future__ import annotations

from datetime import date


def memory_age_days(created: str, today: str | None = None) -> int:
    """Whole days between ``created`` and ``today`` (both ISO). 0 if missing/invalid/future."""
    if not created:
        return 0
    try:
        c = date.fromisoformat(created)
        t = date.fromisoformat(today) if today else date.today()
    except ValueError:
        return 0
    return max(0, (t - c).days)


def memory_age_str(days: int) -> str:
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago"


def memory_freshness_text(age_days: int, staleness_days: int = 7) -> str:
    """Staleness caveat when age_days > staleness_days; '' otherwise."""
    if age_days <= staleness_days:
        return ""
    return (
        f"This memory is {age_days} days old. "
        "Memories are point-in-time observations, not live state — "
        "claims about code behavior or file:line citations may be outdated. "
        "Verify against current code before asserting as fact."
    )
