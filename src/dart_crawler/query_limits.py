from dataclasses import dataclass, replace
from typing import Final


@dataclass(frozen=True, slots=True)
class QueryPolicy:
    """Immutable input scope and response budget for one service request."""

    max_response_rows: int | None
    max_response_cells: int | None
    max_response_text_chars: int | None
    max_companies_per_query: int = 100
    all_registered_selections: bool = True


QueryLimits = QueryPolicy

MAX_COMPANIES_PER_QUERY: Final = 100
MAX_TOPICS_PER_QUERY: Final = 100
# Rows are about 20 fields wide, so 1,000 rows aligns with the 20,000-cell
# section response budget.
MAX_RESPONSE_ROWS: Final = 1_000
# Oversized responses fail instead of being truncated because a truncated
# report cannot be reconciled with its source.
MAX_RESPONSE_CELLS: Final = 20_000
# Narrative text is measured separately because notes and opinions can contain
# no table cells while still producing an oversized response.
MAX_RESPONSE_TEXT_CHARS: Final = 200_000

NORMAL_POLICY: Final = QueryPolicy(
    max_response_rows=MAX_RESPONSE_ROWS,
    max_response_cells=MAX_RESPONSE_CELLS,
    max_response_text_chars=MAX_RESPONSE_TEXT_CHARS,
)
EXCEL_POLICY: Final = replace(
    NORMAL_POLICY,
    max_response_rows=None,
    max_response_cells=None,
    max_response_text_chars=None,
)
REMOTE_QUERY_LIMITS: Final = NORMAL_POLICY
LOCAL_QUERY_LIMITS: Final = EXCEL_POLICY
DEFAULT_QUERY_LIMITS: Final = NORMAL_POLICY
