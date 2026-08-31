from dataclasses import FrozenInstanceError

import anyio
import anyio.lowlevel
import pytest

from dart_crawler import query_limits


def test_normal_and_excel_policies_are_immutable_and_scoped() -> None:
    # Given: the two request policy profiles.
    normal = query_limits.NORMAL_POLICY
    excel = query_limits.EXCEL_POLICY

    # When/Then: input scope is shared while only Excel removes response caps.
    assert normal.max_companies_per_query == 100
    assert excel.max_companies_per_query == 100
    assert normal.all_registered_selections is True
    assert excel.all_registered_selections is True
    assert normal.max_response_rows == 1_000
    assert normal.max_response_cells == 20_000
    assert normal.max_response_text_chars == 200_000
    assert excel.max_response_rows is None
    assert excel.max_response_cells is None
    assert excel.max_response_text_chars is None
    with pytest.raises(FrozenInstanceError):
        normal.__setattr__("max_response_rows", None)


@pytest.mark.anyio
async def test_concurrent_and_cancelled_policy_use_cannot_leak() -> None:
    # Given: concurrent normal and Excel requests plus one cancelled request.
    observed: list[tuple[str, int | None]] = []
    normal_before = query_limits.NORMAL_POLICY
    excel_before = query_limits.EXCEL_POLICY

    async def observe(label: str, policy: query_limits.QueryPolicy) -> None:
        await anyio.lowlevel.checkpoint()
        observed.append((label, policy.max_response_rows))

    async def cancel_without_mutation() -> None:
        with anyio.CancelScope() as scope:
            scope.cancel()
            await anyio.lowlevel.checkpoint()

    # When: policy objects are read in interleaved tasks and one task is cancelled.
    async with anyio.create_task_group() as task_group:
        for _ in range(20):
            task_group.start_soon(observe, "normal", query_limits.NORMAL_POLICY)
            task_group.start_soon(observe, "excel", query_limits.EXCEL_POLICY)
        task_group.start_soon(cancel_without_mutation)

    # Then: each request observes only its profile and both shared values stay unchanged.
    assert observed.count(("normal", 1_000)) == 20
    assert observed.count(("excel", None)) == 20
    assert query_limits.NORMAL_POLICY is normal_before
    assert query_limits.EXCEL_POLICY is excel_before
    assert query_limits.NORMAL_POLICY.max_response_rows == 1_000
    assert query_limits.EXCEL_POLICY.max_response_rows is None
