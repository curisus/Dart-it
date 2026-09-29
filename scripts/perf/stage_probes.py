"""Harness-side probes: an upstream request monitor and per-stage timers.

Nothing here edits product code. Every probe is a wrapper installed on a live
module or class attribute for the duration of a session and removed again by
``uninstall``; the product modules on disk are never touched.

- ``UpstreamMonitor`` wraps ``dart_crawler.http_client.HttpxClient.get`` - the
  single method every OpenDART/DART request goes through - to count requests
  (always on, negligible cost) and, with probes enabled, to log each request's
  host, path (query string dropped: it carries the API key), status, bytes and
  elapsed ms. Once the count passes the budget it refuses further requests so
  a runaway loop cannot burn the OpenDART quota.
- ``StageTimers`` wraps the ``PROBE_TARGETS`` ("module:qualname") and
  accumulates inclusive wall time per target. Class members are patched on
  their class; module functions are patched at the definition site and at
  every loaded use site that bound the same object with ``from x import y``.
  Nested stages overlap by design (parsing includes the coverage scan), and a
  re-entrant call of the same stage on one thread is timed once.

MCP runs sync tools in worker threads, so both accumulators are lock-guarded.
This module is imported by the unit tests: it imports product code lazily and
never performs I/O itself.
"""

from __future__ import annotations

import functools
import importlib
import inspect
import sys
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from types import ModuleType
from typing import Final, Protocol, cast
from urllib.parse import urlsplit, urlunsplit

# Cumulative-time probe targets, extendable as data. Ranking inside company
# search is deliberately not wrapped (it runs once per directory entry, ~100k
# times per search); it is the remainder search - download - parse - filter.
PROBE_TARGETS: Final[tuple[str, ...]] = (
    # company search: whole search, directory download, directory parse, filter
    "dart_crawler.company_search:CompanySearchService.search",
    "dart_crawler.dart_api:DartApi.download_company_codes",
    "dart_crawler.company_search:_parse_company_archive",
    "dart_crawler.company_search:CompanySearchService._filter_disclosures",
    # filing / disclosure lookup
    "dart_crawler.filing_service:FilingService.list",
    "dart_crawler.dart_api:DartApi.find_disclosure",
    # attachments: listing, reading, ZIP member extraction
    "dart_crawler.attachments:AttachmentService.list",
    "dart_crawler.attachments:AttachmentService.read_selected",
    "dart_crawler.zip_safety:read_member",
    # document parsing and its independent source coverage scan
    "dart_crawler.document_parser:parse_attachment",
    "dart_crawler.xml_parser:parse_xml_document",
    "dart_crawler.html_parser:parse_html_document",
    "dart_crawler.source_coverage:build_source_coverage",
    # report export: official amount comparison, workbook write and validation
    "dart_crawler.amount_checker:compare_statement_amounts",
    "dart_crawler.workbook_writer:write_workbook",
    "dart_crawler.workbook_validation:validate_workbook",
    # excel datasets: query + normalization, query workbook write/validation
    "dart_crawler.excel_normalized_dispatch:execute_normalized_excel_query",
    "dart_crawler.excel_dataset_builder:normalize_excel_source",
    "dart_crawler.excel_query_workbook_writer:write_excel_query_workbook",
    "dart_crawler.excel_query_workbook_validation:validate_excel_query_workbook",
    # remote pages: page selection and wire-size measurement
    "dart_crawler.excel_page_selection:select_excel_page",
    "dart_crawler.mcp_wire:measure_excel_result_wire",
    "dart_crawler.mcp_wire:measure_excel_schema_wire",
)

_NS_PER_MS: Final = 1_000_000


def redact_url(url: str) -> str:
    """Return scheme://host/path only: no userinfo, query string or fragment."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


class UpstreamBudgetExceededError(RuntimeError):
    """Raised inside the product's HTTP call once the request budget is spent."""


class _Response(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def content(self) -> bytes: ...


type _GetMethod = Callable[..., _Response]
type RequestRecord = dict[str, object]


@dataclass(slots=True)
class _Patch:
    owner: object
    name: str
    original: object
    replacement: object


def _restore(patches: list[_Patch]) -> None:
    for patch in reversed(patches):
        current = inspect.getattr_static(patch.owner, patch.name, None)
        if current is patch.replacement:
            setattr(patch.owner, patch.name, patch.original)
    patches.clear()


class UpstreamMonitor:
    """Count (and optionally log) every upstream HTTP request of a session."""

    def __init__(
        self,
        max_requests: int,
        *,
        record_requests: bool = False,
        client_class: type | None = None,
    ) -> None:
        self._max_requests = max_requests
        self._record_requests = record_requests
        self._client_class = client_class
        self._lock = threading.Lock()
        self._count = 0
        self._exceeded = False
        self._context: dict[str, object] = {}
        self._records: list[RequestRecord] = []
        self._patches: list[_Patch] = []

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    @property
    def exceeded(self) -> bool:
        with self._lock:
            return self._exceeded

    def set_context(self, context: dict[str, object]) -> None:
        with self._lock:
            self._context = dict(context)

    def drain_records(self) -> list[RequestRecord]:
        with self._lock:
            records = self._records
            self._records = []
            return records

    def _admit(self) -> None:
        # A refused request is never sent, so it is not counted: the count is
        # always the number of requests that actually reached the network.
        with self._lock:
            if self._count >= self._max_requests:
                self._exceeded = True
                msg = f"upstream request budget of {self._max_requests} exceeded"
                raise UpstreamBudgetExceededError(msg)
            self._count += 1

    def _record(
        self,
        url: str,
        status: int | None,
        size: int | None,
        started: int,
        error: str | None,
    ) -> None:
        parts = urlsplit(url)
        record: RequestRecord = {
            "kind": "upstream",
            "host": parts.hostname or "",
            "path": parts.path,
            "status": status,
            "bytes": size,
            "ms": round((time.perf_counter_ns() - started) / _NS_PER_MS, 3),
            "error": error,
        }
        with self._lock:
            record.update(self._context)
            self._records.append(record)

    def _wrap(self, original: _GetMethod) -> _GetMethod:
        @functools.wraps(original)
        def get(client: object, url: str, *args: object, **kwargs: object) -> _Response:
            self._admit()
            if not self._record_requests:
                return original(client, url, *args, **kwargs)
            started = time.perf_counter_ns()
            try:
                response = original(client, url, *args, **kwargs)
            except Exception as error:
                self._record(url, None, None, started, type(error).__name__)
                raise
            self._record(
                url, response.status_code, len(response.content), started, None
            )
            return response

        return get

    def install(self) -> None:
        if self._patches:
            return
        client_class = self._client_class
        if client_class is None:
            from dart_crawler.http_client import HttpxClient

            client_class = HttpxClient
        original = cast("_GetMethod", inspect.getattr_static(client_class, "get"))
        replacement = self._wrap(original)
        setattr(client_class, "get", replacement)  # noqa: B010 - patch target is data
        self._patches.append(_Patch(client_class, "get", original, replacement))

    def uninstall(self) -> None:
        _restore(self._patches)


@dataclass(slots=True)
class _StageTotal:
    total_ns: int = 0
    calls: int = 0


class StageTimers:
    """Lock-guarded inclusive wall time per probe target."""

    def __init__(self, targets: Iterable[str] = PROBE_TARGETS) -> None:
        self._targets = tuple(targets)
        self._lock = threading.Lock()
        self._totals: dict[str, _StageTotal] = {}
        self._depth = threading.local()
        self._patches: list[_Patch] = []

    @property
    def targets(self) -> tuple[str, ...]:
        return self._targets

    def reset(self) -> None:
        with self._lock:
            self._totals = {}

    def snapshot(self) -> dict[str, dict[str, float | int]]:
        with self._lock:
            return {
                stage: {
                    "ms": round(total.total_ns / _NS_PER_MS, 3),
                    "calls": total.calls,
                }
                for stage, total in sorted(self._totals.items())
            }

    def _depths(self) -> dict[str, int]:
        depths = getattr(self._depth, "value", None)
        if depths is None:
            depths = {}
            self._depth.value = depths
        return cast("dict[str, int]", depths)

    def _add(self, stage: str, elapsed_ns: int) -> None:
        with self._lock:
            total = self._totals.setdefault(stage, _StageTotal())
            total.total_ns += elapsed_ns
            total.calls += 1

    def _wrap(
        self, stage: str, function: Callable[..., object]
    ) -> Callable[..., object]:
        @functools.wraps(function)
        def timed(*args: object, **kwargs: object) -> object:
            depths = self._depths()
            depth = depths.get(stage, 0)
            depths[stage] = depth + 1
            started = time.perf_counter_ns()
            try:
                return function(*args, **kwargs)
            finally:
                depths[stage] = depth
                if depth == 0:
                    self._add(stage, time.perf_counter_ns() - started)

        return timed

    def _wrap_member(self, stage: str, member: object) -> object:
        if isinstance(member, staticmethod):
            return staticmethod(
                self._wrap(stage, cast("Callable[..., object]", member.__func__))
            )
        if isinstance(member, classmethod):
            return classmethod(
                self._wrap(stage, cast("Callable[..., object]", member.__func__))
            )
        if callable(member):
            return self._wrap(stage, member)
        msg = f"probe target is not callable: {stage}"
        raise TypeError(msg)

    def _install_target(self, target: str) -> None:
        module_name, _, qualname = target.partition(":")
        if not module_name or not qualname:
            msg = f"probe target must be 'module:qualname': {target}"
            raise ValueError(msg)
        module = importlib.import_module(module_name)
        *owner_path, name = qualname.split(".")
        owner: object = module
        for part in owner_path:
            owner = getattr(owner, part)
        original = inspect.getattr_static(owner, name)
        if inspect.iscoroutinefunction(original):
            msg = f"async probe targets are not supported: {target}"
            raise TypeError(msg)
        replacement = self._wrap_member(target, original)
        setattr(owner, name, replacement)
        self._patches.append(_Patch(owner, name, original, replacement))
        if owner is module:
            self._patch_use_sites(module, original, replacement)

    def _patch_use_sites(
        self, module: ModuleType, original: object, replacement: object
    ) -> None:
        package = module.__name__.split(".", 1)[0]
        for loaded_name, loaded in list(sys.modules.items()):
            if loaded is module or loaded is None:
                continue
            if loaded_name != package and not loaded_name.startswith(package + "."):
                continue
            for attribute, value in list(vars(loaded).items()):
                if value is original:
                    setattr(loaded, attribute, replacement)
                    self._patches.append(
                        _Patch(loaded, attribute, original, replacement)
                    )

    def install(self) -> None:
        if self._patches:
            return
        try:
            for target in self._targets:
                self._install_target(target)
        except Exception:
            self.uninstall()
            raise

    def uninstall(self) -> None:
        _restore(self._patches)
