"""RCA-specific PR comment building and posting.

Builds a compact PR comment from a full RCA markdown report and posts it
via :class:`common.pr_comment.PRCommentClient`.

The comment is structured to surface the most actionable information
(classification, root cause, suggested fix, patch) without exceeding
GitHub's comment size limit.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Allow importing from the sibling tools/common package when this module is
# imported by a script that adds tools/ to sys.path.
_tools_dir = str(Path(__file__).parent.parent)
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

from common.pr_comment import PRCommentClient  # noqa: E402

_MAX_COMMENT_CHARS = 65_000  # GitHub comment hard limit is ~65 536 chars


def _extract_section(
    content: str, heading: str, max_chars: int | None = None
) -> str:
    """Extract a markdown section by heading name."""
    pattern = rf"## {re.escape(heading)}\s*\n+(.*?)(?=\n## |\Z)"
    m = re.search(pattern, content, re.DOTALL)
    if not m:
        return "(see full report)"
    text = m.group(1).strip()
    if max_chars and len(text) > max_chars:
        text = (
            text[:max_chars]
            + "\n\n_(truncated — see the CI artifact for details)_"
        )
    return text


def build_rca_comment(rca_content: str, client: PRCommentClient) -> str:
    """Build a compact PR comment body from the full RCA markdown.

    The returned string begins with ``client.marker`` so that
    :meth:`~common.pr_comment.PRCommentClient.post` can locate and update the
    comment on future runs.

    Args:
        rca_content: Full RCA report in markdown format.
        client: Configured :class:`~common.pr_comment.PRCommentClient` instance
            whose :attr:`~common.pr_comment.PRCommentClient.marker`,
            :attr:`~common.pr_comment.PRCommentClient.job`,
            :attr:`~common.pr_comment.PRCommentClient.run_number`, and
            :attr:`~common.pr_comment.PRCommentClient.run_url` are used.
    """
    run_label = f" · run #{client.run_number}" if client.run_number else ""

    classification = _extract_section(rca_content, "Failure Classification", 120)
    root_cause = _extract_section(rca_content, "Root Cause", 800)
    suggested_fix = _extract_section(rca_content, "Suggested Fix", 1_200)
    diff_section = _extract_section(rca_content, "Unified Diff", 1_500)

    parts: list[str] = [
        client.marker,
        f"## 🤖 AI Root Cause Analysis — `{client.job}`{run_label}",
        "",
        f"**Failure Classification:** {classification}",
        "",
        "### Root Cause",
        root_cause,
        "",
        "### Suggested Fix",
        suggested_fix,
    ]

    # Only include the diff block when it contains an actual patch
    if diff_section and not diff_section.startswith("N/A"):
        parts += ["", "### Patch", diff_section]

    if client.run_url:
        parts += ["", "---", f"_[View full RCA artifact]({client.run_url})_"]

    comment = "\n".join(parts)

    # Safety truncation to stay within GitHub's limit
    if len(comment) > _MAX_COMMENT_CHARS:
        comment = (
            comment[: _MAX_COMMENT_CHARS - 200]
            + "\n\n_(comment truncated — see the CI artifact for the full report)_"
        )

    return comment


def post_rca_pr_comment(rca_content: str) -> None:
    """Build and post (or update) the RCA summary as a GitHub PR comment."""
    client = PRCommentClient()
    body = build_rca_comment(rca_content, client)
    client.post(body)
