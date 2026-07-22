"""Bounded read-only HTTP transport for remote discovery metadata."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class HttpRequestError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class ReadOnlyHttpTransport:
    """Issue bounded GET requests without exposing credentials in errors."""

    def __init__(
        self,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float = 10.0,
        max_bytes: int = 5_000_000,
    ) -> None:
        self._headers = {"Accept": "application/json", **dict(headers or {})}
        self._timeout = timeout
        self._max_bytes = max_bytes

    def get_json(self, url: str, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        try:
            payload = json.loads(self.get_text(url, params=params))
        except json.JSONDecodeError as exc:
            raise HttpRequestError("remote source returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise HttpRequestError("remote source JSON must be an object")
        return cast(Mapping[str, Any], payload)

    def get_text(self, url: str, *, params: Mapping[str, str]) -> str:
        target = f"{url}?{urlencode(params)}" if params else url
        request = Request(target, headers=self._headers, method="GET")
        try:
            with urlopen(request, timeout=self._timeout) as response:
                raw = response.read(self._max_bytes + 1)
        except HTTPError as exc:
            raise HttpRequestError(
                f"remote source returned HTTP {exc.code}", status_code=exc.code
            ) from exc
        except (OSError, TimeoutError, URLError) as exc:
            raise HttpRequestError("remote source is unavailable") from exc
        if len(raw) > self._max_bytes:
            raise HttpRequestError("remote source response exceeded size limit")
        try:
            decoded: str = raw.decode("utf-8")
            return decoded
        except UnicodeDecodeError as exc:
            raise HttpRequestError("remote source response was not UTF-8") from exc
