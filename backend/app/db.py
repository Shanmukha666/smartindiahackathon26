from collections.abc import AsyncGenerator

import asyncpg

from .config import get_settings


async def check_database_connection() -> bool:
    settings = get_settings()
    try:
        connection = await asyncpg.connect(settings.database_url.get_secret_value(), timeout=2)
        await connection.fetchval("SELECT 1")
        await connection.close()
        return True
    except (OSError, asyncpg.PostgresError, TimeoutError):
        return False


async def get_connection() -> AsyncGenerator[asyncpg.Connection, None]:
    connection = await asyncpg.connect(get_settings().database_url.get_secret_value())
    try:
        yield connection
    finally:
        await connection.close()
