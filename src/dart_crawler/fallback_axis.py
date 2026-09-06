"""What a FALLBACK_SOURCE_USED warning is actually reporting.

One warning code covers three unrelated substitutions, and the 2026-09-06
campaign saw it on essentially every source read, which left it carrying no
signal. The axis says which substitution happened so a reader can tell the
routine case from the one worth looking at.
"""

from __future__ import annotations

from enum import StrEnum, unique
from typing import Final

FALLBACK_AXIS_KEY: Final = "fallback_axis"


@unique
class FallbackAxis(StrEnum):
    """The three substitutions FALLBACK_SOURCE_USED reports."""

    # The OpenDART original-document ZIP was unavailable, so the filing was
    # read from the DART viewer instead. This one changes where the content
    # came from and is the only axis that can change what the content is.
    SOURCE = "source"
    # The attachment did not parse as strict XML, so the HTML-compatible parser
    # read it. Routine: nearly every OpenDART attachment takes this path.
    PARSER = "parser"
    # The report body carried no authored date, so the filing receipt date was
    # used to name the output file. Nothing about the content is affected.
    FILENAME_DATE = "filename_date"
