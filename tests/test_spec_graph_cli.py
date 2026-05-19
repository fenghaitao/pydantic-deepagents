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
    list_docs_result: list[dict] | None = None,
    delete_doc_result: dict | None = None,
    purge_query_cache_result: int = 0,
) -> MagicMock:
    rt = MagicMock()
    rt.list_projects = AsyncMock(return_value=projects or [])
    rt.register_project = AsyncMock(return_value=register_result or {"project_id": "new-id"})
    rt.spec_insert_texts = AsyncMock(
        return_value=insert_result
        or {"inserted": 1, "workspace": "defaultuser__new-id"}
    )
    rt.spec_query = AsyncMock(return_value=query_result)
    rt.spec_list_docs = AsyncMock(return_value=list_docs_result if list_docs_result is not None else [])
    rt.spec_delete_doc = AsyncMock(
        return_value=delete_doc_result
        or {"status": "success", "doc_id": "doc-abc", "message": "Deleted.", "status_code": 200, "file_path": "foo.md"}
    )
    rt.spec_purge_query_cache = AsyncMock(return_value=purge_query_cache_result)
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


# ---------------------------------------------------------------------------
# spec index — query-cache purge after insertion
# ---------------------------------------------------------------------------


class TestSpecIndexPurgesQueryCache:
    def test_purges_query_cache_after_insert(self, tmp_path: Path) -> None:
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("content\n")

        rt = _make_runtime(
            projects=[{"id": "proj-1", "repo_name": "myproj"}],
            insert_result={"inserted": 1, "workspace": "defaultuser__proj-1"},
            purge_query_cache_result=0,
        )

        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "index", "--path", str(spec_file), "--project-name", "myproj"],
            )

        assert result.exit_code == 0, result.output
        rt.spec_purge_query_cache.assert_awaited_once_with(
            project_id="proj-1",
            user_id="defaultuser",
        )

    def test_prints_purge_count_when_nonzero(self, tmp_path: Path) -> None:
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("content\n")

        rt = _make_runtime(
            projects=[{"id": "proj-1", "repo_name": "myproj"}],
            insert_result={"inserted": 1, "workspace": "defaultuser__proj-1"},
            purge_query_cache_result=5,
        )

        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "index", "--path", str(spec_file), "--project-name", "myproj"],
            )

        assert result.exit_code == 0, result.output
        assert "5" in result.output
        assert "stale query-cache" in result.output.lower() or "purged" in result.output.lower()

    def test_silent_when_nothing_purged(self, tmp_path: Path) -> None:
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("content\n")

        rt = _make_runtime(
            projects=[{"id": "proj-1", "repo_name": "myproj"}],
            insert_result={"inserted": 1, "workspace": "defaultuser__proj-1"},
            purge_query_cache_result=0,
        )

        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "index", "--path", str(spec_file), "--project-name", "myproj"],
            )

        assert result.exit_code == 0, result.output
        assert "Purged 0" not in result.output


# ---------------------------------------------------------------------------
# spec list — validation, lookup, and output
# ---------------------------------------------------------------------------


_SAMPLE_DOC = {
    "doc_id": "doc-2fe649",
    "file_path": "/specs/requirements.md",
    "status": "indexed",
    "chunks_count": 4,
    "content_length": 1024,
    "created_at": "2024-01-01T12:00:00.000Z",
    "updated_at": "2024-01-01T12:00:00.000Z",
}


class TestSpecListValidation:
    def test_requires_project_name_or_id(self) -> None:
        result = runner.invoke(app, ["spec", "list"])
        assert result.exit_code == 1
        assert "specify at least one" in (result.output + (result.stderr or "")).lower()

    def test_help_lists_list_command(self) -> None:
        result = runner.invoke(app, ["spec", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output


class TestSpecListByName:
    def test_lists_docs_for_existing_project(self) -> None:
        rt = _make_runtime(
            projects=[{"id": "proj-1", "repo_name": "myproj"}],
            list_docs_result=[_SAMPLE_DOC],
        )

        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "list", "--project-name", "myproj"],
            )

        assert result.exit_code == 0, result.output
        rt.spec_list_docs.assert_awaited_once_with(
            project_id="proj-1",
            user_id="defaultuser",
        )
        assert "doc-2fe649" in result.output
        assert "/specs/" in result.output  # file path column (may be truncated by Rich)
        assert "indexed" in result.output

    def test_shows_empty_message_when_no_docs(self) -> None:
        rt = _make_runtime(
            projects=[{"id": "proj-1", "repo_name": "myproj"}],
            list_docs_result=[],
        )

        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "list", "--project-name", "myproj"],
            )

        assert result.exit_code == 0, result.output
        assert "No indexed documents" in result.output

    def test_unknown_name_errors(self) -> None:
        rt = _make_runtime(projects=[{"id": "x", "repo_name": "other"}])

        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "list", "--project-name", "missing"],
            )

        assert result.exit_code == 1
        assert "not found" in result.output
        rt.spec_list_docs.assert_not_awaited()

    def test_name_id_mismatch_errors(self) -> None:
        rt = _make_runtime(projects=[{"id": "real-id", "repo_name": "myproj"}])

        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "list", "--project-name", "myproj", "--project-id", "wrong-id"],
            )

        assert result.exit_code == 1
        assert "does not match" in result.output
        rt.spec_list_docs.assert_not_awaited()


class TestSpecListById:
    def test_lists_by_id_skips_lookup(self) -> None:
        rt = _make_runtime(list_docs_result=[_SAMPLE_DOC])

        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "list", "--project-id", "proj-9"],
            )

        assert result.exit_code == 0, result.output
        rt.list_projects.assert_not_awaited()
        rt.spec_list_docs.assert_awaited_once_with(
            project_id="proj-9",
            user_id="defaultuser",
        )

    def test_shows_total_count(self) -> None:
        rt = _make_runtime(list_docs_result=[_SAMPLE_DOC, {**_SAMPLE_DOC, "doc_id": "doc-xyz"}])

        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "list", "--project-id", "pid"],
            )

        assert result.exit_code == 0, result.output
        assert "2 document" in result.output


class TestSpecListOptions:
    def test_json_output(self) -> None:
        import json

        rt = _make_runtime(list_docs_result=[_SAMPLE_DOC])

        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "list", "--project-id", "pid", "--json"],
            )

        assert result.exit_code == 0, result.output
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)
        assert parsed[0]["doc_id"] == "doc-2fe649"

    def test_custom_user_id(self) -> None:
        rt = _make_runtime(list_docs_result=[])

        with _patch_runtime(rt):
            runner.invoke(
                app,
                ["spec", "list", "--project-id", "pid", "--user-id", "alice"],
            )

        rt.spec_list_docs.assert_awaited_once_with(
            project_id="pid",
            user_id="alice",
        )


# ---------------------------------------------------------------------------
# spec del — validation, confirmation, deletion, cache purge
# ---------------------------------------------------------------------------


class TestSpecDelValidation:
    def test_requires_project_name_or_id(self) -> None:
        result = runner.invoke(app, ["spec", "del", "doc-abc"])
        assert result.exit_code == 1
        assert "specify at least one" in (result.output + (result.stderr or "")).lower()

    def test_help_lists_del_command(self) -> None:
        result = runner.invoke(app, ["spec", "--help"])
        assert result.exit_code == 0
        assert "del" in result.output


class TestSpecDelByName:
    def test_deletes_with_force_flag(self) -> None:
        rt = _make_runtime(
            projects=[{"id": "proj-1", "repo_name": "myproj"}],
            delete_doc_result={
                "status": "success", "doc_id": "doc-abc", "message": "Deleted.",
                "status_code": 200, "file_path": "foo.md",
            },
        )

        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "del", "doc-abc", "--project-name", "myproj", "--force"],
            )

        assert result.exit_code == 0, result.output
        rt.spec_delete_doc.assert_awaited_once_with(
            project_id="proj-1",
            user_id="defaultuser",
            doc_id="doc-abc",
            delete_llm_cache=False,
        )
        assert "Deleted" in result.output
        assert "doc-abc" in result.output

    def test_prompts_confirmation_and_proceeds(self) -> None:
        rt = _make_runtime(
            projects=[{"id": "proj-1", "repo_name": "myproj"}],
        )

        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "del", "doc-abc", "--project-name", "myproj"],
                input="y\n",
            )

        assert result.exit_code == 0, result.output
        rt.spec_delete_doc.assert_awaited_once()

    def test_prompts_confirmation_and_aborts(self) -> None:
        rt = _make_runtime(
            projects=[{"id": "proj-1", "repo_name": "myproj"}],
        )

        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "del", "doc-abc", "--project-name", "myproj"],
                input="n\n",
            )

        assert result.exit_code == 0
        rt.spec_delete_doc.assert_not_awaited()
        assert "Aborted" in result.output

    def test_prints_not_found_status(self) -> None:
        rt = _make_runtime(
            projects=[{"id": "proj-1", "repo_name": "myproj"}],
            delete_doc_result={
                "status": "not_found", "doc_id": "doc-missing", "message": "Document not found.",
                "status_code": 404, "file_path": None,
            },
        )

        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "del", "doc-missing", "--project-name", "myproj", "--force"],
            )

        assert result.exit_code == 0, result.output
        assert "Not found" in result.output
        assert "doc-missing" in result.output

    def test_prints_failed_status(self) -> None:
        rt = _make_runtime(
            projects=[{"id": "proj-1", "repo_name": "myproj"}],
            delete_doc_result={
                "status": "error", "doc_id": "doc-err", "message": "Internal error.",
                "status_code": 500, "file_path": None,
            },
        )

        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "del", "doc-err", "--project-name", "myproj", "--force"],
            )

        assert result.exit_code == 0, result.output
        assert "Failed" in result.output
        assert "doc-err" in result.output

    def test_unknown_name_errors(self) -> None:
        rt = _make_runtime(projects=[{"id": "x", "repo_name": "other"}])

        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "del", "doc-abc", "--project-name", "missing"],
            )

        assert result.exit_code == 1
        assert "not found" in result.output
        rt.spec_delete_doc.assert_not_awaited()

    def test_name_id_mismatch_errors(self) -> None:
        rt = _make_runtime(projects=[{"id": "real-id", "repo_name": "myproj"}])

        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "del", "doc-abc", "--project-name", "myproj", "--project-id", "wrong"],
            )

        assert result.exit_code == 1
        assert "does not match" in result.output
        rt.spec_delete_doc.assert_not_awaited()

    def test_purges_query_cache_after_delete(self) -> None:
        rt = _make_runtime(
            projects=[{"id": "proj-1", "repo_name": "myproj"}],
            purge_query_cache_result=3,
        )

        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "del", "doc-abc", "--project-name", "myproj", "--force"],
            )

        assert result.exit_code == 0, result.output
        rt.spec_purge_query_cache.assert_awaited_once_with(
            project_id="proj-1",
            user_id="defaultuser",
        )
        assert "3" in result.output

    def test_purge_silent_when_zero(self) -> None:
        rt = _make_runtime(
            projects=[{"id": "proj-1", "repo_name": "myproj"}],
            purge_query_cache_result=0,
        )

        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "del", "doc-abc", "--project-name", "myproj", "--force"],
            )

        assert result.exit_code == 0, result.output
        assert "Purged 0" not in result.output

    def test_multiple_doc_ids_all_deleted(self) -> None:
        call_count = 0

        async def _delete(**kwargs: object) -> dict:
            nonlocal call_count
            call_count += 1
            return {
                "status": "success", "doc_id": kwargs["doc_id"],
                "message": "Deleted.", "status_code": 200, "file_path": None,
            }

        rt = _make_runtime(projects=[{"id": "proj-1", "repo_name": "myproj"}])
        rt.spec_delete_doc = _delete  # type: ignore[method-assign]

        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "del", "doc-1", "doc-2", "doc-3", "--project-name", "myproj", "--force"],
            )

        assert result.exit_code == 0, result.output
        assert call_count == 3

    def test_delete_cache_flag_passed_through(self) -> None:
        rt = _make_runtime(projects=[{"id": "proj-1", "repo_name": "myproj"}])

        with _patch_runtime(rt):
            runner.invoke(
                app,
                ["spec", "del", "doc-abc", "--project-name", "myproj", "--force", "--delete-cache"],
            )

        rt.spec_delete_doc.assert_awaited_once()
        assert rt.spec_delete_doc.await_args.kwargs["delete_llm_cache"] is True


class TestSpecDelById:
    def test_deletes_by_id_skips_lookup(self) -> None:
        rt = _make_runtime()

        with _patch_runtime(rt):
            result = runner.invoke(
                app,
                ["spec", "del", "doc-abc", "--project-id", "pid-9", "--force"],
            )

        assert result.exit_code == 0, result.output
        rt.list_projects.assert_not_awaited()
        rt.spec_delete_doc.assert_awaited_once_with(
            project_id="pid-9",
            user_id="defaultuser",
            doc_id="doc-abc",
            delete_llm_cache=False,
        )

    def test_custom_user_id(self) -> None:
        rt = _make_runtime()

        with _patch_runtime(rt):
            runner.invoke(
                app,
                ["spec", "del", "doc-x", "--project-id", "pid", "--force", "--user-id", "bob"],
            )

        assert rt.spec_delete_doc.await_args.kwargs["user_id"] == "bob"


# ---------------------------------------------------------------------------
# PotpieRuntime.spec_list_docs — direct unit tests
# ---------------------------------------------------------------------------


class TestPotpieRuntimeSpecListDocs:
    async def test_returns_empty_when_file_missing(self, tmp_path: Path) -> None:
        from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

        b = PotpieRuntime()
        mock_config = MagicMock()
        mock_config.get_lightrag_working_dir.return_value = str(tmp_path)
        mock_config_mod = MagicMock(config_provider=mock_config)
        mock_kg_mod = MagicMock(workspace_for_user_project=lambda uid, pid: f"{uid}__{pid}")

        with patch.dict("sys.modules", {
            "app.core.config_provider": mock_config_mod,
            "app.modules.parsing.lightrag_sync.custom_kg_builder": mock_kg_mod,
        }):
            result = await b.spec_list_docs(project_id="proj-1", user_id="u1")

        assert result == []

    async def test_returns_docs_from_file(self, tmp_path: Path) -> None:
        import json

        from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

        b = PotpieRuntime()
        workspace = "u1__proj-1"
        ws_dir = tmp_path / workspace
        ws_dir.mkdir()
        status_data = {
            "doc-abc123": {
                "file_path": "/specs/req.md",
                "status": "indexed",
                "chunks_count": 3,
                "content_length": 512,
                "created_at": "2024-01-01T10:00:00",
                "updated_at": "2024-01-02T10:00:00",
            },
        }
        (ws_dir / "kv_store_doc_status.json").write_text(json.dumps(status_data))

        mock_config = MagicMock()
        mock_config.get_lightrag_working_dir.return_value = str(tmp_path)
        mock_config_mod = MagicMock(config_provider=mock_config)
        mock_kg_mod = MagicMock(workspace_for_user_project=lambda uid, pid: f"{uid}__{pid}")

        with patch.dict("sys.modules", {
            "app.core.config_provider": mock_config_mod,
            "app.modules.parsing.lightrag_sync.custom_kg_builder": mock_kg_mod,
        }):
            result = await b.spec_list_docs(project_id="proj-1", user_id="u1")

        assert len(result) == 1
        doc = result[0]
        assert doc["doc_id"] == "doc-abc123"
        assert doc["file_path"] == "/specs/req.md"
        assert doc["status"] == "indexed"
        assert doc["chunks_count"] == 3
        assert doc["content_length"] == 512
        assert doc["created_at"] == "2024-01-01T10:00:00"

    async def test_returns_multiple_docs(self, tmp_path: Path) -> None:
        import json

        from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

        b = PotpieRuntime()
        workspace = "u1__proj-2"
        ws_dir = tmp_path / workspace
        ws_dir.mkdir()
        status_data = {
            f"doc-{i}": {
                "file_path": f"file{i}.md",
                "status": "indexed",
                "chunks_count": i,
                "content_length": i * 100,
                "created_at": "",
                "updated_at": "",
            }
            for i in range(3)
        }
        (ws_dir / "kv_store_doc_status.json").write_text(json.dumps(status_data))

        mock_config = MagicMock()
        mock_config.get_lightrag_working_dir.return_value = str(tmp_path)
        mock_config_mod = MagicMock(config_provider=mock_config)
        mock_kg_mod = MagicMock(workspace_for_user_project=lambda uid, pid: f"{uid}__{pid}")

        with patch.dict("sys.modules", {
            "app.core.config_provider": mock_config_mod,
            "app.modules.parsing.lightrag_sync.custom_kg_builder": mock_kg_mod,
        }):
            result = await b.spec_list_docs(project_id="proj-2", user_id="u1")

        assert len(result) == 3
        doc_ids = {d["doc_id"] for d in result}
        assert doc_ids == {"doc-0", "doc-1", "doc-2"}


# ---------------------------------------------------------------------------
# PotpieRuntime.spec_purge_query_cache — direct unit tests
# ---------------------------------------------------------------------------


class TestPotpieRuntimeSpecPurgeQueryCache:
    async def test_returns_zero_when_no_cache_file(self, tmp_path: Path) -> None:
        from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

        b = PotpieRuntime()
        mock_config = MagicMock()
        mock_config.get_lightrag_working_dir.return_value = str(tmp_path)
        mock_config_mod = MagicMock(config_provider=mock_config)
        mock_kg_mod = MagicMock(workspace_for_user_project=lambda uid, pid: f"{uid}__{pid}")

        with patch.dict("sys.modules", {
            "app.core.config_provider": mock_config_mod,
            "app.modules.parsing.lightrag_sync.custom_kg_builder": mock_kg_mod,
        }):
            result = await b.spec_purge_query_cache(project_id="proj-1", user_id="u1")

        assert result == 0

    async def test_removes_only_query_type_entries(self, tmp_path: Path) -> None:
        import json

        from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

        b = PotpieRuntime()
        workspace = "u1__proj-1"
        ws_dir = tmp_path / workspace
        ws_dir.mkdir()
        cache_data = {
            "extract-key-1": {"cache_type": "extract", "data": "entity-extraction"},
            "query-key-1": {"cache_type": "query", "data": "old-query-answer"},
            "query-key-2": {"cache_type": "query", "data": "another-answer"},
            "keywords-key": {"cache_type": "keywords", "data": "kw"},
        }
        cache_file = ws_dir / "kv_store_llm_response_cache.json"
        cache_file.write_text(json.dumps(cache_data))

        mock_config = MagicMock()
        mock_config.get_lightrag_working_dir.return_value = str(tmp_path)
        mock_config_mod = MagicMock(config_provider=mock_config)
        mock_kg_mod = MagicMock(workspace_for_user_project=lambda uid, pid: f"{uid}__{pid}")
        mock_query_mod = MagicMock()
        mock_query_mod._rag_instance_cache = {}

        with patch.dict("sys.modules", {
            "app.core.config_provider": mock_config_mod,
            "app.modules.parsing.lightrag_sync.custom_kg_builder": mock_kg_mod,
            "app.modules.parsing.lightrag_sync.lightrag_query_service": mock_query_mod,
        }):
            removed = await b.spec_purge_query_cache(project_id="proj-1", user_id="u1")

        assert removed == 2
        remaining = json.loads(cache_file.read_text())
        assert "query-key-1" not in remaining
        assert "query-key-2" not in remaining
        assert "extract-key-1" in remaining
        assert "keywords-key" in remaining

    async def test_returns_zero_when_no_query_entries(self, tmp_path: Path) -> None:
        import json

        from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

        b = PotpieRuntime()
        workspace = "u1__proj-1"
        ws_dir = tmp_path / workspace
        ws_dir.mkdir()
        cache_data = {
            "extract-1": {"cache_type": "extract", "data": "x"},
        }
        cache_file = ws_dir / "kv_store_llm_response_cache.json"
        cache_file.write_text(json.dumps(cache_data))

        mock_config = MagicMock()
        mock_config.get_lightrag_working_dir.return_value = str(tmp_path)
        mock_config_mod = MagicMock(config_provider=mock_config)
        mock_kg_mod = MagicMock(workspace_for_user_project=lambda uid, pid: f"{uid}__{pid}")

        with patch.dict("sys.modules", {
            "app.core.config_provider": mock_config_mod,
            "app.modules.parsing.lightrag_sync.custom_kg_builder": mock_kg_mod,
        }):
            removed = await b.spec_purge_query_cache(project_id="proj-1", user_id="u1")

        assert removed == 0
        # File should be unchanged
        assert json.loads(cache_file.read_text()) == cache_data

    async def test_evicts_rag_instance_cache(self, tmp_path: Path) -> None:
        import json

        from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

        b = PotpieRuntime()
        workspace = "u1__proj-1"
        ws_dir = tmp_path / workspace
        ws_dir.mkdir()
        cache_data = {"q-1": {"cache_type": "query", "data": "answer"}}
        (ws_dir / "kv_store_llm_response_cache.json").write_text(json.dumps(cache_data))

        mock_config = MagicMock()
        mock_config.get_lightrag_working_dir.return_value = str(tmp_path)
        mock_config_mod = MagicMock(config_provider=mock_config)
        mock_kg_mod = MagicMock(workspace_for_user_project=lambda uid, pid: f"{uid}__{pid}")
        # Simulate a cached RAG instance for the workspace
        instance_cache: dict = {workspace: MagicMock()}
        mock_query_mod = MagicMock()
        mock_query_mod._rag_instance_cache = instance_cache

        with patch.dict("sys.modules", {
            "app.core.config_provider": mock_config_mod,
            "app.modules.parsing.lightrag_sync.custom_kg_builder": mock_kg_mod,
            "app.modules.parsing.lightrag_sync.lightrag_query_service": mock_query_mod,
        }):
            removed = await b.spec_purge_query_cache(project_id="proj-1", user_id="u1")

        assert removed == 1
        assert workspace not in instance_cache


# ---------------------------------------------------------------------------
# PotpieRuntime.spec_delete_doc — direct unit tests
# ---------------------------------------------------------------------------


def _make_deletion_result(
    status: str = "success",
    doc_id: str = "doc-abc",
    message: str = "Deleted.",
    status_code: int = 200,
    file_path: str | None = "foo.md",
) -> MagicMock:
    r = MagicMock()
    r.status = status
    r.doc_id = doc_id
    r.message = message
    r.status_code = status_code
    r.file_path = file_path
    return r


def _make_spec_delete_modules(deletion_result: MagicMock) -> dict:
    """Build sys.modules stubs needed for spec_delete_doc."""
    mock_rag = MagicMock()
    mock_rag.initialize_storages = AsyncMock()
    mock_rag.adelete_by_doc_id = AsyncMock(return_value=deletion_result)
    mock_rag.finalize_storages = AsyncMock()
    mock_lightrag_cls = MagicMock(return_value=mock_rag)

    mock_lightrag_mod = MagicMock()
    mock_lightrag_mod.LightRAG = mock_lightrag_cls
    mock_lightrag_utils = MagicMock()
    mock_lightrag_utils.EmbeddingFunc = MagicMock()
    mock_lightrag_utils.setup_logger = MagicMock()

    mock_config = MagicMock()
    mock_config.get_lightrag_working_dir.return_value = "/fake/dir"
    mock_config.get_lightrag_embedding_dim.return_value = 768
    mock_config.get_lightrag_embedding_model.return_value = "model-name"
    mock_config.get_lightrag_query_model.return_value = "llm-model"
    mock_config_mod = MagicMock(config_provider=mock_config)
    mock_kg_mod = MagicMock(workspace_for_user_project=lambda uid, pid: f"{uid}__{pid}")
    mock_query_svc_mod = MagicMock(_make_llm_func=MagicMock(return_value=MagicMock()))
    mock_embedding_mod = MagicMock(get_embedding_model=MagicMock(return_value=MagicMock()))
    mock_embedding_mod.get_embedding_model.return_value.encode = MagicMock(return_value=[])

    return {
        "lightrag": mock_lightrag_mod,
        "lightrag.utils": mock_lightrag_utils,
        "app.core.config_provider": mock_config_mod,
        "app.modules.parsing.lightrag_sync.custom_kg_builder": mock_kg_mod,
        "app.modules.parsing.lightrag_sync.lightrag_query_service": mock_query_svc_mod,
        "app.modules.parsing.knowledge_graph.code_embedding": mock_embedding_mod,
        "numpy": MagicMock(),
        "np": MagicMock(),
    }, mock_rag


class TestPotpieRuntimeSpecDeleteDoc:
    async def test_returns_deletion_result_dict(self) -> None:
        from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

        b = PotpieRuntime()
        deletion_result = _make_deletion_result()
        modules, mock_rag = _make_spec_delete_modules(deletion_result)

        with patch.dict("sys.modules", modules):
            result = await b.spec_delete_doc(
                project_id="proj-1",
                user_id="u1",
                doc_id="doc-abc",
            )

        assert result["status"] == "success"
        assert result["doc_id"] == "doc-abc"
        assert result["message"] == "Deleted."
        assert result["status_code"] == 200
        assert result["file_path"] == "foo.md"

    async def test_calls_adelete_by_doc_id_with_correct_args(self) -> None:
        from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

        b = PotpieRuntime()
        deletion_result = _make_deletion_result()
        modules, mock_rag = _make_spec_delete_modules(deletion_result)

        with patch.dict("sys.modules", modules):
            await b.spec_delete_doc(
                project_id="proj-1",
                user_id="u1",
                doc_id="doc-target",
            )

        mock_rag.adelete_by_doc_id.assert_awaited_once_with(
            "doc-target",
            delete_llm_cache=False,
        )

    async def test_passes_delete_llm_cache_flag(self) -> None:
        from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

        b = PotpieRuntime()
        deletion_result = _make_deletion_result()
        modules, mock_rag = _make_spec_delete_modules(deletion_result)

        with patch.dict("sys.modules", modules):
            await b.spec_delete_doc(
                project_id="proj-1",
                user_id="u1",
                doc_id="doc-xyz",
                delete_llm_cache=True,
            )

        assert mock_rag.adelete_by_doc_id.await_args.kwargs["delete_llm_cache"] is True

    async def test_initializes_and_finalizes_storages(self) -> None:
        from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

        b = PotpieRuntime()
        deletion_result = _make_deletion_result()
        modules, mock_rag = _make_spec_delete_modules(deletion_result)

        with patch.dict("sys.modules", modules):
            await b.spec_delete_doc(project_id="proj-1", user_id="u1", doc_id="doc-1")

        mock_rag.initialize_storages.assert_awaited_once()
        mock_rag.finalize_storages.assert_awaited_once()

    async def test_not_found_result(self) -> None:
        from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

        b = PotpieRuntime()
        deletion_result = _make_deletion_result(
            status="not_found", message="Document not found.", status_code=404, file_path=None,
        )
        modules, _ = _make_spec_delete_modules(deletion_result)

        with patch.dict("sys.modules", modules):
            result = await b.spec_delete_doc(project_id="p", user_id="u", doc_id="doc-gone")

        assert result["status"] == "not_found"
        assert result["status_code"] == 404
        assert result["file_path"] is None

    async def test_embedding_func_closure_is_callable(self) -> None:
        """The inner ``embedding_func`` closure (line 608) is passed to LightRAG but
        never invoked when LightRAG itself is mocked.  This test captures it from the
        ``EmbeddingFunc`` constructor call and calls it directly to cover the body."""
        from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

        b = PotpieRuntime()
        deletion_result = _make_deletion_result()
        modules, _ = _make_spec_delete_modules(deletion_result)

        with patch.dict("sys.modules", modules):
            await b.spec_delete_doc(project_id="proj-1", user_id="u1", doc_id="doc-abc")

        # ``EmbeddingFunc`` is mocked; grab the ``func`` kwarg that was passed to it.
        captured_func = modules["lightrag.utils"].EmbeddingFunc.call_args.kwargs["func"]

        mock_model = (
            modules["app.modules.parsing.knowledge_graph.code_embedding"]
            .get_embedding_model.return_value
        )
        mock_model.encode.return_value = [[0.1, 0.2]]

        result = await captured_func(["hello", "world"])

        mock_model.encode.assert_called_once_with(["hello", "world"], show_progress_bar=False)
        assert result == [[0.1, 0.2]]
