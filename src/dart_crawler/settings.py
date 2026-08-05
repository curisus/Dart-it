"""Configuration resolution without parent-directory secret discovery."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, SecretStr

from dart_crawler.result import ErrorCode, Result, error_info


class AppSettings(BaseModel):
    """Resolved settings used by one server process."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_dir: Path
    api_key: SecretStr
    output_dir: Path


def load_settings(
    *,
    environment: Mapping[str, str] | None = None,
    process_dir: Path | None = None,
    provided_work_directories: Sequence[Path] = (),
) -> Result[AppSettings]:
    """Resolve project, API key, and output paths in documented order."""
    env = os.environ if environment is None else environment
    cwd = Path.cwd() if process_dir is None else process_dir
    project_result = _resolve_project_dir(env, cwd, provided_work_directories)
    if not project_result.ok or project_result.data is None:
        return Result.failure(
            project_result.error
            if project_result.error is not None
            else error_info(
                ErrorCode.CONFIG_ERROR,
                "프로젝트 기준 폴더를 확인할 수 없습니다.",
                retryable=False,
            ),
            next_action="DART_MCP_PROJECT_DIR 또는 단일 작업 폴더를 지정하세요.",
        )

    project_dir = project_result.data
    dotenv = _read_dotenv(project_dir / ".env")
    api_key = env.get("OPEN_DART_API_KEY") or dotenv.get("OPEN_DART_API_KEY")
    if not api_key:
        return Result.failure(
            error_info(
                ErrorCode.CONFIG_ERROR,
                "OPEN_DART_API_KEY가 설정되지 않았습니다.",
                retryable=False,
            ),
            next_action="운영체제 환경변수 또는 프로젝트 .env에 API 키를 설정하세요.",
        )

    raw_output = env.get("DART_MCP_OUTPUT_DIR") or dotenv.get("DART_MCP_OUTPUT_DIR")
    output_dir = Path(raw_output) if raw_output else project_dir / "output"
    if not output_dir.is_absolute():
        output_dir = project_dir / output_dir
    return Result.success(
        AppSettings(
            project_dir=project_dir,
            api_key=SecretStr(api_key),
            output_dir=output_dir,
        )
    )


def _resolve_project_dir(
    environment: Mapping[str, str],
    process_dir: Path,
    provided_work_directories: Sequence[Path],
) -> Result[Path]:
    explicit = environment.get("DART_MCP_PROJECT_DIR")
    if explicit:
        candidate = Path(explicit)
        if candidate.is_dir():
            return Result.success(candidate)
        return Result.failure(
            error_info(
                ErrorCode.CONFIG_ERROR,
                "DART_MCP_PROJECT_DIR가 폴더가 아닙니다.",
                retryable=False,
            )
        )
    if len(provided_work_directories) > 1:
        return Result.failure(
            error_info(
                ErrorCode.CONFIG_ERROR,
                "여러 로컬 작업 폴더 중 기준 폴더를 정할 수 없습니다.",
                retryable=False,
            )
        )
    if provided_work_directories:
        candidate = provided_work_directories[0]
        if candidate.is_dir():
            return Result.success(candidate)
        return Result.failure(
            error_info(
                ErrorCode.CONFIG_ERROR,
                "제공된 작업 폴더가 존재하지 않습니다.",
                retryable=False,
            )
        )
    return Result.success(process_dir)


def _read_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", maxsplit=1)
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values
