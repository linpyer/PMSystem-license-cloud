from __future__ import annotations

import os

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def private_key():
    return Ed25519PrivateKey.generate()
