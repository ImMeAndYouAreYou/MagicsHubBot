from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Iterable, Sequence

import aiosqlite
import asyncpg


type PgOperationResult = Any


class Database:
    def __init__(self, path: Path, schema_path: Path, database_url: str | None = None) -> None:
        self.path = path
        self.schema_path = schema_path
        self.database_url = database_url
        self._connection: aiosqlite.Connection | None = None
        self._pg_connection: asyncpg.Connection | None = None
        self._pg_lock = asyncio.Lock()

    @property
    def connection(self) -> aiosqlite.Connection | asyncpg.Connection:
        if self.database_url:
            if self._pg_connection is None:
                raise RuntimeError("Database connection has not been initialized")
            return self._pg_connection

        if self._connection is None:
            raise RuntimeError("Database connection has not been initialized")
        return self._connection

    async def connect(self) -> None:
        if self.database_url:
            self._pg_connection = await asyncpg.connect(
                self.database_url,
                statement_cache_size=0,
            )
            schema_path = self.schema_path.with_name("schema_postgres.sql")
            schema = schema_path.read_text(encoding="utf-8")
            await self._pg_connection.execute(schema)
            await self._run_migrations()
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self.path)
        self._connection.row_factory = aiosqlite.Row
        schema = self.schema_path.read_text(encoding="utf-8")
        await self._connection.executescript(schema)
        await self._run_migrations()
        await self._connection.commit()

    async def _run_migrations(self) -> None:
        await self._ensure_column("systems", "roblox_gamepass_id", "TEXT")
        await self._ensure_column("order_requests", "roblox_username", "TEXT")
        await self._ensure_column("order_requests", "admin_reply", "TEXT")

    async def _ensure_column(self, table_name: str, column_name: str, column_sql: str) -> None:
        if self.database_url:
            row = await self.fetchone(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = ?
                  AND column_name = ?
                """,
                (table_name, column_name),
            )
            if row is not None:
                return
            await self.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")
            return

        rows = await self.fetchall(f"PRAGMA table_info({table_name})")
        if any(str(row["name"]) == column_name for row in rows):
            return
        sqlite_connection = self.connection
        if not isinstance(sqlite_connection, aiosqlite.Connection):
            return
        await sqlite_connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")

    async def close(self) -> None:
        if self._pg_connection is not None:
            await self._pg_connection.close()
            self._pg_connection = None
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def execute(self, query: str, parameters: Sequence[Any] = ()) -> None:
        if self.database_url:
            await self._run_pg(lambda pg_connection: pg_connection.execute(self._translate_query(query), *parameters))
            return

        sqlite_connection = self.connection
        assert isinstance(sqlite_connection, aiosqlite.Connection)
        await sqlite_connection.execute(query, parameters)
        await sqlite_connection.commit()

    async def executemany(self, query: str, parameters: Iterable[Sequence[Any]]) -> None:
        if self.database_url:
            parameter_list = list(parameters)
            await self._run_pg(lambda pg_connection: pg_connection.executemany(self._translate_query(query), parameter_list))
            return

        sqlite_connection = self.connection
        assert isinstance(sqlite_connection, aiosqlite.Connection)
        await sqlite_connection.executemany(query, parameters)
        await sqlite_connection.commit()

    async def fetchone(self, query: str, parameters: Sequence[Any] = ()) -> aiosqlite.Row | None:
        if self.database_url:
            return await self._run_pg(lambda pg_connection: pg_connection.fetchrow(self._translate_query(query), *parameters))

        sqlite_connection = self.connection
        assert isinstance(sqlite_connection, aiosqlite.Connection)
        async with sqlite_connection.execute(query, parameters) as cursor:
            return await cursor.fetchone()

    async def fetchall(self, query: str, parameters: Sequence[Any] = ()) -> list[aiosqlite.Row]:
        if self.database_url:
            rows = await self._run_pg(lambda pg_connection: pg_connection.fetch(self._translate_query(query), *parameters))
            return list(rows)

        sqlite_connection = self.connection
        assert isinstance(sqlite_connection, aiosqlite.Connection)
        async with sqlite_connection.execute(query, parameters) as cursor:
            return await cursor.fetchall()

    async def insert(self, query: str, parameters: Sequence[Any] = ()) -> int:
        if self.database_url:
            translated = self._translate_query(query)
            if "RETURNING" not in translated.upper():
                translated = translated.rstrip().rstrip(";") + " RETURNING id"
            value = await self._run_pg(lambda pg_connection: pg_connection.fetchval(translated, *parameters))
            return int(value)

        sqlite_connection = self.connection
        assert isinstance(sqlite_connection, aiosqlite.Connection)
        cursor = await sqlite_connection.execute(query, parameters)
        await sqlite_connection.commit()
        return int(cursor.lastrowid)

    @staticmethod
    def _translate_query(query: str) -> str:
        translated = query.replace(" COLLATE NOCASE", "")
        parts = translated.split("?")
        if len(parts) == 1:
            return translated

        rebuilt: list[str] = [parts[0]]
        for index, part in enumerate(parts[1:], start=1):
            rebuilt.append(f"${index}")
            rebuilt.append(part)
        return "".join(rebuilt)

    async def _run_pg(self, operation: Callable[[asyncpg.Connection], Awaitable[PgOperationResult]]) -> PgOperationResult:
        pg_connection = self.connection
        assert isinstance(pg_connection, asyncpg.Connection)
        async with self._pg_lock:
            return await operation(pg_connection)
