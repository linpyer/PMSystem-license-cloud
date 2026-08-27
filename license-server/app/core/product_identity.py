from __future__ import annotations


PRODUCT_DISPLAY_NAME = "iVRec"
PRODUCT_PACKAGE_NAME = "iVRec"

# Batch 1 only separates protocol identity from brand identity. The active
# server contract remains DDREC until Client, Server, Release and signatures
# move to iVRec together.
LEGACY_LICENSE_PROTOCOL_PRODUCT = "DDREC"
TARGET_LICENSE_PROTOCOL_PRODUCT = "iVRec"
ACTIVE_LICENSE_PROTOCOL_PRODUCT = LEGACY_LICENSE_PROTOCOL_PRODUCT

LEGACY_UPDATE_PROTOCOL_PRODUCT = "DDREC"
TARGET_UPDATE_PROTOCOL_PRODUCT = "iVRec"
ACTIVE_UPDATE_PROTOCOL_PRODUCT = LEGACY_UPDATE_PROTOCOL_PRODUCT

ADMIN_TOTP_ISSUER_NAME = "iVRec License Admin"
