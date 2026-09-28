"""Compare two latency-harness runs: completeness, per-flow statistics, invariance, verdict.

Usage:
  uv run python scripts/perf/compare_runs.py --base <run_dir> --new <run_dir>
  uv run python scripts/perf/compare_runs.py --ab <ab_run_dir>     (= --base <dir>/A --new <dir>/B)
      [--representative L-A] [--target-reduction 0.5] [--max-regression 0.10]
      [--allow-incomplete] [--exclude-cold] [--exclude-first-in-session] [--out <dir>]
  uv run python scripts/perf/compare_runs.py combine <comparison.json> [<comparison.json> ...]
      [--require L-A,R-A] [--out <dir>]

A comparison reads each run's flows.jsonl (valid and invalid records) and
env.json, writes comparison.json and comparison.md into --out (default: the ab
dir, else the new run dir) and prints the Markdown.

- Completeness comes first (see perf_stats): every (flow, company) needs the
  same number of valid samples in both arms and no invalid one; otherwise the
  flow is INCOMPLETE (or MISSING when one arm never recorded it or neither arm
  has a valid sample) and the comparison FAILs. --allow-incomplete turns that
  into PASS_WITH_INCOMPLETE, never PASS.
- A flow's reduction is the median over companies of each company's own
  reduction; the pooled median is shown for information only.
- The representative flow is the catalog's representative flow for the run's
  target (env.json: local -> L-A, remote/remote-asgi -> R-A) unless
  --representative overrides it. ``combine`` joins the local and the remote
  comparison: PASS only when every input passed and every catalog
  representative (L-A and R-A) passed in one of them.
- Invariance is decided per (flow, company) on the flow identity: the data
  hash (rows_sha256 or xlsx_sha256_of_values) plus the flow's sorted warning
  codes, with an xlsx diff for any pair whose data differ.
- --ab first verifies arm isolation: every session in each arm's env.json must
  have imported dart_crawler from the project ab.json names for that arm.
- --exclude-cold / --exclude-first-in-session drop flows flagged so (local and
  remote runs alike). They are refused for --ab: every ab subprocess is its
  own session, so each one's first flow is first-in-session (and, remotely,
  possibly cold) in both arms alike - cold starts are symmetric there, and
  excluding them would only delete every sample of the first-listed flow.

Exit codes: 0 PASS, 1 FAIL, 2 unusable input, 3 PASS_WITH_INCOMPLETE.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Collection, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, cast

from latency_harness import code_root_mismatch, load_catalog
from perf_stats import (
    DEFAULT_MAX_REGRESSION,
    DEFAULT_TARGET_REDUCTION,
    CombineInput,
    CompanySamples,
    FlowAssessment,
    OracleVerdict,
    Verdict,
    assess_flow,
    combine_verdicts,
    invariance_verdict,
    oracle_verdict,
)
from xlsx_invariance import compare_workbooks, flow_identity, report_json

SCHEMA_VERSION: Final = 2
EXIT_USAGE: Final = 2
EXIT_CODES: Final[dict[Verdict, int]] = {
    Verdict.PASS: 0,
    Verdict.FAIL: 1,
    Verdict.PASS_WITH_INCOMPLETE: 3,
}
AB_EXCLUSION_REFUSAL: Final = (
    "--exclude-cold/--exclude-first-in-session are refused for --ab: every ab "
    "subprocess starts its own session, so its first flow is first-in-session "
    "in both arms alike (cold starts are symmetric) and excluding it would "
    "only delete every sample of the first-listed flow"
)

type FlowRecord = dict[str, object]
type PairKey = tuple[str, str]


class CompareError(RuntimeError):
    """The run directories cannot be compared."""


@dataclass(frozen=True, slots=True)
class InvarianceEntry:
    flow: str
    corp_code: str
    status: str
    base_identities: tuple[str, ...]
    new_identities: tuple[str, ...]
    base_warning_codes: tuple[tuple[str, ...], ...]
    new_warning_codes: tuple[tuple[str, ...], ...]
    xlsx_diff: dict[str, object] | None


# ---------------------------------------------------------------- inputs


def load_flows(run_dir: Path) -> list[FlowRecord]:
    path = run_dir / "flows.jsonl"
    if not path.is_file():
        msg = f"no flows.jsonl in {run_dir}"
        raise CompareError(msg)
    records: list[FlowRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                records.append(cast("FlowRecord", value))
    return records


def _load_json_object(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return cast("dict[str, object]", value) if isinstance(value, dict) else None


def run_target(run_dir: Path) -> str | None:
    env = _load_json_object(run_dir / "env.json")
    target = None if env is None else env.get("target")
    return target if isinstance(target, str) else None


def _warning_codes(record: FlowRecord) -> tuple[str, ...]:
    codes = record.get("warning_codes")
    if not isinstance(codes, list):
        return ()
    return tuple(sorted({code for code in codes if isinstance(code, str)}))


def _data_hash(record: FlowRecord) -> str | None:
    for key in ("rows_sha256", "xlsx_sha256_of_values"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def record_identity(record: FlowRecord) -> str | None:
    """The flow identity: data hash plus sorted unique warning codes."""
    return flow_identity(_data_hash(record), _warning_codes(record))


def _total(record: FlowRecord) -> float | None:
    value = record.get("total_ms")
    return float(value) if isinstance(value, (int, float)) else None


def _excluded(record: FlowRecord, *, cold: bool, first: bool) -> bool:
    return (cold and record.get("possibly_cold") is True) or (
        first and record.get("first_in_session") is True
    )


def _pairs(records: list[FlowRecord]) -> dict[PairKey, list[FlowRecord]]:
    pairs: dict[PairKey, list[FlowRecord]] = {}
    for record in records:
        key = (str(record.get("flow")), str(record.get("corp_code")))
        pairs.setdefault(key, []).append(record)
    return pairs


# ---------------------------------------------------------------- ab isolation


def verify_ab_arms(ab_dir: Path) -> dict[str, list[str]]:
    """Every session of each arm must have imported dart_crawler from its project."""
    ab = _load_json_object(ab_dir / "ab.json")
    projects = None if ab is None else ab.get("projects")
    if not isinstance(projects, dict):
        msg = f"no ab.json with projects in {ab_dir}"
        raise CompareError(msg)
    roots: dict[str, list[str]] = {}
    for arm in ("A", "B"):
        expected = projects.get(arm)
        env = _load_json_object(ab_dir / arm / "env.json")
        sessions = [] if env is None else env.get("sessions")
        if (
            not isinstance(expected, str)
            or not isinstance(sessions, list)
            or not sessions
        ):
            msg = f"arm {arm}: no project in ab.json or no sessions in env.json"
            raise CompareError(msg)
        roots[arm] = []
        for session in sessions:
            root = session.get("code_root") if isinstance(session, dict) else None
            if not isinstance(root, str):
                msg = f"arm {arm}: a session recorded no code_root"
                raise CompareError(msg)
            problem = code_root_mismatch(root, expected)
            if problem is not None:
                msg = f"arm {arm} is not isolated: {problem}"
                raise CompareError(msg)
            roots[arm].append(root)
    return roots


# ---------------------------------------------------------------- assessment


def company_samples(
    base: list[FlowRecord], new: list[FlowRecord]
) -> dict[str, list[CompanySamples]]:
    """Per flow, each company's valid latencies and invalid counts in both arms."""
    base_pairs = _pairs(base)
    new_pairs = _pairs(new)
    flows: dict[str, list[CompanySamples]] = {}
    for pair in sorted(set(base_pairs) | set(new_pairs)):
        base_records = base_pairs.get(pair, [])
        new_records = new_pairs.get(pair, [])
        flows.setdefault(pair[0], []).append(
            CompanySamples(
                corp_code=pair[1],
                base_ms=_valid_totals(base_records),
                new_ms=_valid_totals(new_records),
                base_invalid=_invalid_count(base_records),
                new_invalid=_invalid_count(new_records),
            )
        )
    return flows


def _valid_totals(records: list[FlowRecord]) -> tuple[float, ...]:
    return tuple(
        total
        for total in (
            _total(record) for record in records if record.get("valid") is True
        )
        if total is not None
    )


def _invalid_count(records: list[FlowRecord]) -> int:
    return sum(
        1
        for record in records
        if record.get("valid") is not True or _total(record) is None
    )


def assess_flows(
    base: list[FlowRecord],
    new: list[FlowRecord],
    representative: Collection[str],
    *,
    target_reduction: float,
    max_regression: float,
) -> list[FlowAssessment]:
    base_flows = {str(record.get("flow")) for record in base}
    new_flows = {str(record.get("flow")) for record in new}
    return [
        assess_flow(
            flow,
            companies,
            in_base=flow in base_flows,
            in_new=flow in new_flows,
            representative=flow in representative,
            target_reduction=target_reduction,
            max_regression=max_regression,
        )
        for flow, companies in sorted(company_samples(base, new).items())
    ]


def _first_xlsx(records: list[FlowRecord]) -> Path | None:
    for record in records:
        path = record.get("xlsx_path")
        if isinstance(path, str) and Path(path).is_file():
            return Path(path)
    return None


def _pair_status(base_ids: set[str], new_ids: set[str]) -> str:
    if not base_ids and not new_ids:
        return "missing_both"
    if not base_ids:
        return "missing_base"
    if not new_ids:
        return "missing_new"
    if len(base_ids) > 1:
        return "unstable_base"
    if len(new_ids) > 1:
        return "unstable_new"
    return "identical" if base_ids == new_ids else "different"


def invariance_entries(
    base: list[FlowRecord], new: list[FlowRecord]
) -> list[InvarianceEntry]:
    base_pairs = _pairs(base)
    new_pairs = _pairs(new)
    entries: list[InvarianceEntry] = []
    for pair in sorted(set(base_pairs) | set(new_pairs)):
        base_valid = [r for r in base_pairs.get(pair, []) if r.get("valid") is True]
        new_valid = [r for r in new_pairs.get(pair, []) if r.get("valid") is True]
        base_ids = {i for i in map(record_identity, base_valid) if i}
        new_ids = {i for i in map(record_identity, new_valid) if i}
        status = _pair_status(base_ids, new_ids)
        base_data = {h for h in map(_data_hash, base_valid) if h}
        new_data = {h for h in map(_data_hash, new_valid) if h}
        base_xlsx = _first_xlsx(base_valid)
        new_xlsx = _first_xlsx(new_valid)
        diff = (
            report_json(compare_workbooks(base_xlsx, new_xlsx))
            if status != "identical"
            and base_data != new_data
            and base_xlsx is not None
            and new_xlsx is not None
            else None
        )
        entries.append(
            InvarianceEntry(
                flow=pair[0],
                corp_code=pair[1],
                status=status,
                base_identities=tuple(sorted(base_ids)),
                new_identities=tuple(sorted(new_ids)),
                base_warning_codes=tuple(
                    sorted({_warning_codes(r) for r in base_valid})
                ),
                new_warning_codes=tuple(sorted({_warning_codes(r) for r in new_valid})),
                xlsx_diff=diff,
            )
        )
    return entries


def representative_flows(target: str) -> tuple[str, ...]:
    """The catalog's representative flow(s) for a run target's surface."""
    surface = "local" if target == "local" else "remote"
    return tuple(
        flow.flow_id
        for flow in load_catalog().flows
        if flow.representative and flow.surface == surface
    )


def catalog_representatives() -> tuple[str, ...]:
    return tuple(flow.flow_id for flow in load_catalog().flows if flow.representative)


def _split(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in text.split(",") if part.strip())


def _resolve_representative(
    namespace: argparse.Namespace, base_dir: Path, new_dir: Path
) -> tuple[str | None, tuple[str, ...]]:
    targets = {run_target(base_dir), run_target(new_dir)}
    target = next(iter(targets)) if len(targets) == 1 else None
    if namespace.representative is not None:
        return target, _split(namespace.representative)
    if target is None:
        msg = f"cannot pick the representative flow: env.json targets {sorted(map(str, targets))}"
        raise CompareError(msg)
    return target, representative_flows(target)


# ---------------------------------------------------------------- report


def _fmt(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:,.1f}"
    return str(value)


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:+.1%}"


def _median(summary: object) -> str:
    return _fmt(getattr(summary, "median_ms", None))


def _flow_row(flow: FlowAssessment) -> str:
    companies = flow.companies
    return (
        f"| {flow.flow} | {flow.representative} | {flow.status} "
        f"| {sum(c.n_base for c in companies)} | {sum(c.n_new for c in companies)} "
        f"| {sum(c.invalid_base for c in companies)} | {sum(c.invalid_new for c in companies)} "
        f"| {_median(flow.pooled_base)} | {_median(flow.pooled_new)} "
        f"| {_pct(flow.reduction)} | {flow.requirement} | {_fmt(flow.passed)} |"
    )


def _flow_rows(verdict: OracleVerdict) -> list[str]:
    return [
        (
            "| flow | representative | status | n base | n new | invalid base | invalid new "
            "| pooled median base | pooled median new | company-median reduction | requirement | pass |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
        *(_flow_row(flow) for flow in verdict.flows),
    ]


def _company_rows(verdict: OracleVerdict) -> list[str]:
    rows = [
        "| flow | corp_code | n base | n new | invalid base | invalid new | median base | median new | reduction |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    rows.extend(
        f"| {flow.flow} | {c.corp_code} | {c.n_base} | {c.n_new} | {c.invalid_base} "
        f"| {c.invalid_new} | {_fmt(c.base_median_ms)} | {_fmt(c.new_median_ms)} | {_pct(c.reduction)} |"
        for flow in verdict.flows
        for c in flow.companies
    )
    return rows


def _codes(groups: tuple[tuple[str, ...], ...]) -> str:
    return " / ".join(",".join(group) or "(none)" for group in groups) or "-"


def _invariance_rows(entries: list[InvarianceEntry]) -> list[str]:
    rows = [
        "| flow | corp_code | invariance | base identity | new identity | base warnings | new warnings |",
        "|---|---|---|---|---|---|---|",
    ]
    rows.extend(
        f"| {e.flow} | {e.corp_code} | {e.status} "
        f"| {','.join(v[:12] for v in e.base_identities) or '-'} "
        f"| {','.join(v[:12] for v in e.new_identities) or '-'} "
        f"| {_codes(e.base_warning_codes)} | {_codes(e.new_warning_codes)} |"
        for e in entries
    )
    return rows


def render_markdown(
    result: dict[str, object],
    entries: list[InvarianceEntry],
    verdict: OracleVerdict,
) -> str:
    lines = [
        "# Latency comparison",
        "",
        f"- base: `{result['base']}`",
        f"- new: `{result['new']}`",
        (
            f"- target: {result['target']} / representative flows: {result['representative']} "
            f"(target reduction {result['target_reduction']}, max regression {result['max_regression']})"
        ),
        f"- allow incomplete: {result['allow_incomplete']} / excluded: {result['excluded'] or 'nothing'}",
        f"- latency: **{verdict.latency}** / invariance: **{verdict.invariance}** / overall: **{verdict.overall}**",
    ]
    if verdict.overall is Verdict.PASS_WITH_INCOMPLETE:
        lines.append(
            "- **WARNING: PASS_WITH_INCOMPLETE is not a PASS - some flows were not fully measured.**"
        )
    lines.extend(f"- reason: {reason}" for reason in verdict.reasons)
    lines.extend(["", "## Flows", "", *_flow_rows(verdict)])
    lines.extend(["", "## Companies", "", *_company_rows(verdict)])
    lines.extend(
        [
            "",
            "## Invariance (data hash + warning codes)",
            "",
            *_invariance_rows(entries),
        ]
    )
    lines.extend(["", "## Invalid and missing", ""])
    invalid = cast("dict[str, dict[str, int]]", result["invalid_samples"])
    lines.extend(
        f"- invalid samples in {arm}: {pair} x{count}"
        for arm in ("base", "new")
        for pair, count in sorted(invalid[arm].items())
    )
    lines.extend(
        f"- {flow.flow}: {flow.status}"
        for flow in verdict.flows
        if flow.status != "COMPLETE"
    )
    lines.extend(
        f"- representative {flow} not measured in either arm"
        for flow in verdict.missing_representative
    )
    return "\n".join(lines) + "\n"


def _invalid_samples(records: list[FlowRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        if record.get("valid") is not True:
            pair = f"{record.get('flow')}/{record.get('corp_code')}"
            counts[pair] = counts.get(pair, 0) + 1
    return counts


def _directories(namespace: argparse.Namespace) -> tuple[Path, Path, Path, bool]:
    if namespace.ab:
        if namespace.exclude_cold or namespace.exclude_first_in_session:
            raise CompareError(AB_EXCLUSION_REFUSAL)
        ab_dir = Path(namespace.ab)
        out_dir = Path(namespace.out) if namespace.out else ab_dir
        return ab_dir / "A", ab_dir / "B", out_dir, True
    if namespace.base and namespace.new:
        new_dir = Path(namespace.new)
        out_dir = Path(namespace.out) if namespace.out else new_dir
        return Path(namespace.base), new_dir, out_dir, False
    msg = "give --ab <dir> or both --base and --new"
    raise CompareError(msg)


def compare(namespace: argparse.Namespace) -> int:
    base_dir, new_dir, out_dir, is_ab = _directories(namespace)
    arm_roots = verify_ab_arms(Path(namespace.ab)) if is_ab else None
    target, representative = _resolve_representative(namespace, base_dir, new_dir)

    def kept(records: list[FlowRecord]) -> list[FlowRecord]:
        return [
            record
            for record in records
            if not _excluded(
                record,
                cold=namespace.exclude_cold,
                first=namespace.exclude_first_in_session,
            )
        ]

    base = kept(load_flows(base_dir))
    new = kept(load_flows(new_dir))
    flows = assess_flows(
        base,
        new,
        representative,
        target_reduction=namespace.target_reduction,
        max_regression=namespace.max_regression,
    )
    entries = invariance_entries(base, new)
    verdict = oracle_verdict(
        flows,
        representative,
        invariance=invariance_verdict(
            [entry.status for entry in entries],
            allow_incomplete=namespace.allow_incomplete,
        ),
        invariance_reasons=[
            f"{entry.flow}/{entry.corp_code} {entry.status}"
            for entry in entries
            if entry.status != "identical"
        ],
        allow_incomplete=namespace.allow_incomplete,
    )
    excluded = [
        name
        for name, flag in (
            ("possibly_cold", namespace.exclude_cold),
            ("first_in_session", namespace.exclude_first_in_session),
        )
        if flag
    ]
    result: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "base": str(base_dir.resolve()),
        "new": str(new_dir.resolve()),
        "mode": "ab" if is_ab else "runs",
        "arm_code_roots": arm_roots,
        "target": target,
        "representative": list(representative),
        "target_reduction": namespace.target_reduction,
        "max_regression": namespace.max_regression,
        "allow_incomplete": namespace.allow_incomplete,
        "excluded": excluded,
        "invalid_samples": {
            "base": _invalid_samples(base),
            "new": _invalid_samples(new),
        },
        "invariance": [asdict(entry) for entry in entries],
        "verdict": {
            "latency": verdict.latency.value,
            "invariance": verdict.invariance.value,
            "overall": verdict.overall.value,
            "reasons": list(verdict.reasons),
            "missing_representative": list(verdict.missing_representative),
            "flows": [asdict(flow) for flow in verdict.flows],
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "comparison.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    markdown = render_markdown(result, entries, verdict)
    (out_dir / "comparison.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"wrote {out_dir / 'comparison.json'} and comparison.md")
    return EXIT_CODES[verdict.overall]


# ---------------------------------------------------------------- combine


def _combine_input(path: Path) -> CombineInput:
    data = _load_json_object(path)
    if data is None or data.get("schema_version") != SCHEMA_VERSION:
        msg = f"{path}: not a schema {SCHEMA_VERSION} comparison.json (re-run compare_runs)"
        raise CompareError(msg)
    verdict = cast("dict[str, object]", data["verdict"])
    flows = cast("list[dict[str, object]]", verdict["flows"])
    return CombineInput(
        source=str(path),
        overall=Verdict(str(verdict["overall"])),
        passing_representatives=frozenset(
            str(flow["flow"])
            for flow in flows
            if flow.get("representative") is True and flow.get("passed") is True
        ),
    )


def combine(namespace: argparse.Namespace) -> int:
    paths = [Path(value) for value in namespace.inputs]
    inputs = [_combine_input(path) for path in paths]
    required = (
        _split(namespace.require)
        if namespace.require is not None
        else catalog_representatives()
    )
    verdict, reasons = combine_verdicts(inputs, required)
    result = {
        "schema_version": SCHEMA_VERSION,
        "inputs": [
            {
                "source": item.source,
                "overall": item.overall.value,
                "passing_representatives": sorted(item.passing_representatives),
            }
            for item in inputs
        ],
        "required_representatives": list(required),
        "overall": verdict.value,
        "reasons": list(reasons),
    }
    lines = [
        "# Combined latency verdict",
        "",
        f"- required representatives: {', '.join(required)}",
        f"- overall: **{verdict}**",
        *(f"- reason: {reason}" for reason in reasons),
        "",
        "| comparison | overall | passing representatives |",
        "|---|---|---|",
        *(
            f"| `{item.source}` | {item.overall} | {', '.join(sorted(item.passing_representatives)) or '-'} |"
            for item in inputs
        ),
    ]
    markdown = "\n".join(lines) + "\n"
    out_dir = Path(namespace.out) if namespace.out else paths[0].resolve().parent
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "combined.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "combined.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"wrote {out_dir / 'combined.json'} and combined.md")
    return EXIT_CODES[verdict]


# ---------------------------------------------------------------- CLI


def _compare_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare two latency-harness runs")
    parser.add_argument("--base", default=None)
    parser.add_argument("--new", default=None)
    parser.add_argument("--ab", default=None, help="an ab run dir holding A/ and B/")
    parser.add_argument(
        "--representative",
        default=None,
        help="comma-separated flow ids (default: the catalog's representative for the run target)",
    )
    parser.add_argument(
        "--target-reduction", type=float, default=DEFAULT_TARGET_REDUCTION
    )
    parser.add_argument("--max-regression", type=float, default=DEFAULT_MAX_REGRESSION)
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="judge incomplete flows on the companies both arms measured (PASS_WITH_INCOMPLETE, never PASS)",
    )
    parser.add_argument(
        "--exclude-cold", action="store_true", help="drop flows flagged possibly_cold"
    )
    parser.add_argument(
        "--exclude-first-in-session",
        action="store_true",
        help="drop the first flow of every session",
    )
    parser.add_argument("--out", default=None)
    return parser


def _combine_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compare_runs.py combine",
        description="Join comparison.json verdicts (e.g. the local and the remote one)",
    )
    parser.add_argument("inputs", nargs="+", help="comparison.json files")
    parser.add_argument(
        "--require",
        default=None,
        help="comma-separated representatives that must pass (default: all catalog representatives)",
    )
    parser.add_argument("--out", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if arguments[:1] == ["combine"]:
            return combine(_combine_parser().parse_args(arguments[1:]))
        return compare(_compare_parser().parse_args(arguments))
    except CompareError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
