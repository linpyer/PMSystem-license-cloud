from __future__ import annotations

import hashlib

import pytest

from app.licensing.device_fingerprint import build_device_id, normalize_identifier
from app.licensing.errors import DeviceFingerprintError


@pytest.mark.parametrize(
    "raw",
    ["", "  ", None, "UNKNOWN", "to be filled by o.e.m.", "DEFAULT STRING", "NONE",
     "NOT SPECIFIED", "SYSTEM SERIAL NUMBER", "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF"],
)
def test_invalid_hardware_values_are_removed(raw):
    assert normalize_identifier(raw) == ""


def test_normalization_is_stable():
    assert normalize_identifier("  ab c  \t def ") == "AB C DEF"


def test_same_inputs_always_produce_same_device_id():
    values = {"machineGuid": "abc", "biosUuid": "def"}
    assert build_device_id(values) == build_device_id(values)


def test_input_order_does_not_change_device_id():
    assert build_device_id({"machineGuid": "abc", "biosUuid": "def"}) == build_device_id(
        {"biosUuid": "def", "machineGuid": "abc"}
    )


def test_empty_values_do_not_change_device_id():
    assert build_device_id({"machineGuid": "abc"}) == build_device_id(
        {"machineGuid": "abc", "biosUuid": "UNKNOWN"}
    )


def test_device_id_is_sha256_and_contains_no_raw_value():
    result = build_device_id({"machineGuid": "secret-machine-guid"})
    assert result == hashlib.sha256(b"machineguid=SECRET-MACHINE-GUID").hexdigest()
    assert len(result) == 64 and "SECRET" not in result


def test_no_stable_values_fails_closed():
    with pytest.raises(DeviceFingerprintError):
        build_device_id({"machineGuid": "UNKNOWN", "biosUuid": ""})
