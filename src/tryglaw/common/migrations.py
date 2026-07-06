from __future__ import annotations

import importlib.resources
from datetime import datetime, timezone
from typing import Callable, Awaitable

from tryglaw.common.db import get_connection

LEDGER_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);
"""


async def run_migrations(
    db_path: str,
    package: str,
    *,
    baseline_predicate: Callable[[str], Awaitable[bool]] | None = None,
) -> list[str]:
    async with get_connection(db_path) as conn:
        await conn.executescript(LEDGER_SQL)
        await conn.commit()

        rows = await conn.execute_fetchall(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
        applied = {r[0] for r in rows}

    all_versions = _discover_migrations(package)
    pending = [(v, sql) for v, sql in all_versions if v not in applied]

    if not pending:
        return []

    if not applied and baseline_predicate and await baseline_predicate(db_path):
        now = datetime.now(timezone.utc).isoformat()
        async with get_connection(db_path) as conn:
            for version, _ in pending:
                await conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (version, now),
                )
            await conn.commit()
        return []

    newly_applied: list[str] = []
    async with get_connection(db_path) as conn:
        now = datetime.now(timezone.utc).isoformat()
        for version, sql in pending:
            await conn.executescript(sql)
            await conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, now),
            )
            await conn.commit()
            newly_applied.append(version)

    return newly_applied


async def migration_status(db_path: str, package: str) -> dict:
    async with get_connection(db_path) as conn:
        await conn.executescript(LEDGER_SQL)
        await conn.commit()
        rows = await conn.execute_fetchall(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
        applied = {r[0] for r in rows}

    all_versions = _discover_migrations(package)
    all_names = [v for v, _ in all_versions]
    pending = [v for v in all_names if v not in applied]
    return {"applied": sorted(applied), "pending": pending}


def _discover_migrations(package: str) -> list[tuple[str, str]]:
    try:
        pkg = importlib.resources.files(package).joinpath("migrations")
    except (ModuleNotFoundError, FileNotFoundError):
        return []

    entries: list[tuple[str, str]] = []
    for item in sorted(pkg.iterdir()):
        name = item.name if hasattr(item, "name") else str(item).split("/")[-1]
        if name.endswith(".sql"):
            version = name[:-4]
            sql = item.read_text(encoding="utf-8")
            entries.append((version, sql))
    return entries
