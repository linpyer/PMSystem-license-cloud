from __future__ import annotations

import logging
import sys

import pytest
import requests
import responses

from app.licensing.device_fingerprint import DeviceIdentity
from app.licensing.errors import LicenseApiError
from app.licensing.constants import PRODUCTION_LICENSE_API_BASE_URL
from app.licensing.license_api import LicenseApiClient, normalize_license_code
from tests.licensing.helpers import DEVICE_ID, LICENSE_ID


BASE_URL = "http://127.0.0.1:18080/api/v1"
CODE = "PMS-2345-6789-ABCD-EFGH"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(CODE, CODE), ("pms23456789abcdefgh", CODE), (" 2345 6789 abcd efgh ", CODE)],
)
def test_license_code_normalization(raw, expected):
    assert normalize_license_code(raw) == expected


@pytest.mark.parametrize("raw", ["", "PMS-1234-5678-ABCD-EFGH", "PMS-OOOO-2345-6789-ABCD"])
def test_invalid_license_code_is_rejected(raw):
    with pytest.raises(LicenseApiError) as error:
        normalize_license_code(raw)
    assert error.value.code == "INVALID_REQUEST"


def client(**kwargs):
    return LicenseApiClient(BASE_URL, allow_insecure_http=True, **kwargs)


def test_insecure_http_requires_explicit_development_opt_in():
    with pytest.raises(LicenseApiError, match="HTTP"):
        LicenseApiClient(BASE_URL, allow_insecure_http=False)


def test_loopback_http_requires_explicit_mock_opt_in():
    with pytest.raises(LicenseApiError):
        LicenseApiClient(BASE_URL)


class SuccessfulSession(requests.Session):
    def __init__(self):
        super().__init__()
        self.kwargs = None

    def request(self, *args, **kwargs):
        self.kwargs = kwargs
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"success": true, "status": "ok"}'
        response.headers["Content-Type"] = "application/json"
        return response


def test_frozen_production_client_locks_url_and_tls(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("DDREC_LICENSE_API_BASE_URL", BASE_URL)
    monkeypatch.setenv("DDREC_LICENSE_ALLOW_INSECURE_HTTP", "true")
    session = SuccessfulSession()
    api = LicenseApiClient(BASE_URL, allow_insecure_http=True, session=session)
    assert api.base_url == PRODUCTION_LICENSE_API_BASE_URL
    assert api.health()["status"] == "ok"
    assert session.kwargs["verify"] is True


@responses.activate
def test_health_success():
    responses.get(f"{BASE_URL}/health", json={"success": True, "status": "ok"})
    assert client().health()["status"] == "ok"


@responses.activate
def test_activate_sends_client_metadata_without_logging_code(caplog):
    responses.post(
        f"{BASE_URL}/licenses/activate",
        json={"success": True, "credential": "x" * 40, "license": {}},
    )
    identity = DeviceIdentity(DEVICE_ID, "win-v1", "Test PC", "Windows 11")
    with caplog.at_level(logging.INFO):
        client().activate(CODE, identity)
    body = responses.calls[0].request.body.decode()
    assert CODE in body and '"appVersion": "1.3.0"' in body
    assert CODE not in caplog.text


@responses.activate
def test_trial_activation_sends_device_identity_without_license_code():
    responses.post(
        f"{BASE_URL}/trials/activate",
        json={"success": True, "credential": "x" * 40, "license": {}},
    )
    identity = DeviceIdentity(DEVICE_ID, "win-v1", "Test PC", "Windows 11")
    client().activate_trial(identity)
    body = responses.calls[0].request.body.decode()
    assert '"deviceId"' in body and '"fingerprintVersion": "win-v1"' in body
    assert "licenseCode" not in body


@responses.activate
def test_verify_never_sends_full_activation_code():
    responses.post(f"{BASE_URL}/licenses/verify", json={"success": True, "license": {}})
    record = type("Record", (), {"license_id": LICENSE_ID, "device_id": DEVICE_ID, "credential": "c" * 40})()
    client().verify(record)
    body = responses.calls[0].request.body.decode()
    assert "licenseCode" not in body and CODE not in body and "credential" in body


@responses.activate
def test_server_business_error_is_mapped():
    responses.post(
        f"{BASE_URL}/licenses/verify",
        status=409,
        json={
            "success": False,
            "traceId": "trace-1",
            "error": {"code": "DEVICE_MISMATCH", "message": "mismatch", "retryable": False},
        },
    )
    record = type("Record", (), {"license_id": LICENSE_ID, "device_id": DEVICE_ID, "credential": "c" * 40})()
    with pytest.raises(LicenseApiError) as error:
        client().verify(record)
    assert error.value.code == "DEVICE_MISMATCH"
    assert error.value.trace_id == "trace-1"


@responses.activate
def test_server_500_does_not_crash_client():
    responses.get(f"{BASE_URL}/health", status=500, json={"success": False, "error": {}})
    with pytest.raises(LicenseApiError) as error:
        client().health()
    assert error.value.code == "SERVER_TEMPORARILY_UNAVAILABLE"


@responses.activate
def test_invalid_json_is_safe_error():
    responses.get(f"{BASE_URL}/health", status=502, body="not-json")
    with pytest.raises(LicenseApiError) as error:
        client().health()
    assert error.value.retryable


class TimeoutSession(requests.Session):
    def request(self, *args, **kwargs):
        raise requests.Timeout("timeout")


class ConnectionFailureSession(requests.Session):
    def request(self, *args, **kwargs):
        raise requests.ConnectionError("offline")


@pytest.mark.parametrize("session", [TimeoutSession(), ConnectionFailureSession()])
def test_network_failure_is_retryable_and_bounded(session):
    with pytest.raises(LicenseApiError) as error:
        client(session=session).health()
    assert error.value.code == "SERVER_TEMPORARILY_UNAVAILABLE"
    assert error.value.retryable


@responses.activate
def test_credential_is_not_written_to_logs(caplog):
    secret = "credential-that-must-never-appear-in-logs"
    responses.post(f"{BASE_URL}/licenses/deactivate", json={"success": True, "deactivated": True})
    record = type("Record", (), {"license_id": LICENSE_ID, "device_id": DEVICE_ID, "credential": secret})()
    with caplog.at_level(logging.INFO):
        client().deactivate(record, "test")
    assert secret not in caplog.text
