"""Generic GitHub PR comment client for CI tooling.

Posts or updates a job-scoped comment on a GitHub pull request.  Each
comment is identified by a small HTML marker embedded in its body, so the
same comment is updated on every workflow re-run rather than accumulating
multiple comments.

Usage::

    from common.pr_comment import PRCommentClient

    client = PRCommentClient()
    body = f"{client.marker}\\n## My Report\\n..."
    client.post(body)
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class PRCommentClient:
    """GitHub PR comment client that posts or updates a job-scoped comment.

    Each instance is bound to a specific PR via environment variables (or
    explicit constructor arguments).  The :attr:`marker` HTML comment is
    embedded in the comment body and used to find an existing comment to
    update, rather than creating a new one on every CI run.

    Args:
        token: GitHub token with PR write access. Defaults to
            ``GITHUB_TOKEN`` env var.
        repo: ``owner/repo`` string. Defaults to ``GITHUB_REPOSITORY`` env var.
        pr_number: Pull request number. Defaults to ``PR_NUMBER`` env var
            (falls back to ``GITHUB_PR_NUMBER``).
        api_base: GitHub API base URL. Defaults to ``GITHUB_API_URL`` or
            ``https://api.github.com``.
        server_url: GitHub web URL. Defaults to ``GITHUB_SERVER_URL`` or
            ``https://github.com``.
        run_id: Actions run ID. Defaults to ``GITHUB_RUN_ID``.
        run_number: Human-readable run counter. Defaults to
            ``GITHUB_RUN_NUMBER``.
        job: Job identifier used in :attr:`marker`. Defaults to ``GITHUB_JOB``.
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        repo: str | None = None,
        pr_number: str | None = None,
        api_base: str | None = None,
        server_url: str | None = None,
        run_id: str | None = None,
        run_number: str | None = None,
        job: str | None = None,
    ) -> None:
        self._token = token or os.environ.get("GITHUB_TOKEN", "")
        self._repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
        self._pr_number = (
            pr_number
            or os.environ.get("PR_NUMBER")
            or os.environ.get("GITHUB_PR_NUMBER", "")
        )
        self._api_base = api_base or os.environ.get(
            "GITHUB_API_URL", "https://api.github.com"
        )
        self._server_url = server_url or os.environ.get(
            "GITHUB_SERVER_URL", "https://github.com"
        )
        self._run_id = run_id or os.environ.get("GITHUB_RUN_ID", "")
        self._run_number = run_number or os.environ.get("GITHUB_RUN_NUMBER", "")
        self._job = job or os.environ.get("GITHUB_JOB", "unknown")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def marker(self) -> str:
        """Job-scoped HTML comment marker used to identify this comment.

        Embed this string somewhere in the body you pass to :meth:`post` so
        future runs can find and update the same comment.
        """
        return f"<!-- ci-comment:{self._job} -->"

    @property
    def run_url(self) -> str:
        """Full GitHub Actions run URL, or empty string if unavailable."""
        if self._run_id and self._repo:
            return f"{self._server_url}/{self._repo}/actions/runs/{self._run_id}"
        return ""

    @property
    def run_number(self) -> str:
        """Human-readable run counter string (e.g. ``"42"``)."""
        return self._run_number

    @property
    def job(self) -> str:
        """Job identifier (value of ``GITHUB_JOB``)."""
        return self._job

    # ------------------------------------------------------------------
    # GitHub API helpers
    # ------------------------------------------------------------------

    def _github_request(
        self,
        url: str,
        *,
        method: str = "GET",
        body: dict | None = None,
    ) -> dict | list:
        """Make a GitHub API request and return the parsed JSON response."""
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        data: bytes | None = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"GitHub API {method} {url} returned {exc.code}: "
                f"{exc.read().decode(errors='replace')}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"GitHub API request failed: {exc}") from exc

    def _find_existing_comment(self) -> int | None:
        """Return the comment ID containing :attr:`marker`, or ``None``."""
        url = (
            f"{self._api_base}/repos/{self._repo}/issues/"
            f"{self._pr_number}/comments?per_page=100"
        )
        try:
            comments = self._github_request(url)
            if isinstance(comments, list):
                for comment in comments:
                    if self.marker in comment.get("body", ""):
                        return int(comment["id"])
        except RuntimeError as exc:
            print(f"WARNING: Could not fetch existing PR comments: {exc}")
        return None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def post(self, body: str) -> None:
        """Post or update a PR comment.

        The *body* must contain :attr:`marker` so that future runs can find
        and update the same comment instead of creating a new one.

        Silently skips posting when required credentials or PR context are
        missing (e.g., on push events that have no associated PR).
        """
        if not all([self._token, self._repo, self._pr_number]):
            print(
                "WARNING: GITHUB_TOKEN, GITHUB_REPOSITORY, or PR_NUMBER not set — "
                "skipping PR comment."
            )
            return

        existing_id = self._find_existing_comment()
        comments_url = (
            f"{self._api_base}/repos/{self._repo}/issues/"
            f"{self._pr_number}/comments"
        )

        try:
            if existing_id:
                patch_url = (
                    f"{self._api_base}/repos/{self._repo}/issues/"
                    f"comments/{existing_id}"
                )
                self._github_request(patch_url, method="PATCH", body={"body": body})
                print(f"PR comment updated (id={existing_id}).")
            else:
                self._github_request(comments_url, method="POST", body={"body": body})
                print("PR comment posted.")
        except RuntimeError as exc:
            print(f"WARNING: Could not post PR comment: {exc}")
