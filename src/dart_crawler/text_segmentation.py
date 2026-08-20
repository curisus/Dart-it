"""Text segmentation rules shared by block capture and source verification.

Both the markup parser and the independent source scanner must agree on where
visible text breaks apart, so every rule lives here and nowhere else.
"""

from __future__ import annotations

import re
from typing import Final

_ITEM_MARKER: Final = re.compile(r"\(\d{1,2}\)")
_GLUED_ITEM_MARKER: Final = re.compile(r"(?<=\.)(?=\(\d{1,2}\))")
_NOTE_NUMBER: Final = re.compile(r"^\d+\.\s")


def split_source_tokens(text: str) -> list[str]:
    """Tokenize visible text, detaching item markers glued to a sentence end."""
    return [
        piece for token in text.split() for piece in _GLUED_ITEM_MARKER.split(token)
    ]


def split_item_rows(text: str) -> tuple[str, ...]:
    """Split one paragraph into a leading note title and numbered item rows.

    A row starts at an item marker that closes a sentence, and at the first
    marker following a note number heading. Markers without such a boundary,
    and a trailing marker that would leave a row holding nothing else, stay
    inside the current row.
    """
    rows: list[str] = []
    cursor = 0
    content_end = len(text.rstrip())
    title_break_allowed = _NOTE_NUMBER.match(text.lstrip()) is not None
    for marker in _ITEM_MARKER.finditer(text):
        start = marker.start()
        if start > cursor and marker.end() < content_end:
            head_end = start
            while head_end > cursor and text[head_end - 1].isspace():
                head_end -= 1
            if head_end > cursor and (
                text[head_end - 1] == "."
                or (title_break_allowed and head_end != start)
            ):
                rows.append(text[cursor:head_end])
                cursor = start
        title_break_allowed = False
    rows.append(text[cursor:])
    return tuple(rows)
