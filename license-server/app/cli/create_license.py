from __future__ import annotations

import argparse
import asyncio
from datetime import datetime

from app.core.config import get_settings
from app.db.models.enums import LicenseType
from app.db.session import create_database_runtime
from app.services.license_code_service import LicenseCodeService


def parse_utc_datetime(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include Z or a UTC offset")
    return parsed


async def create_from_args(args: argparse.Namespace) -> None:
    settings = get_settings()
    runtime = create_database_runtime(settings)
    try:
        async with runtime.session_factory() as session:
            created = await LicenseCodeService(settings).create(
                session,
                license_type=LicenseType(args.type),
                expires_at=args.expires_at,
                customer_name=args.customer_name,
                customer_contact=args.customer_contact,
                remark=args.remark,
            )
            await session.commit()
            print("License created. The complete code is displayed once and is not stored in plaintext.")
            print(created.plaintext_code)
            print(f"License ID: {created.record.id}")
            print(f"Stored mask: {created.record.license_code_masked}")
    finally:
        await runtime.engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create one DDREC license code")
    parser.add_argument(
        "--type", required=True,
        choices=[item.value for item in LicenseType if item != LicenseType.TRIAL]
    )
    parser.add_argument("--expires-at", type=parse_utc_datetime)
    parser.add_argument("--customer-name")
    parser.add_argument("--customer-contact")
    parser.add_argument("--remark")
    args = parser.parse_args()
    if args.type == LicenseType.FIXED_DATE.value and args.expires_at is None:
        parser.error("--expires-at is required for fixed_date")
    if args.type != LicenseType.FIXED_DATE.value and args.expires_at is not None:
        parser.error("--expires-at is only allowed for fixed_date")
    asyncio.run(create_from_args(args))


if __name__ == "__main__":
    main()
