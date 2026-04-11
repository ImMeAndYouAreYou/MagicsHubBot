from __future__ import annotations

import aiosqlite

from sales_bot.db import Database
from sales_bot.exceptions import AlreadyExistsError, NotFoundError, PermissionDeniedError
from sales_bot.models import AppealRecord, BlacklistEntry


class BlacklistService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def is_blacklisted(self, user_id: int) -> bool:
        row = await self.database.fetchone(
            "SELECT user_id FROM blacklist_entries WHERE user_id = ?",
            (user_id,),
        )
        return row is not None

    async def add_entry(self, user_id: int, display_label: str, actor_id: int) -> BlacklistEntry:
        if await self.is_blacklisted(user_id):
            raise AlreadyExistsError("That user is already blacklisted.")

        await self.database.execute(
            "INSERT INTO blacklist_entries (user_id, display_label, blacklisted_by) VALUES (?, ?, ?)",
            (user_id, display_label, actor_id),
        )
        return await self.get_entry(user_id)

    async def get_entry(self, user_id: int) -> BlacklistEntry:
        row = await self.database.fetchone(
            "SELECT * FROM blacklist_entries WHERE user_id = ?",
            (user_id,),
        )
        if row is None:
            raise NotFoundError("Blacklist entry not found.")
        return self._map_blacklist(row)

    async def list_entries(self) -> list[BlacklistEntry]:
        rows = await self.database.fetchall(
            "SELECT * FROM blacklist_entries ORDER BY blacklisted_at DESC"
        )
        return [self._map_blacklist(row) for row in rows]

    async def remove_entry(self, user_id: int) -> None:
        if not await self.is_blacklisted(user_id):
            raise NotFoundError("Blacklist entry not found.")
        await self.database.execute("DELETE FROM blacklist_entries WHERE user_id = ?", (user_id,))

    async def create_appeal(self, user_id: int, answer_one: str, answer_two: str) -> AppealRecord:
        existing = await self.database.fetchone(
            "SELECT id FROM blacklist_appeals WHERE user_id = ? AND status = 'pending'",
            (user_id,),
        )
        if existing is not None:
            raise AlreadyExistsError("You already have a pending blacklist appeal.")

        appeal_id = await self.database.insert(
            "INSERT INTO blacklist_appeals (user_id, answer_one, answer_two) VALUES (?, ?, ?)",
            (user_id, answer_one.strip(), answer_two.strip()),
        )
        return await self.get_appeal(appeal_id)

    async def get_appeal(self, appeal_id: int) -> AppealRecord:
        row = await self.database.fetchone(
            "SELECT * FROM blacklist_appeals WHERE id = ?",
            (appeal_id,),
        )
        if row is None:
            raise NotFoundError("Blacklist appeal not found.")
        return self._map_appeal(row)

    async def list_pending_appeals(self) -> list[AppealRecord]:
        rows = await self.database.fetchall(
            "SELECT * FROM blacklist_appeals WHERE status = 'pending' ORDER BY submitted_at ASC"
        )
        return [self._map_appeal(row) for row in rows]

    async def set_owner_message(self, appeal_id: int, message_id: int) -> None:
        await self.database.execute(
            "UPDATE blacklist_appeals SET owner_message_id = ? WHERE id = ?",
            (message_id, appeal_id),
        )

    async def resolve_appeal(self, appeal_id: int, reviewer_id: int, status: str) -> AppealRecord:
        if status not in {"accepted", "rejected"}:
            raise PermissionDeniedError("Invalid appeal resolution status.")

        appeal = await self.get_appeal(appeal_id)
        if appeal.status != "pending":
            raise PermissionDeniedError("That appeal has already been reviewed.")

        await self.database.execute(
            """
            UPDATE blacklist_appeals
            SET status = ?, reviewed_at = CURRENT_TIMESTAMP, reviewed_by = ?
            WHERE id = ?
            """,
            (status, reviewer_id, appeal_id),
        )
        return await self.get_appeal(appeal_id)

    @staticmethod
    def build_display_label(user_id: int) -> str:
        return f"<@{user_id}> - {user_id}"

    @staticmethod
    def _map_blacklist(row: aiosqlite.Row) -> BlacklistEntry:
        return BlacklistEntry(
            user_id=int(row["user_id"]),
            display_label=str(row["display_label"]),
            blacklisted_by=int(row["blacklisted_by"]) if row["blacklisted_by"] is not None else None,
            blacklisted_at=str(row["blacklisted_at"]),
        )

    @staticmethod
    def _map_appeal(row: aiosqlite.Row) -> AppealRecord:
        return AppealRecord(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            answer_one=str(row["answer_one"]),
            answer_two=str(row["answer_two"]),
            owner_message_id=int(row["owner_message_id"]) if row["owner_message_id"] is not None else None,
            status=str(row["status"]),
            submitted_at=str(row["submitted_at"]),
            reviewed_at=str(row["reviewed_at"]) if row["reviewed_at"] else None,
            reviewed_by=int(row["reviewed_by"]) if row["reviewed_by"] is not None else None,
        )
