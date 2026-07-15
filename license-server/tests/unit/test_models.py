from __future__ import annotations

from app.db.models import DeviceBinding, License


def test_active_binding_partial_unique_index_exists() -> None:
    index = next(
        item for item in DeviceBinding.__table__.indexes if item.name == "uq_device_bindings_active_license"
    )
    assert index.unique is True
    assert "status = 'ACTIVE'" in str(index.dialect_options["postgresql"]["where"])


def test_license_code_hash_is_unique_but_mask_is_not_plaintext() -> None:
    assert License.__table__.c.license_code_hash.unique is True
    assert License.__table__.c.license_code_masked.unique is not True


def test_license_type_enum_persists_public_lowercase_values() -> None:
    assert License.__table__.c.license_type.type.enums == [
        "monthly",
        "yearly",
        "permanent",
        "fixed_date",
    ]
