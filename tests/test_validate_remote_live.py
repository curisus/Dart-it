from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.validate_remote_live as live

from dart_crawler.result import JsonObject


class _MalformedRegistrationClient:
    def call(
        self,
        name: str,
        arguments: JsonObject,
        *,
        auth: str = "header",
        label: str | None = None,
    ) -> JsonObject:
        assert name == "get_registration_statements"
        assert arguments == {
            "corp_code": "00126380",
            "stmt_type": "debt_securities",
            "bgn_de": "20200101",
            "end_de": time.strftime("%Y%m%d"),
        }
        assert auth == "header"
        assert label == "get_registration_statements(debt_securities)"
        return {
            "ok": True,
            "data": {
                "corp_code": "99999999",
                "stmt_type": "debt_securities",
                "label": "증권신고서(채무증권)",
                "bgn_de": "19990101",
                "end_de": "19991231",
                "returned_group_count": 1,
                "returned_row_count": 7,
                "groups": [
                    {
                        "title": 123,
                        "row_count": 7,
                        "rows": [],
                    },
                ],
            },
        }


def test_registration_statement_live_check_rejects_malformed_echo_and_group() -> None:
    recorder = live.Recorder()
    client = cast(live.RemoteClient, _MalformedRegistrationClient())

    try:
        live._run_registration_statements_check(
            client,
            recorder,
            "00126380",
        )
    except live.LiveValidationError:
        return

    assert recorder.checks[-1].passed is False
