"""Turn a proposed name into one Windows will actually accept.

Kept apart from ``output_file`` so the query-export path can reuse it without
pulling in the source-preserving workbook validation that module depends on.
"""

from __future__ import annotations

import os
import re
from typing import Final

_ILLEGAL_CHARACTERS: Final = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# Windows refuses these names with any extension, so a report titled "AUX" or a
# domain that ever ends up as "COM1" must not become the whole stem.
_RESERVED_STEMS: Final[frozenset[str]] = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "CONIN$",
        "CONOUT$",
        *(f"COM{digit}" for digit in range(1, 10)),
        *(f"LPT{digit}" for digit in range(1, 10)),
    }
)
# Well inside the 255-character path-component limit, leaving room for the
# collision suffix and the directories the file is written under.
MAX_FILENAME_STEM_CHARS: Final = 220


def safe_filename(filename: str) -> str:
    """Return the name with reserved characters, words, and length handled."""
    cleaned = _ILLEGAL_CHARACTERS.sub("_", filename).rstrip(" .")
    stem, suffix = os.path.splitext(cleaned)
    if stem.upper() in _RESERVED_STEMS:
        stem = "_" + stem
    return stem[:MAX_FILENAME_STEM_CHARS] + suffix
