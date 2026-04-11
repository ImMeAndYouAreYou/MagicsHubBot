from __future__ import annotations

from sales_bot.db import Database
from sales_bot.models import VouchStats


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
