from __future__ import annotations

import time
from typing import Any, Protocol

import requests


class JsonClient(Protocol):
    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any: ...


class OfficialHttpError(RuntimeError):
    """La font oficial no ha pogut retornar un payload vàlid."""


class RequestsJsonClient:
    def __init__(self, timeout: float = 30, retries: int = 3) -> None:
        self.timeout = timeout
        self.retries = retries

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = requests.get(url, params=params, headers=headers, timeout=self.timeout)
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                if response.status_code >= 400:
                    raise OfficialHttpError(f"HTTP {response.status_code} en {response.url}")
                try:
                    return response.json()
                except ValueError as exc:
                    raise OfficialHttpError(f"JSON invàlid en {response.url}") from exc
            except (requests.RequestException, OfficialHttpError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                time.sleep(0.5 * (2**attempt))
        raise OfficialHttpError(f"Error consultant {url}: {last_error}") from last_error
