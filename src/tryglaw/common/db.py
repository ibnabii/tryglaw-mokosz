from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import aiosqlite


@asynccontextmanager
async def get_connection(db_path: str) -> AsyncGenerator[aiosqlite.Connection, None]:
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    try:
        yield conn
    finally:
        await conn.close()


async def execute_script(db_path: str, sql: str) -> None:
    async with get_connection(db_path) as conn:
        await conn.executescript(sql)
        await conn.commit()
