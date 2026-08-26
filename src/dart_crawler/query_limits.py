from dataclasses import dataclass, replace
from typing import Final


@dataclass(frozen=True, slots=True)
class QueryLimits:
    """Limits shared by the query services in one runtime environment."""

    max_companies_per_query: int
    max_topics_per_query: int
    max_response_rows: int | None
    max_response_cells: int | None
    max_response_text_chars: int | None


MAX_COMPANIES_PER_QUERY: Final = 10
MAX_TOPICS_PER_QUERY: Final = 10
# Rows are about 20 fields wide, so 1,000 rows aligns with the 20,000-cell
# section response budget.
MAX_RESPONSE_ROWS: Final = 1_000
# Oversized responses fail instead of being truncated because a truncated
# report cannot be reconciled with its source.
MAX_RESPONSE_CELLS: Final = 20_000
# Narrative text is measured separately because notes and opinions can contain
# no table cells while still producing an oversized response.
MAX_RESPONSE_TEXT_CHARS: Final = 200_000

REMOTE_QUERY_LIMITS: Final = QueryLimits(
    max_companies_per_query=MAX_COMPANIES_PER_QUERY,
    max_topics_per_query=MAX_TOPICS_PER_QUERY,
    max_response_rows=MAX_RESPONSE_ROWS,
    max_response_cells=MAX_RESPONSE_CELLS,
    max_response_text_chars=MAX_RESPONSE_TEXT_CHARS,
)
LOCAL_QUERY_LIMITS: Final = replace(
    REMOTE_QUERY_LIMITS,
    max_response_rows=None,
    max_response_cells=None,
    max_response_text_chars=None,
)
DEFAULT_QUERY_LIMITS: Final = REMOTE_QUERY_LIMITS
