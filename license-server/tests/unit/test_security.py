from __future__ import annotations

import re

import pytest

from app.core.security import (
    canonical_json_bytes,
    credential_matches,
    generate_device_credential,
    generate_license_code,
    hash_device_credential,
    hash_license_code,
    mask_license_code,
    validate_license_code,
)


def test_generated_license_code_has_expected_format_and_alphabet() -> None:
    code = generate_license_code()
    assert re.fullmatch(r"PMS-(?:[A-HJ-KM-NP-Z2-9]{4}-){3}[A-HJ-KM-NP-Z2-9]{4}", code)
    assert not any(character in code for character in "01OIL")


def test_license_code_validation_normalizes_case() -> None:
    assert validate_license_code("pms-abcd-efgh-jkmn-pqrs") == "PMS-ABCD-EFGH-JKMN-PQRS"


def test_invalid_license_code_is_rejected() -> None:
    with pytest.raises(ValueError):
        validate_license_code("PMS-0000-OOOO-1111-LLLL")


def test_license_code_hash_is_hmac_and_mask_hides_secret() -> None:
    code = "PMS-ABCD-EFGH-JKMN-PQRS"
    digest = hash_license_code(code, "pepper-value-longer-than-24")
    assert len(digest) == 64
    assert code not in digest
    assert mask_license_code(code) == "PMS-****-****-****-PQRS"


def test_device_credential_is_one_way_and_constant_time_comparable() -> None:
    credential = generate_device_credential()
    digest = hash_device_credential(credential, "credential-pepper-longer-than-24")
    assert credential not in digest
    assert credential_matches(credential, digest, "credential-pepper-longer-than-24")
    assert not credential_matches(credential + "x", digest, "credential-pepper-longer-than-24")


def test_canonical_json_is_stable_and_compact() -> None:
    assert canonical_json_bytes({"b": 2, "a": "中文"}) == canonical_json_bytes(
        {"a": "中文", "b": 2}
    )
    assert b" " not in canonical_json_bytes({"a": 1, "b": 2})

