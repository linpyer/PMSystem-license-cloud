from __future__ import annotations

import argparse
import asyncio
import getpass
from datetime import datetime, timezone

from app.core.admin_security import hash_admin_password
from app.core.config import get_settings
from app.db.session import create_database_runtime
from app.repositories.admin_repository import AdminRepository


async def reset(username: str, password: str) -> None:
    settings = get_settings()
    runtime = create_database_runtime(settings)
    try:
        async with runtime.session_factory() as session:
            repository = AdminRepository()
            user = await repository.get_user_by_username(session, username)
            if user is None:
                raise ValueError("Administrator was not found")
            now = datetime.now(timezone.utc)
            user.password_hash = hash_admin_password(password)
            user.password_changed_at = now
            user.failed_login_count = 0
            user.locked_until = None
            await repository.revoke_user_sessions(session, user.id, now)
            await repository.add_audit(
                session, action="RESET_ADMIN_PASSWORD_CLI", request_id="local-cli",
                trace_id="local-cli", result="SUCCESS", now=now,
                admin_user_id=user.id, target_type="admin_user", target_id=str(user.id),
            )
            await session.commit()
    finally:
        await runtime.engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset a DDREC administrator password")
    parser.add_argument("--username", required=True)
    args = parser.parse_args()
    first = getpass.getpass("New password: ")
    second = getpass.getpass("Confirm new password: ")
    if first != second:
        raise ValueError("Passwords do not match")
    asyncio.run(reset(args.username, first))
    print("Password reset. Existing administrator sessions were revoked.")


if __name__ == "__main__":
    main()
