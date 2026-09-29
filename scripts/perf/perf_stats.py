"""Pure latency statistics and the redesign oracle for the perf harness.

Every function here is a pure computation over already-recorded numbers, so
the unit tests exercise it with tiny synthetic samples and no I/O.

Oracle (the bar a later redesign is judged against):
- a flow's reduction is the median over companies of each company's own
  reduction ``(median_base - median_new) / median_base``, so a change in the
  mix of companies (or of reps per company) can never move it; the pooled
  median over all samples is informational only;
- every representative flow must reach ``target_reduction`` (0.5 = the new
  median is at most half of the base median);
- every other flow may not get slower by more than ``max_regression``
  (0.10 = the new median is at most 110% of the base median);
- the result data must be identical (decided by the caller, passed in).

Completeness comes before the verdict. A (flow, company) is complete when both
arms have the same, non-zero number of valid samples and neither arm has an
invalid one. A flow is COMPLETE when all its companies are, MISSING when it
was recorded in one arm only or has no valid sample in either arm, and
INCOMPLETE otherwise. Any INCOMPLETE or MISSING flow fails the comparison, so
no rule ever passes unmeasured. ``allow_incomplete`` relaxes that to the
separate verdict PASS_WITH_INCOMPLETE (never PASS): INCOMPLETE flows are then
judged on the companies both arms measured, and a secondary flow without any
such company is tolerated but listed. A representative flow must always be
measured and pass; a missing or unmeasurable one fails even then.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

DEFAULT_TARGET_REDUCTION: Final = 0.5
DEFAULT_MAX_REGRESSION: Final = 0.10


class Verdict(StrEnum):
    PASS = "PASS"  # noqa: S105 - a verdict label, not a credential
    PASS_WITH_INCOMPLETE = "PASS_WITH_INCOMPLETE"  # noqa: S105 - a verdict label
    FAIL = "FAIL"


class FlowStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    MISSING = "MISSING"


@dataclass(frozen=True, slots=True)
class LatencySummary:
    n: int
    median_ms: float
    p90_ms: float
    min_ms: float
    max_ms: float


@dataclass(frozen=True, slots=True)
class CompanySamples:
    """One company's valid latencies and invalid-sample counts in both arms."""

    corp_code: str
    base_ms: tuple[float, ...]
    new_ms: tuple[float, ...]
    base_invalid: int = 0
    new_invalid: int = 0

    @property
    def complete(self) -> bool:
        return (
            self.base_invalid == 0
            and self.new_invalid == 0
            and len(self.base_ms) == len(self.new_ms)
            and len(self.base_ms) > 0
        )


@dataclass(frozen=True, slots=True)
class CompanyResult:
    corp_code: str
    n_base: int
    n_new: int
    invalid_base: int
    invalid_new: int
    base_median_ms: float | None
    new_median_ms: float | None
    reduction: float | None


@dataclass(frozen=True, slots=True)
class FlowAssessment:
    flow: str
    representative: bool
    status: FlowStatus
    companies: tuple[CompanyResult, ...]
    reduction: float | None
    passed: bool | None
    requirement: str
    pooled_base: LatencySummary | None
    pooled_new: LatencySummary | None


@dataclass(frozen=True, slots=True)
class OracleVerdict:
    latency: Verdict
    invariance: Verdict
    overall: Verdict
    flows: tuple[FlowAssessment, ...]
    missing_representative: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CombineInput:
    """One comparison's overall verdict and the representatives it passed."""

    source: str
    overall: Verdict
    passing_representatives: frozenset[str]


def _require_samples(values: Sequence[float]) -> None:
    if not values:
        msg = "at least one latency sample is required"
        raise ValueError(msg)
    if any(not math.isfinite(value) for value in values):
        msg = "latency samples must be finite numbers"
        raise ValueError(msg)


def median(values: Sequence[float]) -> float:
    _require_samples(values)
    return float(statistics.median(values))


def percentile(values: Sequence[float], fraction: float) -> float:
    """Linear-interpolation percentile (the numpy "linear" method).

    The rank is ``(n - 1) * fraction`` over the sorted samples, interpolated
    between its two neighbours, so a single sample is its own percentile.
    """
    _require_samples(values)
    if not 0.0 <= fraction <= 1.0:
        msg = "percentile fraction must be within [0, 1]"
        raise ValueError(msg)
    ordered = sorted(values)
    rank = (len(ordered) - 1) * fraction
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(ordered[lower])
    weight = rank - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * weight)


def p90(values: Sequence[float]) -> float:
    return percentile(values, 0.9)


def summarize(values: Sequence[float]) -> LatencySummary:
    _require_samples(values)
    return LatencySummary(
        n=len(values),
        median_ms=median(values),
        p90_ms=p90(values),
        min_ms=float(min(values)),
        max_ms=float(max(values)),
    )


def reduction_ratio(base_median_ms: float, new_median_ms: float) -> float:
    """Fraction of the base median removed by the new run (negative = slower)."""
    if not math.isfinite(base_median_ms) or base_median_ms <= 0:
        msg = "base median must be a positive finite number"
        raise ValueError(msg)
    if not math.isfinite(new_median_ms) or new_median_ms < 0:
        msg = "new median must be a non-negative finite number"
        raise ValueError(msg)
    return (base_median_ms - new_median_ms) / base_median_ms


def requirement(
    *,
    representative: bool,
    target_reduction: float = DEFAULT_TARGET_REDUCTION,
    max_regression: float = DEFAULT_MAX_REGRESSION,
) -> float:
    """The minimum reduction a flow must reach."""
    return target_reduction if representative else -max_regression


def company_result(samples: CompanySamples) -> CompanyResult:
    """A company's medians in both arms and its own reduction (None if unmeasurable)."""
    base_median = median(samples.base_ms) if samples.base_ms else None
    new_median = median(samples.new_ms) if samples.new_ms else None
    reduction = (
        reduction_ratio(base_median, new_median)
        if base_median is not None and new_median is not None and base_median > 0
        else None
    )
    return CompanyResult(
        corp_code=samples.corp_code,
        n_base=len(samples.base_ms),
        n_new=len(samples.new_ms),
        invalid_base=samples.base_invalid,
        invalid_new=samples.new_invalid,
        base_median_ms=base_median,
        new_median_ms=new_median,
        reduction=reduction,
    )


def flow_status(
    companies: Sequence[CompanySamples], *, in_base: bool, in_new: bool
) -> FlowStatus:
    """COMPLETE / INCOMPLETE / MISSING, per the module docstring."""
    has_valid = any(company.base_ms or company.new_ms for company in companies)
    if not (in_base and in_new) or not has_valid:
        return FlowStatus.MISSING
    if companies and all(company.complete for company in companies):
        return FlowStatus.COMPLETE
    return FlowStatus.INCOMPLETE


def assess_flow(
    flow: str,
    companies: Sequence[CompanySamples],
    *,
    in_base: bool,
    in_new: bool,
    representative: bool,
    target_reduction: float = DEFAULT_TARGET_REDUCTION,
    max_regression: float = DEFAULT_MAX_REGRESSION,
) -> FlowAssessment:
    """Status, per-company reductions and the company-median reduction of one flow."""
    ordered = sorted(companies, key=lambda company: company.corp_code)
    results = tuple(company_result(company) for company in ordered)
    measured = [result.reduction for result in results if result.reduction is not None]
    reduction = median(measured) if measured else None
    minimum = requirement(
        representative=representative,
        target_reduction=target_reduction,
        max_regression=max_regression,
    )
    base_samples = [value for company in ordered for value in company.base_ms]
    new_samples = [value for company in ordered for value in company.new_ms]
    return FlowAssessment(
        flow=flow,
        representative=representative,
        status=flow_status(ordered, in_base=in_base, in_new=in_new),
        companies=results,
        reduction=reduction,
        passed=None if reduction is None else reduction >= minimum,
        requirement=f"company-median reduction >= {minimum}",
        pooled_base=summarize(base_samples) if base_samples else None,
        pooled_new=summarize(new_samples) if new_samples else None,
    )


def worst(*verdicts: Verdict) -> Verdict:
    """FAIL beats PASS_WITH_INCOMPLETE beats PASS."""
    if Verdict.FAIL in verdicts:
        return Verdict.FAIL
    if Verdict.PASS_WITH_INCOMPLETE in verdicts:
        return Verdict.PASS_WITH_INCOMPLETE
    return Verdict.PASS


def _latency_verdict(
    flows: Sequence[FlowAssessment],
    missing_representative: Sequence[str],
    *,
    allow_incomplete: bool,
) -> tuple[Verdict, list[str]]:
    failures: list[str] = []
    incomplete: list[str] = []
    for flow in flows:
        if flow.passed is False:
            failures.append(
                f"{flow.flow}: reduction {flow.reduction:+.3f} misses {flow.requirement}"
            )
        if flow.status is FlowStatus.COMPLETE:
            continue
        if flow.representative and flow.passed is None:
            failures.append(f"{flow.flow}: representative flow is {flow.status}")
        else:
            incomplete.append(f"{flow.flow}: {flow.status}")
    failures.extend(
        f"{flow}: representative flow is MISSING" for flow in missing_representative
    )
    if not any(flow.representative for flow in flows) and not missing_representative:
        failures.append("no representative flow was named")
    if failures:
        return Verdict.FAIL, failures + incomplete
    if incomplete:
        if allow_incomplete:
            return Verdict.PASS_WITH_INCOMPLETE, incomplete
        return Verdict.FAIL, [
            *incomplete,
            "incomplete flows fail the comparison (see --allow-incomplete)",
        ]
    return Verdict.PASS, []


def oracle_verdict(
    flows: Sequence[FlowAssessment],
    representative: Collection[str],
    *,
    invariance: Verdict,
    invariance_reasons: Sequence[str] = (),
    allow_incomplete: bool = False,
) -> OracleVerdict:
    """Combine per-flow assessments and the invariance verdict into one verdict."""
    names = {flow.flow for flow in flows}
    missing = tuple(sorted(set(representative) - names))
    latency, reasons = _latency_verdict(
        flows, missing, allow_incomplete=allow_incomplete
    )
    if invariance is not Verdict.PASS:
        reasons.append(f"invariance {invariance}")
        reasons.extend(f"invariance: {reason}" for reason in invariance_reasons)
    return OracleVerdict(
        latency=latency,
        invariance=invariance,
        overall=worst(latency, invariance),
        flows=tuple(flows),
        missing_representative=missing,
        reasons=tuple(reasons),
    )


def invariance_verdict(
    statuses: Sequence[str], *, allow_incomplete: bool = False
) -> Verdict:
    """identical everywhere = PASS; a difference or unstable arm = FAIL.

    A (flow, company) that an arm never measured validly ("missing_base",
    "missing_new", "missing_both") is unchecked: FAIL, or PASS_WITH_INCOMPLETE
    when incompleteness is allowed.
    """
    if not statuses:
        return Verdict.FAIL
    if any(
        status in {"different", "unstable_base", "unstable_new"} for status in statuses
    ):
        return Verdict.FAIL
    if any(status != "identical" for status in statuses):
        return Verdict.PASS_WITH_INCOMPLETE if allow_incomplete else Verdict.FAIL
    return Verdict.PASS


def combine_verdicts(
    inputs: Sequence[CombineInput], required: Collection[str]
) -> tuple[Verdict, tuple[str, ...]]:
    """PASS only when every input passed and every required representative passed somewhere."""
    reasons = [
        f"{item.source}: overall FAIL"
        for item in inputs
        if item.overall is Verdict.FAIL
    ]
    if not inputs:
        reasons.append("no comparison given")
    covered: set[str] = set()
    for item in inputs:
        covered |= item.passing_representatives
    reasons.extend(
        f"representative {flow} did not pass in any comparison"
        for flow in sorted(set(required) - covered)
    )
    if reasons:
        return Verdict.FAIL, tuple(reasons)
    labels = [
        f"{item.source}: PASS_WITH_INCOMPLETE"
        for item in inputs
        if item.overall is Verdict.PASS_WITH_INCOMPLETE
    ]
    if labels:
        return Verdict.PASS_WITH_INCOMPLETE, tuple(labels)
    return Verdict.PASS, ()
