import pytest
import requests

import tacticus_api_client as client


class FakeResponse:
    def __init__(self, status_code, body=None, invalid_json=False):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._body = body
        self._invalid_json = invalid_json

    def json(self):
        if self._invalid_json:
            raise ValueError("not JSON")
        return self._body


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def get(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def test_get_json_returns_body_and_sends_key_with_timeout():
    session = FakeSession(FakeResponse(200, {"entries": []}))

    body = client.get_json(session, "/guildRaid", "secret")

    assert body == {"entries": []}
    (call,) = session.calls
    assert call["url"].endswith("/guildRaid")
    assert call["headers"] == {"x-api-key": "secret"}
    assert call["timeout"] == client.REQUEST_TIMEOUT_SECONDS


def test_get_json_surfaces_api_error_type():
    session = FakeSession(FakeResponse(403, {"type": "FORBIDDEN", "code": 2}))

    with pytest.raises(client.TacticusApiError) as raised:
        client.get_json(session, "/guildRaid", "secret")

    assert (raised.value.status, raised.value.detail) == (403, "FORBIDDEN")
    assert "HTTP 403 (FORBIDDEN)" in str(raised.value)


def test_get_json_handles_error_without_json_body():
    session = FakeSession(FakeResponse(502, invalid_json=True))

    with pytest.raises(client.TacticusApiError) as raised:
        client.get_json(session, "/player", "secret")

    assert (raised.value.status, raised.value.detail) == (502, None)


def test_get_json_wraps_network_errors():
    session = FakeSession(error=requests.ConnectionError("offline"))

    with pytest.raises(client.TacticusApiError) as raised:
        client.get_json(session, "/player", "secret")

    assert raised.value.status is None
    assert "offline" in str(raised.value)


def test_get_json_rejects_non_json_success():
    session = FakeSession(FakeResponse(200, invalid_json=True))

    with pytest.raises(client.TacticusApiError, match="not JSON"):
        client.get_json(session, "/player", "secret")
