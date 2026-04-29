"""Tests for the ``pydantic-deep spec index`` CLI command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from apps.cli.main import app

runner = CliRunner()


def _make_runtime(
    *,
    projects: list[dict] | None = None,
    register_result: dict | None = None,
    insert_result: dict | None = None,
    query_result: str = "the answer",
) -> MagicMock:
    rt = MagicMock()
    rt.list_projects = AsyncMock(return_value=projects or [])
    rt.register_project = AsyncMock(return_value=register_result or {"project_id": "new-id"})
    rt.spec_insert_texts = AsyncMock(
        return_value=insert_result
        or {"inserted": 1, "workspace": "defaultuser__new-id"}
    )
    rt.spec_query = AsyncMock(return_value=query_result)
    return rt


def _patch_runtime(rt: MagicMock):
    return patch("apps.cli.main._make_code_graph_runtime", return_value=rt)


class TestSpecIndexValidation:
    """Argument-validation paths that don't require a runtime call."""

    def test_requires_project_name_or_id(self, tmp_path: Path) -> None:
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# spec\n")

        result = runner.invoke(app, ["spec", "index", "--path", str(spec_file)])
        assert result.exit_code == 1
        assert "specify at least one" in (result.output + (result.stderr or "")).lower()

    def test_path_option_is_required(self) -> None:
        # No --path provided → typer should refuse and exit non-zero.
        result = runner.invoke(app, ["spec", "index", "--project-name", "p"])
        assert result.exit_code != 0

    def test_help_lists_index(self) -> None:
        result = runner.invoke(app, ["spec", "--help"])
        assert result.exit_code == 0
        assert "index" in result.output


class TestSpecIndexByName:
    def test_indexes_existing_project(self, tmp_path: Path) -> None:
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Hello\nSome content.\n")

        rt = _make_runtime(
            projects=[{"id": "abc-123", "repo_name": "myproj"}],
            insert_result={"inserted": 1, "workspace": "defaultuser__abc-123"},
        )

        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "index", "--path", str(spec_file), "--project-name", "myproj"],
            )

        assert result.exit_code == 0, result.output
        rt.register_project.assert_not_awaited()
        rt.spec_insert_texts.assert_awaited_once()
        kwargs = rt.spec_insert_texts.await_args.kwargs
        assert kwargs["project_id"] == "abc-123"
        assert kwargs["user_id"] == "defaultuser"
        assert kwargs["texts"] and "Hello" in kwargs["texts"][0]
        assert "abc-123" in result.output
        assert "Done." in result.output

    def test_auto_registers_when_name_missing(self, tmp_path: Path) -> None:
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("body\n")

        rt = _make_runtime(
            projects=[],
            register_result={"project_id": "fresh-id"},
            insert_result={"inserted": 1, "workspace": "defaultuser__fresh-id"},
        )

        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "index", "--path", str(spec_file), "--project-name", "brand-new"],
            )

        assert result.exit_code == 0, result.output
        rt.register_project.assert_awaited_once_with(project_name="brand-new")
        kwargs = rt.spec_insert_texts.await_args.kwargs
        assert kwargs["project_id"] == "fresh-id"
        assert "fresh-id" in result.output

    def test_register_failure_exits_one(self, tmp_path: Path) -> None:
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("hi\n")

        rt = _make_runtime(projects=[], register_result={"project_id": ""})
        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "index", "--path", str(spec_file), "--project-name", "x"],
            )
        assert result.exit_code == 1
        assert "Failed to register" in result.output
        rt.spec_insert_texts.assert_not_awaited()

    def test_name_and_id_mismatch_errors(self, tmp_path: Path) -> None:
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("hi\n")

        rt = _make_runtime(projects=[{"id": "real-id", "repo_name": "myproj"}])
        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                [
                    "spec", "index",
                    "--path", str(spec_file),
                    "--project-name", "myproj",
                    "--project-id", "wrong-id",
                ],
            )
        assert result.exit_code == 1
        assert "does not match" in result.output
        rt.spec_insert_texts.assert_not_awaited()


class TestSpecIndexById:
    def test_indexes_by_existing_id(self, tmp_path: Path) -> None:
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("doc\n")

        rt = _make_runtime(
            projects=[{"id": "pid-9", "repo_name": "anything"}],
            insert_result={"inserted": 1, "workspace": "defaultuser__pid-9"},
        )
        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "index", "--path", str(spec_file), "--project-id", "pid-9"],
            )
        assert result.exit_code == 0, result.output
        rt.register_project.assert_not_awaited()
        kwargs = rt.spec_insert_texts.await_args.kwargs
        assert kwargs["project_id"] == "pid-9"

    def test_unknown_id_errors(self, tmp_path: Path) -> None:
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("doc\n")

        rt = _make_runtime(projects=[{"id": "other", "repo_name": "x"}])
        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "index", "--path", str(spec_file), "--project-id", "missing"],
            )
        assert result.exit_code == 1
        assert "not found" in result.output
        rt.spec_insert_texts.assert_not_awaited()


class TestSpecIndexFileCollection:
    def test_collects_from_directory(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("alpha\n")
        (tmp_path / "b.md").write_text("beta\n")
        (tmp_path / "c.txt").write_text("gamma\n")

        rt = _make_runtime(projects=[{"id": "id1", "repo_name": "p"}])
        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                [
                    "spec", "index",
                    "--path", str(tmp_path),
                    "--project-name", "p",
                    "--ext", "md",
                ],
            )
        assert result.exit_code == 0, result.output
        kwargs = rt.spec_insert_texts.await_args.kwargs
        assert len(kwargs["texts"]) == 2
        joined = "\n".join(kwargs["texts"])
        assert "alpha" in joined and "beta" in joined
        assert "gamma" not in joined

    def test_multiple_paths(self, tmp_path: Path) -> None:
        f1 = tmp_path / "one.md"
        f2 = tmp_path / "two.md"
        f1.write_text("one\n")
        f2.write_text("two\n")

        rt = _make_runtime(projects=[{"id": "id1", "repo_name": "p"}])
        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                [
                    "spec", "index",
                    "--path", str(f1),
                    "--path", str(f2),
                    "--project-name", "p",
                ],
            )
        assert result.exit_code == 0, result.output
        kwargs = rt.spec_insert_texts.await_args.kwargs
        assert kwargs["file_paths"] == [str(f1), str(f2)]
        assert len(kwargs["texts"]) == 2

    def test_no_matching_files_errors(self, tmp_path: Path) -> None:
        (tmp_path / "ignore.txt").write_text("nope\n")

        rt = _make_runtime(projects=[{"id": "id1", "repo_name": "p"}])
        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                [
                    "spec", "index",
                    "--path", str(tmp_path),
                    "--project-name", "p",
                    "--ext", "md",
                ],
            )
        assert result.exit_code == 1
        assert "No readable files" in result.output
        rt.spec_insert_texts.assert_not_awaited()


class TestSpecIndexOptions:
    def test_custom_user_id_and_prompt(self, tmp_path: Path) -> None:
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("doc\n")

        rt = _make_runtime(projects=[{"id": "id1", "repo_name": "p"}])
        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                [
                    "spec", "index",
                    "--path", str(spec_file),
                    "--project-name", "p",
                    "--user-id", "alice",
                    "--prompt", "extract entities",
                ],
            )
        assert result.exit_code == 0, result.output
        kwargs = rt.spec_insert_texts.await_args.kwargs
        assert kwargs["user_id"] == "alice"
        assert kwargs["prompt"] == "extract entities"


class TestSpecQueryValidation:
    def test_requires_project_name_or_id(self) -> None:
        result = runner.invoke(app, ["spec", "query", "what is X?"])
        assert result.exit_code == 1
        assert "specify at least one" in (result.output + (result.stderr or "")).lower()

    def test_requires_query_text_when_not_summarize(self) -> None:
        result = runner.invoke(app, ["spec", "query", "--project-id", "pid"])
        assert result.exit_code == 1
        assert "query text is required" in (result.output + (result.stderr or "")).lower()

    def test_invalid_mode_errors(self) -> None:
        result = runner.invoke(
            app,
            ["spec", "query", "what?", "--project-id", "pid", "--mode", "bogus"],
        )
        assert result.exit_code == 1
        assert "--mode must be one of" in (result.output + (result.stderr or "")).lower()

    def test_help_lists_query(self) -> None:
        result = runner.invoke(app, ["spec", "--help"])
        assert result.exit_code == 0
        assert "query" in result.output


class TestSpecQueryByName:
    def test_queries_existing_project(self) -> None:
        rt = _make_runtime(
            projects=[{"id": "abc-123", "repo_name": "myproj"}],
            query_result="ANSWER-TEXT",
        )
        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "query", "what?", "--project-name", "myproj"],
            )
        assert result.exit_code == 0, result.output
        rt.spec_query.assert_awaited_once()
        kwargs = rt.spec_query.await_args.kwargs
        assert kwargs["project_id"] == "abc-123"
        assert kwargs["query"] == "what?"
        assert kwargs["mode"] == "hybrid"
        assert kwargs["summarize"] is False
        assert kwargs["user_id"] == "defaultuser"
        assert "ANSWER-TEXT" in result.output

    def test_unknown_name_errors(self) -> None:
        rt = _make_runtime(projects=[{"id": "x", "repo_name": "other"}])
        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "query", "what?", "--project-name", "missing"],
            )
        assert result.exit_code == 1
        assert "not found" in result.output
        rt.spec_query.assert_not_awaited()

    def test_name_and_id_mismatch_errors(self) -> None:
        rt = _make_runtime(projects=[{"id": "real-id", "repo_name": "myproj"}])
        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                [
                    "spec", "query", "what?",
                    "--project-name", "myproj",
                    "--project-id", "wrong-id",
                ],
            )
        assert result.exit_code == 1
        assert "does not match" in result.output
        rt.spec_query.assert_not_awaited()


class TestSpecQueryById:
    def test_queries_by_id_skips_lookup(self) -> None:
        rt = _make_runtime(query_result="hello")
        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "query", "ping", "--project-id", "pid-9"],
            )
        assert result.exit_code == 0, result.output
        rt.list_projects.assert_not_awaited()
        kwargs = rt.spec_query.await_args.kwargs
        assert kwargs["project_id"] == "pid-9"
        assert kwargs["query"] == "ping"


class TestSpecQueryOptions:
    def test_summarize_without_query_text(self) -> None:
        rt = _make_runtime(query_result="summary")
        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "query", "--project-id", "pid", "--summarize"],
            )
        assert result.exit_code == 0, result.output
        kwargs = rt.spec_query.await_args.kwargs
        assert kwargs["summarize"] is True
        assert kwargs["query"] == ""

    def test_custom_mode_and_user_id(self) -> None:
        rt = _make_runtime(query_result="ok")
        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                [
                    "spec", "query", "what?",
                    "--project-id", "pid",
                    "--mode", "naive",
                    "--user-id", "alice",
                ],
            )
        assert result.exit_code == 0, result.output
        kwargs = rt.spec_query.await_args.kwargs
        assert kwargs["mode"] == "naive"
        assert kwargs["user_id"] == "alice"

    def test_all_valid_modes_accepted(self) -> None:
        for m in ("local", "global", "hybrid", "mix", "naive", "bypass"):
            rt = _make_runtime(query_result="ok")
            with _patch_runtime(rt):
                result = runner.invoke(
                    app,
                    ["spec", "query", "q", "--project-id", "pid", "--mode", m],
                )
            assert result.exit_code == 0, f"mode={m}: {result.output}"
            assert rt.spec_query.await_args.kwargs["mode"] == m


# ---------------------------------------------------------------------------
# Direct PotpieRuntime tests for the spec/* methods invoked by the CLI.
#
# The CLI tests above mock ``_make_code_graph_runtime`` so they don't exercise
# ``PotpieRuntime.register_project`` / ``spec_insert_texts`` / ``spec_query`` /
# ``spec_diff`` themselves.  These tests cover those bodies by calling them
# directly with potpie/lightrag service modules patched via ``sys.modules``.
# ---------------------------------------------------------------------------


def _potpie_modules_for_runtime(mock_rt: MagicMock) -> dict[str, MagicMock]:
    mock_potpie = MagicMock()
    mock_potpie.PotpieRuntime = MagicMock(from_env=MagicMock(return_value=mock_rt))
    return {"potpie": mock_potpie}


def _make_potpie_runtime_mock() -> MagicMock:
    rt = AsyncMock()
    rt.db.get_session.return_value = MagicMock()
    rt.projects.register = AsyncMock(return_value="proj-new")
    rt.close = AsyncMock()
    return rt


class TestPotpieRuntimeRegisterProject:
    async def test_register_project_default_branch(self) -> None:
        from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

        b = PotpieRuntime(user_id="alice")
        mock_rt = _make_potpie_runtime_mock()
        mock_rt.projects.register = AsyncMock(return_value="proj-xyz")

        with patch.dict("sys.modules", _potpie_modules_for_runtime(mock_rt)):
            result = await b.register_project(project_name="brand-new")

        assert result == {"project_id": "proj-xyz", "status": "REGISTERED"}
        mock_rt.projects.register.assert_awaited_once_with(
            repo_name="brand-new",
            branch_name="main",
            user_id="alice",
            repo_path=None,
            commit_id=None,
        )

    async def test_register_project_custom_branch(self) -> None:
        from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

        b = PotpieRuntime()
        mock_rt = _make_potpie_runtime_mock()
        mock_rt.projects.register = AsyncMock(return_value="proj-abc")

        with patch.dict("sys.modules", _potpie_modules_for_runtime(mock_rt)):
            result = await b.register_project(project_name="proj", branch="dev")

        assert result == {"project_id": "proj-abc", "status": "REGISTERED"}
        assert mock_rt.projects.register.await_args.kwargs["branch_name"] == "dev"


class TestPotpieRuntimeSpecLightRAG:
    async def test_spec_insert_texts(self) -> None:
        from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

        b = PotpieRuntime()

        mock_svc = MagicMock()
        mock_svc.insert_texts = AsyncMock(return_value={"inserted": 2, "workspace": "ws-1"})
        mock_ingest_cls = MagicMock(from_config=MagicMock(return_value=mock_svc))
        mock_ingest_mod = MagicMock(LightRAGIngestService=mock_ingest_cls)

        mock_provider = MagicMock()
        mock_provider.get_neo4j_config = MagicMock(return_value={"uri": "bolt://x"})
        mock_config_mod = MagicMock(config_provider=mock_provider)

        with patch.dict("sys.modules", {
            "app.core.config_provider": mock_config_mod,
            "app.modules.parsing.lightrag_sync.lightrag_ingest_service": mock_ingest_mod,
        }):
            result = await b.spec_insert_texts(
                project_id="p1",
                user_id="u1",
                texts=["doc-a", "doc-b"],
                file_paths=["a.md", "b.md"],
                prompt="extract entities",
            )

        assert result == {"inserted": 2, "workspace": "ws-1"}
        mock_ingest_cls.from_config.assert_called_once_with({"uri": "bolt://x"})
        mock_svc.insert_texts.assert_awaited_once_with(
            project_id="p1",
            user_id="u1",
            texts=["doc-a", "doc-b"],
            file_paths=["a.md", "b.md"],
            prompt="extract entities",
        )

    async def test_spec_query(self) -> None:
        from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

        b = PotpieRuntime()

        mock_svc = MagicMock()
        mock_svc.query = AsyncMock(return_value="answer")
        mock_query_mod = MagicMock(LightRAGQueryService=MagicMock(return_value=mock_svc))

        with patch.dict("sys.modules", {
            "app.modules.parsing.lightrag_sync.lightrag_query_service": mock_query_mod,
        }):
            result = await b.spec_query(
                project_id="p1",
                user_id="u1",
                query="what registers exist?",
                mode="local",
                summarize=True,
            )

        assert result == "answer"
        mock_svc.query.assert_awaited_once_with(
            project_id="p1",
            user_id="u1",
            question="what registers exist?",
            mode="local",
            summarize=True,
        )

    async def test_spec_query_default_mode(self) -> None:
        from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

        b = PotpieRuntime()

        mock_svc = MagicMock()
        mock_svc.query = AsyncMock(return_value="ok")
        mock_query_mod = MagicMock(LightRAGQueryService=MagicMock(return_value=mock_svc))

        with patch.dict("sys.modules", {
            "app.modules.parsing.lightrag_sync.lightrag_query_service": mock_query_mod,
        }):
            await b.spec_query(project_id="p1", user_id="u1", query="q")

        kwargs = mock_svc.query.await_args.kwargs
        assert kwargs["mode"] == "hybrid"
        assert kwargs["summarize"] is False

    async def test_spec_diff(self) -> None:
        from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

        b = PotpieRuntime()

        mock_svc = MagicMock()
        mock_svc.diff = AsyncMock(return_value="delta-narration")
        mock_query_mod = MagicMock(LightRAGQueryService=MagicMock(return_value=mock_svc))

        with patch.dict("sys.modules", {
            "app.modules.parsing.lightrag_sync.lightrag_query_service": mock_query_mod,
        }):
            result = await b.spec_diff(
                project_id_a="p-a",
                project_id_b="p-b",
                user_id="u1",
                mode="mix",
                summarize=True,
            )

        assert result == "delta-narration"
        mock_svc.diff.assert_awaited_once_with(
            user_id="u1",
            project_id_a="p-a",
            project_id_b="p-b",
            mode="mix",
            summarize=True,
        )

    async def test_spec_diff_defaults(self) -> None:
        from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

        b = PotpieRuntime()

        mock_svc = MagicMock()
        mock_svc.diff = AsyncMock(return_value="")
        mock_query_mod = MagicMock(LightRAGQueryService=MagicMock(return_value=mock_svc))

        with patch.dict("sys.modules", {
            "app.modules.parsing.lightrag_sync.lightrag_query_service": mock_query_mod,
        }):
            await b.spec_diff(project_id_a="a", project_id_b="b", user_id="u1")

        kwargs = mock_svc.diff.await_args.kwargs
        assert kwargs["mode"] == "hybrid"
        assert kwargs["summarize"] is False
