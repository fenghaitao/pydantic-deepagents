"""Generic GitHub Copilot LLM client for CI tooling.

Uses ``urllib.request`` (stdlib only) so Python's ssl module is used directly.
``ssl.create_default_context()`` respects ``SSL_CERT_FILE`` on Linux, which is
set globally in the workflow to the Intel proxy CA bundle.

Usage::

    from common.llm_client import LLMClient, LLMError

    client = LLMClient(model="gpt-4o")
    response = client.complete(system="You are...", user="Analyse...")
"""
from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request


class LLMError(Exception):
    """Raised when all LLM call attempts have failed."""


class LLMClient:
    """GitHub Copilot LLM client with exponential-backoff retry.

    Args:
        token: GitHub Copilot OAuth token. Defaults to the
            ``COPILOT_GITHUB_TOKEN`` environment variable.
        model: Copilot model ID (without provider prefix). Default: ``"gpt-4o"``.
        retries: Number of attempts before raising :class:`LLMError`.
        retry_delay: Base delay in seconds between retries (multiplied by
            attempt number to give linear back-off).
        timeout: HTTP read timeout in seconds per request.
        max_tokens: Maximum tokens in the model response.
    """

    _ENDPOINT = "https://api.githubcopilot.com/chat/completions"
    _EDITOR_VERSION = "vscode/1.85.1"
    _INTEGRATION_ID = "vscode-chat"

    def __init__(
        self,
        *,
        token: str | None = None,
        model: str = "gpt-4o",
        retries: int = 3,
        retry_delay: float = 5.0,
        timeout: int = 120,
        max_tokens: int = 2048,
    ) -> None:
        self._token = token or os.environ.get("COPILOT_GITHUB_TOKEN", "")
        self._model = model
        self._retries = retries
        self._retry_delay = retry_delay
        self._timeout = timeout
        self._max_tokens = max_tokens

    @staticmethod
    def _ssl_context() -> ssl.SSLContext:
        """Return an SSL context that trusts the Intel proxy CA when configured.

        ``ssl.create_default_context()`` on Linux already reads
        ``SSL_CERT_FILE``, but we also call ``load_verify_locations()``
        explicitly so the CA bundle is used even if the env var is picked up
        differently on unusual runner configurations.
        """
        ctx = ssl.create_default_context()
        ca_bundle = (
            os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
        )
        if ca_bundle:
            ctx.load_verify_locations(ca_bundle)
        return ctx

    def _call_once(self, system: str, user: str) -> str:
        """Make a single API call to GitHub Copilot. Raises :class:`LLMError`."""
        if not self._token:
            raise LLMError(
                "COPILOT_GITHUB_TOKEN is not set. "
                "Pass it via secrets.COPILOT_GITHUB_TOKEN in the workflow."
            )

        # Strip any LiteLLM-style "provider/" prefix from the model name
        model_id = self._model.split("/", 1)[-1] if "/" in self._model else self._model

        payload = json.dumps(
            {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": self._max_tokens,
                "stream": False,
            }
        ).encode()

        req = urllib.request.Request(
            self._ENDPOINT,
            data=payload,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "Editor-Version": self._EDITOR_VERSION,
                "Copilot-Integration-Id": self._INTEGRATION_ID,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                req, context=self._ssl_context(), timeout=self._timeout
            ) as resp:
                result = json.loads(resp.read())
                return result["choices"][0]["message"]["content"] or ""
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")[:400]
            raise LLMError(
                f"Copilot API call failed (HTTP {exc.code}): {body}"
            ) from exc
        except Exception as exc:
            raise LLMError(f"Copilot API error: {exc}") from exc

    def complete(self, system: str, user: str) -> str:
        """Call GitHub Copilot with linear back-off retry.

        Returns the model's text response.
        Raises :class:`LLMError` if all attempts fail.
        """
        last_error: Exception | None = None

        for attempt in range(self._retries):
            if attempt > 0:
                delay = self._retry_delay * attempt
                print(
                    f"  Retrying in {delay:.0f}s "
                    f"(attempt {attempt + 1}/{self._retries})…"
                )
                time.sleep(delay)

            try:
                return self._call_once(system, user)
            except LLMError as exc:
                last_error = exc
                print(
                    f"WARNING: LLM attempt {attempt + 1}/{self._retries} "
                    f"failed: {exc}"
                )

        raise LLMError(
            f"All {self._retries} LLM attempts failed. Last error: {last_error}"
        )
