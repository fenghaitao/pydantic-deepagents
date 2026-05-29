"""Collect failure context for AI root cause analysis.

Gathers git diff, changed files, and relevant source file snippets
referenced in stack traces — while staying within token budget limits.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Token-budget limits (conservative chars-to-tokens ~4:1 assumption)
_MAX_DIFF_CHARS = 8_000
_MAX_FILE_CHARS = 3_500
_MAX_SOURCE_FILES = 10


@dataclass
class FailureContext:
    """Context gathered for AI RCA analysis."""

    git_diff: str = ""
    changed_files: list[str] = field(default_factory=list)
    # path (repo-relative) -> truncated file content
    source_snippets: dict[str, str] = field(default_factory=dict)


def _run(cmd: list[str], cwd: Path | None = None) -> str:
    """Run a shell command and return stdout; return '' on any error."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd,
        )
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def _truncate(text: str, max_chars: int, head_chars: int = 0) -> str:
    """Truncate text to max_chars, optionally preserving a leading head."""
    if len(text) <= max_chars:
        return text
    if head_chars > 0:
        head = text[:head_chars]
        remainder = max_chars - head_chars - 30
        tail = text[-max(remainder, 200):]
        return head + "\n...[truncated]...\n" + tail
    half = max_chars // 2
    return text[:half] + "\n...[truncated]...\n" + text[-half:]


# Code file extensions to include in git diff
_DIFF_EXTENSIONS = (
    "*.py",
    "*.ts",
    "*.js",
    "*.rs",
    "*.go",
    "*.c",
    "*.cpp",
    "*.h",
    "*.toml",
    "*.yaml",
    "*.yml",
)


def _get_git_diff(repo_root: Path) -> tuple[str, list[str]]:
    """Return (diff_content, changed_files_list).

    Tries HEAD first; falls back to HEAD~1 for detached-HEAD / fresh-branch CI
    where HEAD is the merge commit and HEAD~1 is the base.
    """
    diff_flags = ["--"] + list(_DIFF_EXTENSIONS)

    diff = _run(["git", "diff", "HEAD", *diff_flags], cwd=repo_root)
    changed = _run(
        ["git", "diff", "--name-only", "HEAD"], cwd=repo_root
    ).splitlines()

    if not diff.strip():
        diff = _run(
            ["git", "diff", "HEAD~1", "HEAD", *diff_flags], cwd=repo_root
        )
        changed = _run(
            ["git", "diff", "--name-only", "HEAD~1", "HEAD"], cwd=repo_root
        ).splitlines()

    changed_files = [f.strip() for f in changed if f.strip()]
    return _truncate(diff, _MAX_DIFF_CHARS, head_chars=2_000), changed_files


def _extract_file_refs(stack_traces: list[str]) -> list[str]:
    """Extract unique Python file paths from stack trace text."""
    refs: dict[str, None] = {}
    for trace in stack_traces:
        for line in trace.splitlines():
            line = line.strip()
            m = re.search(r'"([^"]+\.py)"', line)
            if m:
                refs[m.group(1)] = None
                continue
            m = re.search(r'([\w./][^\s"\']*\.py):\d+', line)
            if m:
                refs[m.group(1)] = None
    return list(refs)


def _load_snippet(path: Path, max_chars: int = _MAX_FILE_CHARS) -> str | None:
    """Load and truncate a source file; return None if unreadable."""
    try:
        content = path.read_text(errors="replace")
        return _truncate(content, max_chars)
    except (OSError, PermissionError):
        return None


def collect_failure_context(
    repo_root: Path,
    stack_traces: list[str],
    extra_changed_files: list[str] | None = None,
) -> FailureContext:
    """Collect the complete failure context for LLM analysis.

    Args:
        repo_root: Repository root (for git operations and relative paths).
        stack_traces: Raw stack trace strings extracted from JUnit failures.
        extra_changed_files: Additional file paths to include (e.g. from CI env).
    """
    ctx = FailureContext()

    # 1. Git diff + changed files
    ctx.git_diff, ctx.changed_files = _get_git_diff(repo_root)
    if extra_changed_files:
        # Prepend extra files, deduplicate preserving order
        combined = list(dict.fromkeys(extra_changed_files + ctx.changed_files))
        ctx.changed_files = combined

    # 2. Collect candidate source files
    candidates: list[Path] = []

    # Files referenced in stack traces (highest relevance)
    for ref in _extract_file_refs(stack_traces):
        p = Path(ref)
        if not p.is_absolute():
            p = repo_root / p
        if p.exists() and p.is_file():
            candidates.append(p)

    # Changed files (likely cause of the failure)
    for rel in ctx.changed_files[:6]:
        p = repo_root / rel
        if p.exists() and p.is_file():
            candidates.append(p)

    # 3. Deduplicate candidates by resolved path
    seen: set[str] = set()
    unique: list[Path] = []
    for p in candidates:
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(p)

    # 4. Load up to _MAX_SOURCE_FILES snippets
    for p in unique[:_MAX_SOURCE_FILES]:
        content = _load_snippet(p)
        if content is None:
            continue
        try:
            rel = str(p.relative_to(repo_root))
        except ValueError:
            rel = str(p)
        ctx.source_snippets[rel] = content

    return ctx
