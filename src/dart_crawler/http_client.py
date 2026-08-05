"""HTTP client factory and a narrow response protocol for tests."""

from __future__ import annotations

import logging
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Protocol

import httpx2


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """The response fields used by the DART adapter."""

    status_code: int
    headers: Mapping[str, str]
    content: bytes


class HttpClient(Protocol):
    """Synchronous HTTP capability used by the DART adapter."""

    def get(self, url: str, *, params: dict[str, str]) -> HttpResponse:
        """Fetch one URL with query parameters."""
        raise NotImplementedError

    def close(self) -> None:
        """Release the underlying connection pool."""
        raise NotImplementedError


_LIMITS = httpx2.Limits(
    max_connections=200,
    max_keepalive_connections=40,
    keepalive_expiry=30.0,
)
_TIMEOUT = httpx2.Timeout(connect=5.0, read=30.0, write=10.0, pool=10.0)
_SOCKET_OPTIONS = [(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)]


class HttpxClient(HttpClient):
    """Configured httpx2 client for OpenDART and DART web requests."""

    def __init__(self) -> None:
        logging.getLogger("httpx2").setLevel(logging.WARNING)
        transport = httpx2.HTTPTransport(
            http2=True,
            retries=3,
            limits=_LIMITS,
            socket_options=_SOCKET_OPTIONS,
        )
        self._client = httpx2.Client(
            transport=transport,
            timeout=_TIMEOUT,
            follow_redirects=True,
        )

    def get(self, url: str, *, params: Mapping[str, str]) -> HttpResponse:
        """Fetch one URL and detach its content from the client."""
        response = self._client.get(url, params=params)
        return HttpResponse(
            status_code=response.status_code,
            headers=dict(response.headers),
            content=response.content,
        )

    def close(self) -> None:
        """Close the httpx2 connection pool."""
        self._client.close()

    def __enter__(self) -> HttpxClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.close()
