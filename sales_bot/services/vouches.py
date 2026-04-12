from __future__ import annotations

import aiosqlite

from sales_bot.db import Database
from sales_bot.exceptions import NotFoundError
from sales_bot.models import VouchRecord, VouchStats


class VouchService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_vouch(
        self,
        *,
        admin_user_id: int,
        author_user_id: int,
        reason: str,
        rating: int,
        posted_message_id: int,
    ) -> int:
        return await self.database.insert(
            """
            INSERT INTO vouches (admin_user_id, author_user_id, reason, rating, posted_message_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (admin_user_id, author_user_id, reason.strip(), rating, posted_message_id),
        )

    async def get_stats(self, admin_user_id: int) -> VouchStats:
        row = await self.database.fetchone(
            "SELECT COUNT(*) AS total, AVG(rating) AS average_rating FROM vouches WHERE admin_user_id = ?",
            (admin_user_id,),
        )
        total = int(row["total"]) if row is not None else 0
        average = float(row["average_rating"] or 0.0) if row is not None else 0.0
        return VouchStats(total=total, average_rating=average)

    async def list_vouches(self, admin_user_id: int) -> list[VouchRecord]:
        rows = await self.database.fetchall(
            "SELECT * FROM vouches WHERE admin_user_id = ? ORDER BY created_at DESC, id DESC",
            (admin_user_id,),
        )
        return [self._map_vouch(row) for row in rows]

    async def delete_vouch(self, vouch_id: int) -> VouchRecord:
        row = await self.database.fetchone("SELECT * FROM vouches WHERE id = ?", (vouch_id,))
        if row is None:
            raise NotFoundError("ההוכחה שבחרת כבר לא קיימת.")

        await self.database.execute("DELETE FROM vouches WHERE id = ?", (vouch_id,))
        return self._map_vouch(row)

    @staticmethod
    def _map_vouch(row: aiosqlite.Row) -> VouchRecord:
        return VouchRecord(
            id=int(row["id"]),
            admin_user_id=int(row["admin_user_id"]),
            author_user_id=int(row["author_user_id"]),
            reason=str(row["reason"]),
            rating=int(row["rating"]),
            posted_message_id=int(row["posted_message_id"]) if row["posted_message_id"] is not None else None,
            created_at=str(row["created_at"]),
        )
