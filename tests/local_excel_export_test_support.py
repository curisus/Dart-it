from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import SecretStr

import dart_crawler.mcp_server as mcp_server
from dart_crawler.excel_query_service import ExcelQueryServiceFactory
from dart_crawler.http_client import HttpClient
from tests.excel_service_factory_fake import RecordingExcelServiceFactory


@dataclass(slots=True)
class RecordingClock:
    instant: datetime
    calls: int = 0

    def now_utc(self) -> datetime:
        self.calls += 1
        return self.instant


def install_local_export_runtime(
    monkeypatch: pytest.MonkeyPatch,
    project_dir: Path,
    factory: RecordingExcelServiceFactory,
    clock: RecordingClock,
    *,
    use_default_output: bool = False,
) -> Path:
    output_root = project_dir / ("output" if use_default_output else "published")
    monkeypatch.setenv("DART_MCP_PROJECT_DIR", str(project_dir))
    if use_default_output:
        monkeypatch.delenv("DART_MCP_OUTPUT_DIR", raising=False)
    else:
        monkeypatch.setenv("DART_MCP_OUTPUT_DIR", str(output_root))
    monkeypatch.setenv("OPEN_DART_API_KEY", "test-key")

    def build_factory(
        api_key: SecretStr,
        http_client: HttpClient,
    ) -> ExcelQueryServiceFactory:
        del http_client
        assert api_key.get_secret_value() == "test-key"
        return factory

    monkeypatch.setattr(mcp_server, "_excel_export_factory", build_factory)
    monkeypatch.setattr(mcp_server, "_excel_export_clock", clock)
    return output_root
