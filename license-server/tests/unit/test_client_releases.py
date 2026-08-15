from __future__ import annotations

import base64
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.errors import LicenseServiceError
from app.core.update_manifest import canonical_update_bytes
from app.db.models import ClientRelease
from sqlalchemy import UniqueConstraint
from app.schemas.client_releases import ClientReleaseDraftRequest
from app.services.client_release_service import ClientReleaseService
from app.api.v1.client_updates import latest_client_update


def release(**values) -> ClientRelease:
    defaults = dict(product="DDREC",version="1.3.1",build_number=72,git_commit="abcdef123456",
        edition="license",environment="production",architecture="x64",channel="stable",
        title="DD Rec V1.3.1",release_notes="修复问题",file_name="DDREC-1.3.1-license-Setup.exe",
        download_path="/releases/stable/license/1.3.1/DDREC-1.3.1-license-Setup.exe",
        file_size=12,sha256="A"*64,signature="x"*86,mandatory=False,status="published",
        published_at=datetime(2026,8,15,10,0,tzinfo=timezone.utc),created_by=None)
    defaults.update(values)
    return ClientRelease(**defaults)


class Repo:
    def __init__(self, rows): self.rows=rows
    async def published_candidates(self, _session, **filters):
        return [row for row in self.rows if row.status=="published" and all(getattr(row,{"architecture":"architecture"}.get(key,key))==value for key,value in filters.items())]


@pytest.mark.asyncio
async def test_only_published_is_returned_and_withdrawn_stops_immediately(settings):
    rows=[release(status="draft"),release(status="withdrawn",build_number=73),release(status="published",build_number=74)]
    result=await ClientReleaseService(settings,repository=Repo(rows)).latest(None,product="DDREC",edition="license",environment="production",architecture="x64",channel="stable",version="1.3.0",build_number=64)
    assert result["updateAvailable"] and result["buildNumber"]==74
    rows[2].status="withdrawn"
    assert await ClientReleaseService(settings,repository=Repo(rows)).latest(None,product="DDREC",edition="license",environment="production",architecture="x64",channel="stable",version="1.3.0",build_number=64)=={"updateAvailable":False}


@pytest.mark.asyncio
async def test_version_then_build_ordering_and_no_downgrade(settings):
    rows=[release(version="1.3.0",build_number=68,file_name="DDREC-1.3.0-license-Setup.exe"),release(version="1.3.1",build_number=1)]
    service=ClientReleaseService(settings,repository=Repo(rows))
    result=await service.latest(None,product="DDREC",edition="license",environment="production",architecture="x64",channel="stable",version="1.3.0",build_number=64)
    assert (result["version"],result["buildNumber"])==("1.3.1",1)
    assert await service.latest(None,product="DDREC",edition="license",environment="production",architecture="x64",channel="stable",version="1.4.0",build_number=1)=={"updateAvailable":False}


@pytest.mark.asyncio
async def test_edition_environment_and_channel_are_strict(settings):
    rows=[release(edition="standard",file_name="DDREC-1.3.1-standard-Setup.exe",download_path="/releases/stable/standard/1.3.1/DDREC-1.3.1-standard-Setup.exe"),release(environment="local",channel="dev",file_name="DDREC-1.3.1-license-local-Setup.exe",download_path="/releases/dev/license/1.3.1/DDREC-1.3.1-license-local-Setup.exe")]
    service=ClientReleaseService(settings,repository=Repo(rows))
    standard=await service.latest(None,product="DDREC",edition="standard",environment="production",architecture="x64",channel="stable",version="1.3.0",build_number=1)
    local=await service.latest(None,product="DDREC",edition="license",environment="local",architecture="x64",channel="dev",version="1.3.0",build_number=1)
    production=await service.latest(None,product="DDREC",edition="license",environment="production",architecture="x64",channel="stable",version="1.3.0",build_number=1)
    assert standard["edition"]=="standard" and local["environment"]=="local" and production=={"updateAvailable":False}


@pytest.mark.parametrize("changes", [
    {"edition":"standard","fileName":"DDREC-1.3.1-license-Setup.exe"},
    {"environment":"local","channel":"stable"},
    {"mandatory":True},
])
def test_invalid_release_lanes_are_rejected(changes):
    data=dict(product="DDREC",version="1.3.1",buildNumber=72,gitCommit="abcdef123456",edition="license",environment="production",architecture="x64",channel="stable",title="DD Rec V1.3.1",releaseNotes="notes",fileName="DDREC-1.3.1-license-Setup.exe",downloadPath="/releases/stable/license/1.3.1/DDREC-1.3.1-license-Setup.exe",fileSize=12,sha256="A"*64,signature="x"*86,mandatory=False,publishedAt="2026-08-15T10:00:00Z")
    data.update(changes)
    with pytest.raises(ValueError): ClientReleaseDraftRequest.model_validate(data)


def test_publish_requires_real_file_sha_and_valid_signature(settings, tmp_path):
    private=Ed25519PrivateKey.generate(); public=tmp_path/"public.pem"
    public.write_bytes(private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
    content=b"installer"; target=tmp_path/"releases/stable/license/1.3.1/DDREC-1.3.1-license-Setup.exe"; target.parent.mkdir(parents=True); target.write_bytes(content)
    import hashlib
    row=release(file_size=len(content),sha256=hashlib.sha256(content).hexdigest().upper())
    values={"product":row.product,"version":row.version,"buildNumber":row.build_number,"edition":row.edition,"environment":row.environment,"architecture":row.architecture,"channel":row.channel,"fileName":row.file_name,"fileSize":row.file_size,"sha256":row.sha256,"publishedAt":"2026-08-15T10:00:00Z"}
    row.signature=base64.urlsafe_b64encode(private.sign(canonical_update_bytes(values))).decode().rstrip("=")
    configured=settings.model_copy(update={"update_download_root":tmp_path,"update_signing_public_key_path":public})
    ClientReleaseService(configured)._verify_publishable(row)
    row.sha256="0"*64
    with pytest.raises(LicenseServiceError,match="SHA-256"): ClientReleaseService(configured)._verify_publishable(row)


def test_bad_signature_cannot_publish(settings, tmp_path):
    private=Ed25519PrivateKey.generate(); public=tmp_path/"public.pem"
    public.write_bytes(private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
    content=b"installer"; target=tmp_path/"releases/stable/license/1.3.1/DDREC-1.3.1-license-Setup.exe"; target.parent.mkdir(parents=True); target.write_bytes(content)
    import hashlib
    row=release(file_size=len(content),sha256=hashlib.sha256(content).hexdigest().upper(),signature="A"*86)
    configured=settings.model_copy(update={"update_download_root":tmp_path,"update_signing_public_key_path":public})
    with pytest.raises(LicenseServiceError,match="签名"): ClientReleaseService(configured)._verify_publishable(row)


class EmptyScalarResult:
    def all(self): return []


class EmptySession:
    async def scalars(self, _statement): return EmptyScalarResult()


@pytest.mark.asyncio
async def test_public_update_api_requires_no_license_or_activation(settings):
    result = await latest_client_update(
        product="DDREC", edition="standard", environment="production", arch="x64",
        channel="stable", version="1.3.0", build_number=64,
        session=EmptySession(), settings=settings,
    )
    assert result == {"updateAvailable": False}


def test_release_identity_has_database_unique_constraint():
    constraints = [item for item in ClientRelease.__table__.constraints if isinstance(item, UniqueConstraint)]
    assert any(tuple(column.name for column in item.columns) == (
        "product", "version", "build_number", "edition", "environment", "architecture", "channel"
    ) for item in constraints)
