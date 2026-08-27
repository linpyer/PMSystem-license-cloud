from __future__ import annotations

from app.core.product_identity import (
    ACTIVE_LICENSE_PROTOCOL_PRODUCT,
    ACTIVE_UPDATE_PROTOCOL_PRODUCT,
    ADMIN_TOTP_ISSUER_NAME,
    PRODUCT_DISPLAY_NAME,
    PRODUCT_PACKAGE_NAME,
    TARGET_LICENSE_PROTOCOL_PRODUCT,
    TARGET_UPDATE_PROTOCOL_PRODUCT,
)
from app.schemas.client_releases import ClientReleaseDraftRequest


def test_ivrec_brand_and_active_protocols_are_aligned() -> None:
    assert PRODUCT_DISPLAY_NAME == "iVRec"
    assert PRODUCT_PACKAGE_NAME == "iVRec"
    assert ACTIVE_LICENSE_PROTOCOL_PRODUCT == "iVRec"
    assert TARGET_LICENSE_PROTOCOL_PRODUCT == "iVRec"
    assert ACTIVE_UPDATE_PROTOCOL_PRODUCT == "iVRec"
    assert TARGET_UPDATE_PROTOCOL_PRODUCT == "iVRec"
    assert ADMIN_TOTP_ISSUER_NAME == "iVRec License Admin"


def test_client_release_schema_still_uses_active_update_protocol() -> None:
    product_field = ClientReleaseDraftRequest.model_fields["product"]
    assert product_field.default == ACTIVE_UPDATE_PROTOCOL_PRODUCT
    assert ACTIVE_UPDATE_PROTOCOL_PRODUCT in str(product_field.annotation)
