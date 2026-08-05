from pathlib import Path

from dart_crawler.settings import load_settings


def test_environment_api_key_and_output_directory_override_dotenv(
    tmp_path: Path,
) -> None:
    (tmp_path / ".env").write_text(
        "OPEN_DART_API_KEY=dotenv-secret\nDART_MCP_OUTPUT_DIR=dotenv-output\n",
        encoding="utf-8",
    )

    result = load_settings(
        environment={
            "OPEN_DART_API_KEY": "environment-secret",
            "DART_MCP_OUTPUT_DIR": "environment-output",
        },
        process_dir=tmp_path,
    )

    assert result.ok is True
    assert result.data is not None
    assert result.data.api_key.get_secret_value() == "environment-secret"
    assert result.data.output_dir == tmp_path / "environment-output"


def test_project_env_is_not_loaded_from_parent_directory(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (tmp_path / ".env").write_text(
        "OPEN_DART_API_KEY=parent-secret\n", encoding="utf-8"
    )

    result = load_settings(environment={}, process_dir=project_dir)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code.value == "CONFIG_ERROR"


def test_multiple_mcp_work_directories_are_not_selected_arbitrarily(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    result = load_settings(
        environment={},
        process_dir=tmp_path,
        provided_work_directories=(first, second),
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code.value == "CONFIG_ERROR"
