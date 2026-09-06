"""Fitness-test runner: executes tool calls (local mcp.call_tool or remote JSON-RPC) and records evidence.

Usage (run from the repo root so the venv resolves):
  uv run python scripts/fitness/runner.py --run-id R1 --calls calls.json --out <runs_root> [--target local|remote]

calls.json = [
  {"scenario": "S02", "step": "fs_cfs", "tool": "get_financial_statements",
   "args": {...}, "target": "local"|"remote" (optional), "auth": "bearer"|"header"|"none" (optional),
   "follow_cursor": true (optional, load_excel_page only), "expect": {...} (optional, recorded only)}
]
Every call writes <out>/<run_id>/<scenario>/<seq>_<step>.json (record without data),
<seq>_<step>.data.json (data payload) and appends one line to <out>/<run_id>/summary.jsonl.
The API key is read from <repo>/.env and never written to any record.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_DEFAULT = r"C:\python Project\Dart Mcp"
PROD_URL = "https://dart-it-mcp.vercel.app/api/mcp"
COUNT_KEYS = (
    "returned_row_count", "total_row_count", "total_rows", "returned_rows", "page_index",
    "section_count", "total_cell_count", "total_text_char_count", "returned_cell_count",
    "returned_text_char_count", "returned_group_count", "rendered_char_count",
)
LIST_KEYS = ("accounts", "rows", "sections", "topics", "events", "groups", "indicators", "companies", "attachments", "filings")


def read_env_key(repo: Path) -> str:
    env_file = repo / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPEN_DART_API_KEY="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("OPEN_DART_API_KEY", "").strip()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    if "ok" not in payload and set(payload) == {"result"} and isinstance(payload["result"], dict):
        return payload["result"]
    return payload


def _failure(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "data": None, "error": {"code": code, "message": message[:500]}, "warnings": [], "next_action": None}


class LocalCaller:
    def __init__(self, repo: Path, output_dir: Path, key: str) -> None:
        os.environ["DART_MCP_PROJECT_DIR"] = str(repo)
        os.environ["DART_MCP_OUTPUT_DIR"] = str(output_dir)
        os.environ["OPEN_DART_API_KEY"] = key
        from dart_crawler.mcp_server import mcp

        self._mcp = mcp

    def set_output_dir(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        os.environ["DART_MCP_OUTPUT_DIR"] = str(output_dir)

    def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        result = asyncio.run(self._mcp.call_tool(tool, args))
        structured = getattr(result, "structured_content", None)
        if isinstance(structured, dict):
            return _unwrap(structured)
        for block in getattr(result, "content", None) or []:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                return _unwrap(json.loads(text))
        return _failure("HARNESS", "no structured content")


class RemoteCaller:
    def __init__(self, url: str, key: str) -> None:
        import httpx2

        self._url = url
        self._key = key
        self._id = 0
        self._client = httpx2.Client(timeout=httpx2.Timeout(connect=10.0, read=600.0, write=30.0, pool=30.0))

    def close(self) -> None:
        self._client.close()

    def call(self, tool: str, args: dict[str, Any], auth: str = "bearer") -> dict[str, Any]:
        self._id += 1
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if auth == "bearer":
            headers["Authorization"] = "Bearer " + self._key
        elif auth == "header":
            headers["X-OpenDART-API-Key"] = self._key
        payload = {"jsonrpc": "2.0", "id": self._id, "method": "tools/call", "params": {"name": tool, "arguments": args}}
        body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        response = self._client.post(self._url, content=body_bytes, headers=headers)
        if response.status_code != 200:
            envelope = _failure("HTTP_" + str(response.status_code), response.text[:300])
            envelope["_http_status"] = response.status_code
            return envelope
        body = response.json()
        if "error" in body:
            return _failure("JSONRPC_ERROR", canonical(body["error"]))
        result = body.get("result") or {}
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return _unwrap(structured)
        for block in result.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                return _unwrap(json.loads(block["text"]))
        return _failure("HARNESS", "no tool result")


def _counts(data: Any) -> dict[str, Any]:
    counts: dict[str, Any] = {}
    if isinstance(data, dict):
        for key in COUNT_KEYS:
            if key in data:
                counts[key] = data[key]
        for key in LIST_KEYS:
            if isinstance(data.get(key), list):
                counts["len_" + key] = len(data[key])
        if data.get("next_cursor") is not None:
            counts["has_next_cursor"] = True
    elif isinstance(data, list):
        counts["len"] = len(data)
    return counts


def record_call(run_dir: Path, summary: Path, seq: int, spec: dict[str, Any], target: str,
                envelope: dict[str, Any], elapsed_ms: int, run_id: str) -> dict[str, Any]:
    scenario = spec["scenario"]
    step = spec["step"]
    scenario_dir = run_dir / scenario
    scenario_dir.mkdir(parents=True, exist_ok=True)
    data = envelope.get("data")
    data_text = canonical(data)
    data_file = scenario_dir / f"{seq:03d}_{step}.data.json"
    data_file.write_text(data_text, encoding="utf-8")
    error = envelope.get("error") if isinstance(envelope.get("error"), dict) else None
    warnings = envelope.get("warnings") or []
    output_path = data.get("absolute_path") if isinstance(data, dict) else None
    record = {
        "run_id": run_id,
        "scenario": scenario,
        "step": step,
        "seq": seq,
        "target": target,
        "tool": spec["tool"],
        "args": spec["args"],
        "ok": envelope.get("ok"),
        "error_code": error.get("code") if error else None,
        "error_message": error.get("message") if error else None,
        "error_details": error.get("details") if error else None,
        "warning_codes": [w.get("code") for w in warnings if isinstance(w, dict)],
        "warnings": warnings,
        "next_action": envelope.get("next_action"),
        "counts": _counts(data),
        "elapsed_ms": elapsed_ms,
        "bytes": len(canonical(envelope).encode("utf-8")),
        "data_sha256": sha256_text(data_text),
        "output_path": output_path,
        "data_path": str(data_file),
        "expect": spec.get("expect"),
        "http_status": envelope.get("_http_status"),
    }
    (scenario_dir / f"{seq:03d}_{step}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    slim = {k: v for k, v in record.items() if k not in ("warnings", "error_details", "expect")}
    with summary.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(slim, ensure_ascii=False))
        handle.write("\n")
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dart it fitness runner")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--calls", required=True, help="calls.json path")
    parser.add_argument("--out", required=True, help="runs root directory")
    parser.add_argument("--target", default="local", choices=["local", "remote"])
    parser.add_argument("--url", default=PROD_URL)
    parser.add_argument("--repo", default=REPO_DEFAULT)
    parser.add_argument("--auth", default="bearer", choices=["bearer", "header", "none"])
    ns = parser.parse_args(argv)

    repo = Path(ns.repo)
    key = read_env_key(repo)
    if not key:
        print("OPEN_DART_API_KEY not found in .env or environment", file=sys.stderr)
        return 2
    run_dir = Path(ns.out) / ns.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    summary = run_dir / "summary.jsonl"
    specs = json.loads(Path(ns.calls).read_text(encoding="utf-8"))
    seq = sum(1 for _ in summary.open(encoding="utf-8")) if summary.exists() else 0

    local: LocalCaller | None = None
    remote: RemoteCaller | None = None
    recorded = 0
    for spec in specs:
        target = spec.get("target", ns.target)
        spec.setdefault("args", {})
        spec.setdefault("step", spec["tool"])
        if target == "local":
            if local is None:
                local = LocalCaller(repo, run_dir / spec["scenario"] / "xlsx", key)
            local.set_output_dir(run_dir / spec["scenario"] / "xlsx")
        elif remote is None:
            remote = RemoteCaller(ns.url, key)
        pages = 0
        args = json.loads(json.dumps(spec["args"]))
        base_step = spec["step"]
        while True:
            seq += 1
            started = time.perf_counter()
            try:
                if target == "local":
                    assert local is not None
                    envelope = local.call(spec["tool"], args)
                else:
                    assert remote is not None
                    envelope = remote.call(spec["tool"], args, auth=spec.get("auth", ns.auth))
            except Exception as error:  # noqa: BLE001 - the harness records, never crashes
                envelope = _failure("HARNESS_EXCEPTION", f"{type(error).__name__}: {error}")
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            page_spec = dict(spec)
            page_spec["args"] = args
            page_spec["step"] = base_step if pages == 0 else f"{base_step}_p{pages}"
            record = record_call(run_dir, summary, seq, page_spec, target, envelope, elapsed_ms, ns.run_id)
            recorded += 1
            print(f"[{record['scenario']}/{record['step']}] {record['tool']} ok={record['ok']} code={record['error_code']} "
                  f"warn={record['warning_codes']} counts={record['counts']} {elapsed_ms}ms")
            data = envelope.get("data")
            if spec.get("follow_cursor") and isinstance(data, dict) and data.get("next_cursor"):
                pages += 1
                if pages > 200:
                    print("  cursor loop stopped at 200 pages")
                    break
                args = json.loads(json.dumps(args))
                args.setdefault("request", {})["cursor"] = data["next_cursor"]
                continue
            break
    if remote is not None:
        remote.close()
    print(f"--- {recorded} calls recorded under {run_dir} ---")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
