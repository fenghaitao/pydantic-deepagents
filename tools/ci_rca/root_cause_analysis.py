#!/usr/bin/env python3
"""AI-powered root cause analysis for CI test failures.

Usage (called by GitHub Actions on test failure):

    uv run --no-sync python tools/ci_rca/root_cause_analysis.py \\
        --junit-dir test-results \\
        [--junit-dir code-graph-providers/potpie/test-results] \\
        --output test-results/ai-root-cause-analysis.md \\
        [--pr-comment]

The script NEVER exits with a non-zero code so it cannot fail the CI pipeline.
"""
from __future__ import annotations

import argparse
import os
import sys
import textwrap
from pathlib import Path

# Allow importing from tools/common and tools/ci_rca packages when executed
# directly as a script (python tools/ci_rca/root_cause_analysis.py).
_tools_dir = str(Path(__file__).parent.parent)
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

from ci_rca.collect_context import FailureContext, collect_failure_context  # noqa: E402
from ci_rca.comment import post_rca_pr_comment  # noqa: E402
from ci_rca.parse_junit import JUnitSummary, collect_junit_failures  # noqa: E402
from ci_rca.prompts import SYSTEM_PROMPT, build_user_prompt  # noqa: E402
from common.llm_client import LLMClient, LLMError  # noqa: E402


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_junit_summary(summary: JUnitSummary) -> str:
    """Render a JUnit summary as a compact markdown block for the prompt."""
    if not summary.failed_tests and summary.total == 0:
        return "(no JUnit data available)"

    header = (
        f"**Total:** {summary.total}  "
        f"**Failures:** {summary.failures}  "
        f"**Errors:** {summary.errors}  "
        f"**Skipped:** {summary.skipped}  "
        f"**Duration:** {summary.duration:.1f}s"
    )
    lines: list[str] = [header, ""]

    # Cap at 10 failures to avoid blowing the context window
    for i, ft in enumerate(summary.failed_tests[:10]):
        lines.append(f"### Failure {i + 1}: `{ft.classname}::{ft.test_name}`")
        lines.append(
            f"**Type:** {ft.failure_type}  **Duration:** {ft.duration:.2f}s"
        )
        if ft.message:
            lines.append(f"**Message:** {ft.message}")
        if ft.text:
            lines.append(f"```\n{ft.text}\n```")
        lines.append("")

    overflow = len(summary.failed_tests) - 10
    if overflow > 0:
        lines.append(f"_…and {overflow} more failure(s) not shown._")

    return "\n".join(lines)


def _fallback_report(junit_text: str, reason: str) -> str:
    """Generate a minimal RCA report when the LLM is unavailable."""
    return textwrap.dedent(f"""\
        # AI Root Cause Analysis

        ## Failure Classification
        Unknown

        ## Root Cause
        AI analysis was unavailable.

        ```
        {reason}
        ```

        ## Technical Analysis
        {junit_text}

        ## Suggested Fix
        Review the failing tests manually.

        ## Unified Diff
        ```diff
        N/A — AI analysis unavailable
        ```
    """)


# ---------------------------------------------------------------------------
# Core RCA logic
# ---------------------------------------------------------------------------


def run_rca(
    junit_dirs: list[Path],
    output_path: Path,
    repo_root: Path,
    pr_comment: bool = False,
) -> None:
    """Orchestrate the full RCA pipeline and write the markdown report."""
    print("=== AI Root Cause Analysis ===")

    # Step 1: Parse JUnit results
    print(f"Scanning JUnit XML files in: {[str(d) for d in junit_dirs]}")
    summary = collect_junit_failures(junit_dirs)
    print(
        f"Found {len(summary.failed_tests)} failed test(s) "
        f"({summary.failures} failure(s), {summary.errors} error(s))"
    )

    if not summary.failed_tests:
        print("No failures found in JUnit XML — writing placeholder report.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            "# AI Root Cause Analysis\n\nNo test failures detected in JUnit output.\n"
        )
        return

    junit_text = _format_junit_summary(summary)

    # Step 2: Collect context (git diff, source files)
    print("Collecting failure context…")
    ctx: FailureContext = collect_failure_context(
        repo_root=repo_root,
        stack_traces=[ft.text for ft in summary.failed_tests],
    )
    print(f"  Git diff: {len(ctx.git_diff):,} chars")
    print(f"  Changed files: {ctx.changed_files[:10]}")
    print(f"  Source snippets loaded: {list(ctx.source_snippets)}")

    # Step 3: Build prompt
    user_prompt = build_user_prompt(
        junit_summary_text=junit_text,
        git_diff=ctx.git_diff,
        source_snippets=ctx.source_snippets,
        changed_files=ctx.changed_files,
    )

    # Step 4: Call LLM — read model from env so it can be overridden per workflow
    model = os.environ.get("RCA_MODEL", "").strip() or "gpt-4o"
    llm = LLMClient(model=model)

    print(f"Invoking LLM ({model}) for root cause analysis…")
    try:
        rca_content = llm.complete(SYSTEM_PROMPT, user_prompt)
        print("LLM analysis complete.")
    except LLMError as exc:
        print(f"WARNING: LLM call failed — writing fallback report. Reason: {exc}")
        rca_content = _fallback_report(junit_text, str(exc))

    # Step 5: Write report
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rca_content)
    print(f"RCA report written to: {output_path}")

    # Step 6: Optional PR comment
    if pr_comment:
        try:
            post_rca_pr_comment(rca_content)
        except Exception as exc:  # pragma: no cover
            print(f"WARNING: Failed to post PR comment: {exc}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="AI-powered root cause analysis for CI test failures."
    )
    p.add_argument(
        "--junit-dir",
        action="append",
        dest="junit_dirs",
        metavar="DIR",
        default=[],
        help=(
            "Directory to scan for JUnit XML files. "
            "May be specified multiple times."
        ),
    )
    p.add_argument(
        "--output",
        default="test-results/ai-root-cause-analysis.md",
        help="Output path for the RCA markdown report.",
    )
    p.add_argument(
        "--repo-root",
        default=".",
        help="Repository root (used for git operations and relative paths).",
    )
    p.add_argument(
        "--pr-comment",
        action="store_true",
        help="Post RCA summary as a PR comment (requires GITHUB_TOKEN).",
    )
    return p


def main() -> int:
    args = _build_arg_parser().parse_args()

    junit_dirs = (
        [Path(d) for d in args.junit_dirs]
        if args.junit_dirs
        else [Path("test-results")]
    )
    output_path = Path(args.output)
    repo_root = Path(args.repo_root).resolve()

    try:
        run_rca(
            junit_dirs=junit_dirs,
            output_path=output_path,
            repo_root=repo_root,
            pr_comment=args.pr_comment,
        )
    except Exception as exc:
        print(f"WARNING: AI RCA encountered an unexpected error: {exc}")
        # Write a minimal report so the artifact upload step has something
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            f"# AI Root Cause Analysis\n\n"
            f"RCA tool encountered an unexpected error: {exc}\n"
        )

    # Always exit 0 — the RCA system must never fail the CI pipeline
    return 0


if __name__ == "__main__":
    sys.exit(main())
