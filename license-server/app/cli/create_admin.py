from __future__ import annotations

import argparse
import asyncio
import getpass
from datetime import datetime, timezone

import pyotp

from app.core.admin_security import encrypt_totp_secret, generate_totp_secret, hash_admin_password
from app.core.config import get_settings
from app.db.models import AdminUser
from app.db.models.enums import AdminRole, AdminStatus
from app.db.session import create_database_runtime
from app.repositories.admin_repository import AdminRepository


async def create_admin(args: argparse.Namespace, password: str) -> tuple[AdminUser, str]:
    settings = get_settings()
    runtime = create_database_runtime(settings)
    secret = generate_totp_secret()
    try:
        async with runtime.session_factory() as session:
            repository = AdminRepository()
            if await repository.get_user_by_username(session, args.username):
                raise ValueError("Administrator username already exists")
            now = datetime.now(timezone.utc)
            user = AdminUser(
                username=args.username.strip().lower(),
                password_hash=hash_admin_password(password),
                display_name=args.display_name.strip(),
                role=AdminRole(args.role),
                status=AdminStatus.ACTIVE,
                totp_secret_encrypted=encrypt_totp_secret(
                    secret, settings.admin_totp_encryption_key.get_secret_value()
                ),
                totp_enabled=True,
                failed_login_count=0,
                password_changed_at=now,
            )
            await repository.add_user(session, user)
            await repository.add_audit(
                session, action="CREATE_INITIAL_ADMIN", request_id="local-cli",
                trace_id="local-cli", result="SUCCESS", now=now,
                admin_user_id=user.id, target_type="admin_user", target_id=str(user.id),
                detail={"role": user.role.value},
            )
            await session.commit()
            return user, secret
    finally:
        await runtime.engine.dispose()


def _read_password() -> str:
    first = getpass.getpass("Password: ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise ValueError("Passwords do not match")
    return first


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a PMSystem license administrator")
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--role", choices=[item.value for item in AdminRole], default="OWNER")
    args = parser.parse_args()
    user, secret = asyncio.run(create_admin(args, _read_password()))
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.username, issuer_name="PMSystem License Admin")
    print("Administrator created. TOTP enrollment information is displayed once.")
    print(f"TOTP secret: {secret}")
    print(f"Provisioning URI: {uri}")


if __name__ == "__main__":
    main()
