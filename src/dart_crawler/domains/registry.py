"""Shared registry helper for OpenDART endpoint domains.

report_topics.py (DS002), ownership.py (DS004), and material_events.py
(DS005) each hold a fixed set of DART endpoints behind a stable key and a
Korean label, and each needs the same duplicate-key/duplicate-endpoint guard
building an immutable mapping. This module defines that shape once instead
of three near-identical copies.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class RegistryEntry:
    """One OpenDART endpoint behind a stable key, with its Korean label."""

    key: str
    endpoint: str
    label: str


def as_registry(
    *entries: RegistryEntry,
    noun: str = "registry",
) -> Mapping[str, RegistryEntry]:
    """Build an immutable, key- and endpoint-unique registry.

    ``noun`` only customizes the ValueError message (e.g. "report topic" so a
    duplicate reads "duplicate report topic key") so a domain's existing
    error text can be preserved; callers that do not need a domain-specific
    message can omit it and get the generic "duplicate registry key/endpoint".
    """
    registry: dict[str, RegistryEntry] = {}
    endpoints: dict[str, str] = {}
    for entry in entries:
        if entry.key in registry:
            msg = f"duplicate {noun} key: {entry.key!r}"
            raise ValueError(msg)
        if entry.endpoint in endpoints:
            msg = f"duplicate {noun} endpoint: {entry.endpoint!r}"
            raise ValueError(msg)
        registry[entry.key] = entry
        endpoints[entry.endpoint] = entry.key
    return MappingProxyType(registry)
