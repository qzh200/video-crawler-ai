from __future__ import annotations

import ast
import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from video_crawler.core.config import Settings
from video_crawler.infrastructure.process import groups as process_groups
from video_crawler.main import create_app
from video_crawler.worker import main as worker_main
from video_crawler.worker import task_entrypoint

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

APPROVED_OPENAPI_OPERATIONS = {
    "/health/live": {"get"},
    "/health/ready": {"get"},
    "/api/v1/crawl-jobs": {"post"},
    "/api/v1/crawl-jobs/{job_id}": {"get"},
    "/api/v1/crawl-jobs/{job_id}/cancel": {"post"},
    "/api/v1/crawl-jobs/{job_id}/resume": {"post"},
    "/api/v1/auth-profiles": {"get", "post"},
    "/api/v1/auth-profiles/{profile_id}": {"get"},
    "/api/v1/auth-profiles/{profile_id}/verify": {"post"},
    "/api/v1/auth-profiles/{profile_id}/verifications/{verification_id}": {"get"},
    "/api/v1/auth-profiles/{profile_id}/enable": {"post"},
    "/api/v1/auth-profiles/{profile_id}/disable": {"post"},
    "/api/v1/videos/{video_id}/metrics": {"get"},
    "/api/v1/videos/{video_id}/metrics/latest": {"get"},
    "/api/v1/videos/{video_id}/comments": {"get"},
    "/api/v1/video-units/{unit_id}/timed-text": {"get"},
}

APPROVED_TABLES = {
    "platforms",
    "auth_profiles",
    "auth_profile_leases",
    "videos",
    "video_units",
    "target_discoveries",
    "metric_definitions",
    "metric_snapshots",
    "metric_values",
    "comments",
    "timed_text_streams",
    "timed_text_items",
    "crawl_jobs",
    "crawl_runs",
    "crawl_module_runs",
    "idempotency_keys",
    "raw_artifacts",
}


def test_openapi_contains_only_approved_operations() -> None:
    paths = create_app().openapi()["paths"]
    operations = {
        path: {method for method in definition if method in {"get", "post", "put", "delete"}}
        for path, definition in paths.items()
    }

    assert operations == APPROVED_OPENAPI_OPERATIONS


def test_initial_migration_contains_only_approved_tables() -> None:
    migration = REPOSITORY_ROOT / "migrations" / "versions" / "0001_initial_schema.py"
    tree = ast.parse(migration.read_text(encoding="utf-8"))
    created_tables = {
        call.args[0].value
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "op"
        and call.func.attr == "create_table"
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    }

    assert created_tables == APPROVED_TABLES


def test_profile_verification_migration_adds_only_its_request_table() -> None:
    migration = REPOSITORY_ROOT / "migrations" / "versions" / "0002_profile_verifications.py"
    tree = ast.parse(migration.read_text(encoding="utf-8"))
    created_tables = {
        call.args[0].value
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "op"
        and call.func.attr == "create_table"
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    }

    assert created_tables == {"auth_profile_verifications"}


def test_profile_verification_docs_describe_async_worker_flow() -> None:
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
    api_contract = (REPOSITORY_ROOT / "docs" / "api-contract.md").read_text(encoding="utf-8")
    operations = (REPOSITORY_ROOT / "docs" / "operations.md").read_text(encoding="utf-8")
    schema = (REPOSITORY_ROOT / "docs" / "architecture" / "database-schema.md").read_text(
        encoding="utf-8"
    )
    combined = "\n".join((readme, api_contract, operations, schema))

    assert "auth_profile_verifications" in combined
    assert "PROFILE_VERIFICATION_NOT_FOUND" in api_contract
    assert "202" in api_contract
    assert "/verifications/$verificationId" in operations
    assert "Worker 停止" in operations
    assert "pending" in operations


def test_worker_and_profile_concurrency_are_fixed_at_one() -> None:
    settings = _settings()
    assert settings.worker_concurrency == settings.profile_concurrency == 1

    with pytest.raises(ValidationError):
        _settings(worker_concurrency=2)
    with pytest.raises(ValidationError):
        _settings(profile_concurrency=2)


def test_generic_core_and_domain_contain_no_adapter_specific_strings() -> None:
    forbidden = re.compile(r"\b(?:bvid|aid|cid)\b|bilibili", re.IGNORECASE)
    violations: list[str] = []
    for relative_directory in ("core", "domain"):
        directory = REPOSITORY_ROOT / "src" / "video_crawler" / relative_directory
        for source_file in directory.rglob("*.py"):
            for line_number, line in enumerate(
                source_file.read_text(encoding="utf-8").splitlines(),
                start=1,
            ):
                if forbidden.search(line):
                    violations.append(f"{source_file.relative_to(REPOSITORY_ROOT)}:{line_number}")

    assert violations == []


def test_readme_describes_the_release_instead_of_an_implementation_handoff() -> None:
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

    assert "0.1.0" in readme
    assert "规格仓库" not in readme
    assert "业务实现代码由 Codex" not in readme


class _AcceptanceSupervisor:
    def __init__(self) -> None:
        self.ran = False

    async def run_forever(self) -> None:
        self.ran = True


class _AcceptanceWorkerContainer:
    def __init__(self) -> None:
        self.supervisor = _AcceptanceSupervisor()
        self.closed = False

    def create_supervisor(self) -> _AcceptanceSupervisor:
        return self.supervisor

    async def aclose(self) -> None:
        self.closed = True


def test_worker_entrypoints_run_one_supervisor_and_close_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    direct_supervisor = _AcceptanceSupervisor()
    worker_main.run(direct_supervisor)  # type: ignore[arg-type]
    assert direct_supervisor.ran

    container = _AcceptanceWorkerContainer()
    asyncio.run(worker_main.run_production(container_factory=lambda: container))
    assert container.supervisor.ran
    assert container.closed

    main_called = False

    async def fake_run_production() -> None:
        nonlocal main_called
        main_called = True

    monkeypatch.setattr(worker_main, "run_production", fake_run_production)
    worker_main.main()
    assert main_called


class _AcceptanceTaskContainer:
    def __init__(self, *, status: str = "success", fail: bool = False) -> None:
        self.status = status
        self.fail = fail
        self.executed: list[UUID] = []
        self.closed = False

    async def execute_run(self, run_id: UUID) -> object:
        self.executed.append(run_id)
        if self.fail:
            raise RuntimeError("synthetic task failure")
        return SimpleNamespace(status=SimpleNamespace(value=self.status))

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("status", "fail", "expected"),
    [("partial", False, 0), ("failed", False, 1), ("success", True, 1)],
)
def test_task_entrypoint_maps_run_status_to_process_exit_code(
    status: str,
    fail: bool,
    expected: int,
) -> None:
    run_id = uuid4()
    container = _AcceptanceTaskContainer(status=status, fail=fail)

    exit_code = asyncio.run(task_entrypoint.run_task(run_id, container_factory=lambda: container))

    assert exit_code == expected
    assert container.executed == [run_id]
    assert container.closed


def test_task_cli_parses_the_run_id(monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = uuid4()
    received: list[UUID] = []

    async def fake_run_task(parsed_run_id: UUID) -> int:
        received.append(parsed_run_id)
        return 0

    monkeypatch.setattr(task_entrypoint, "run_task", fake_run_task)

    assert task_entrypoint.main([str(run_id)]) == 0
    assert received == [run_id]


def test_process_group_contract_escalates_after_the_grace_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_signals: list[int] = []
    wait_results = iter([False, True])

    monkeypatch.setattr(process_groups.os, "name", "posix")
    monkeypatch.setattr(
        process_groups,
        "_send_group_signal",
        lambda process_group_id, requested_signal: sent_signals.append(requested_signal) or True,
    )
    monkeypatch.setattr(
        process_groups,
        "_wait_for_group_exit",
        lambda process_group_id, timeout_seconds: next(wait_results),
    )

    result = process_groups.terminate_process_group(42, 1.0, 2.0)

    assert result == "SIGKILL"
    assert sent_signals == [process_groups.signal.SIGTERM, 9]


@pytest.mark.parametrize(
    ("process_group_id", "grace_seconds", "kill_timeout_seconds"),
    [(0, 1.0, 2.0), (42, -1.0, 2.0), (42, 1.0, 0.0)],
)
def test_process_group_contract_rejects_invalid_arguments(
    monkeypatch: pytest.MonkeyPatch,
    process_group_id: int,
    grace_seconds: float,
    kill_timeout_seconds: float,
) -> None:
    monkeypatch.setattr(process_groups.os, "name", "posix")

    with pytest.raises(ValueError):
        process_groups.terminate_process_group(
            process_group_id,
            grace_seconds,
            kill_timeout_seconds,
        )


@pytest.mark.parametrize(
    ("send_result", "wait_result"),
    [(False, False), (True, True)],
)
def test_process_group_contract_returns_after_sigterm(
    monkeypatch: pytest.MonkeyPatch,
    send_result: bool,
    wait_result: bool,
) -> None:
    monkeypatch.setattr(process_groups.os, "name", "posix")
    monkeypatch.setattr(process_groups, "_send_group_signal", lambda *_: send_result)
    monkeypatch.setattr(process_groups, "_wait_for_group_exit", lambda *_: wait_result)

    assert process_groups.terminate_process_group(42, 1.0, 2.0) == "SIGTERM"


def test_process_group_contract_reports_sigkill_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(process_groups.os, "name", "posix")
    monkeypatch.setattr(process_groups, "_send_group_signal", lambda *_: True)
    monkeypatch.setattr(process_groups, "_wait_for_group_exit", lambda *_: False)

    with pytest.raises(TimeoutError, match="did not exit after SIGKILL"):
        process_groups.terminate_process_group(42, 1.0, 2.0)


def _settings(**overrides: object) -> Settings:
    return Settings.model_validate(
        {
            "mysql_password": "test",
            "minio_secret_key": "test",
            "api_key": "test",
            **overrides,
        }
    )


def test_operations_document_utf8_and_binary_uuid_inspection() -> None:
    operations = Path("docs/operations.md").read_text(encoding="utf-8")
    api_contract = Path("docs/api-contract.md").read_text(encoding="utf-8")

    assert "Get-Content -Encoding UTF8" in operations
    assert "BINARY(16)" in operations
    assert "0x..." in operations
    assert "PROFILE_NOT_ACTIVE" in api_contract
    assert "DISCOVERY_EMPTY" in api_contract
