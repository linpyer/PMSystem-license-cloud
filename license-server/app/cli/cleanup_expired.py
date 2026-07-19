from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timezone

from app.core.config import get_settings
from app.db.session import create_database_runtime
from app.services.maintenance_service import cleanup_expired_records


async def _run() -> None:
    runtime = create_database_runtime(get_settings())
    try:
        async with runtime.session_factory() as session:
            result = await cleanup_expired_records(session, datetime.now(timezone.utc))
        print(json.dumps(asdict(result), separators=(",", ":")))
    finally:
        await runtime.engine.dispose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
