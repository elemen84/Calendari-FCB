from __future__ import annotations

import pytest
import requests

from src.http_client import OfficialHttpError, RequestsJsonClient
from src.providers.common import SourceDataError
from src.providers.laliga import LaLigaProvider

from .conftest import config


def test_http_error_is_fail_closed(monkeypatch) -> None:
    def timeout(*args, **kwargs):
        raise requests.Timeout("timeout")

    monkeypatch.setattr(requests, "get", timeout)
    with pytest.raises(OfficialHttpError):
        RequestsJsonClient(retries=0).get_json("https://example.invalid")


def test_incomplete_provider_payload_is_rejected() -> None:
    provider = LaLigaProvider(config(), object())
    with pytest.raises(SourceDataError):
        provider._parse_match({"id": 1, "status": "PreMatch"})
