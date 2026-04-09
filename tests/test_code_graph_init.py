"""Tests for pydantic_deep.toolsets.code_graph.__init__ (make_backend factory)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pydantic_deep.toolsets.code_graph import make_backend
from pydantic_deep.toolsets.code_graph.backend import PotpieBackend


def _make_config(
    potpie_mode: str = "rest",
    potpie_url: str | None = None,
    potpie_api_key: str | None = None,
) -> MagicMock:
    cfg = MagicMock()
    cfg.potpie_mode = potpie_mode
    cfg.potpie_url = potpie_url
    cfg.potpie_api_key = potpie_api_key
    return cfg


class TestMakeBackend:
    def test_local_mode_returns_runtime_backend(self) -> None:
        cfg = _make_config(potpie_mode="local")
        with patch(
            "pydantic_deep.toolsets.code_graph.runtime_backend.RuntimeBackend"
        ) as mock_cls:
            mock_cls.return_value = MagicMock(spec=PotpieBackend)
            backend = make_backend(cfg)
            mock_cls.assert_called_once()
            assert backend is mock_cls.return_value

    def test_rest_mode_with_explicit_url(self) -> None:
        cfg = _make_config(potpie_mode="rest", potpie_url="http://localhost:8001", potpie_api_key="key")
        with patch(
            "pydantic_deep.toolsets.code_graph.rest_backend.RestBackend"
        ) as mock_cls:
            mock_cls.return_value = MagicMock(spec=PotpieBackend)
            backend = make_backend(cfg)
            mock_cls.assert_called_once_with(base_url="http://localhost:8001", api_key="key")
            assert backend is mock_cls.return_value

    def test_rest_mode_discovers_url_when_none_configured(self) -> None:
        cfg = _make_config(potpie_mode="rest", potpie_url=None, potpie_api_key=None)
        with (
            patch(
                "apps.cli.potpie_discovery.discover_potpie_url",
                return_value="http://localhost:9000",
            ),
            patch(
                "pydantic_deep.toolsets.code_graph.rest_backend.RestBackend"
            ) as mock_cls,
        ):
            mock_cls.return_value = MagicMock(spec=PotpieBackend)
            backend = make_backend(cfg)
            mock_cls.assert_called_once_with(base_url="http://localhost:9000", api_key="")
            assert backend is mock_cls.return_value

    def test_rest_mode_raises_when_no_url_and_discovery_fails(self) -> None:
        cfg = _make_config(potpie_mode="rest", potpie_url=None)
        with patch(
            "apps.cli.potpie_discovery.discover_potpie_url",
            return_value=None,
        ):
            with pytest.raises(ValueError, match="Cannot connect to potpie"):
                make_backend(cfg)

    def test_rest_mode_empty_api_key_defaults_to_empty_string(self) -> None:
        cfg = _make_config(potpie_mode="rest", potpie_url="http://localhost:8001", potpie_api_key=None)
        with patch(
            "pydantic_deep.toolsets.code_graph.rest_backend.RestBackend"
        ) as mock_cls:
            mock_cls.return_value = MagicMock(spec=PotpieBackend)
            make_backend(cfg)
            mock_cls.assert_called_once_with(base_url="http://localhost:8001", api_key="")
