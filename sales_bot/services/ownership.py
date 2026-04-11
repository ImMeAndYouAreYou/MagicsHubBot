from __future__ import annotations

import aiosqlite

from sales_bot.db import Database
from sales_bot.exceptions import NotFoundError
from sales_bot.models import DeliveryRecord, SystemRecord


class OwnershipService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def grant_system(self, user_id: int, system_id: int, granted_by: int | None, source: str) -> None:
        await self.database.execute(
            """
            INSERT INTO user_systems (user_id, system_id, granted_by, source)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, system_id)
            DO UPDATE SET granted_by = excluded.granted_by, source = excluded.source, granted_at = CURRENT_TIMESTAMP
            """,
            (user_id, system_id, granted_by, source),
        )

    async def revoke_system(self, user_id: int, system_id: int) -> None:
        row = await self.database.fetchone(
            "SELECT 1 FROM user_systems WHERE user_id = ? AND system_id = ?",
            (user_id, system_id),
        )
        if row is None:
            raise NotFoundError("That user does not own the selected system.")

        await self.database.execute(
            "DELETE FROM user_systems WHERE user_id = ? AND system_id = ?",
            (user_id, system_id),
        )

    async def list_user_systems(self, user_id: int) -> list[SystemRecord]:
        rows = await self.database.fetchall(
            """
            SELECT s.*
            FROM user_systems us
            JOIN systems s ON s.id = us.system_id
            WHERE us.user_id = ?
            ORDER BY s.name COLLATE NOCASE ASC
            """,
            (user_id,),
        )
        return [self._map_system(row) for row in rows]

    async def user_owns_system(self, user_id: int, system_id: int) -> bool:
        row = await self.database.fetchone(
            "SELECT 1 FROM user_systems WHERE user_id = ? AND system_id = ?",
            (user_id, system_id),
        )
        return row is not None

    async def add_delivery_message(
        self,
        *,
        user_id: int,
        system_id: int,
        channel_id: int,
        message_id: int,
        source: str,
    ) -> None:
        await self.database.execute(
            """
            INSERT INTO delivery_messages (user_id, system_id, channel_id, message_id, source)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, system_id, channel_id, message_id, source),
        )

    async def list_delivery_messages(
        self,
        user_id: int,
        system_id: int | None = None,
    ) -> list[DeliveryRecord]:
        if system_id is None:
            rows = await self.database.fetchall(
                "SELECT * FROM delivery_messages WHERE user_id = ? ORDER BY sent_at DESC",
                (user_id,),
            )
        else:
            rows = await self.database.fetchall(
                "SELECT * FROM delivery_messages WHERE user_id = ? AND system_id = ? ORDER BY sent_at DESC",
                (user_id, system_id),
            )
        return [self._map_delivery(row) for row in rows]

    async def delete_delivery_record(self, record_id: int) -> None:
        await self.database.execute("DELETE FROM delivery_messages WHERE id = ?", (record_id,))

    @staticmethod
    def _map_delivery(row: aiosqlite.Row) -> DeliveryRecord:
        return DeliveryRecord(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            system_id=int(row["system_id"]),
            channel_id=int(row["channel_id"]),
            message_id=int(row["message_id"]),
            source=str(row["source"]),
            sent_at=str(row["sent_at"]),
        )

    @staticmethod
    def _map_system(row: aiosqlite.Row) -> SystemRecord:
        return SystemRecord(
            id=int(row["id"]),
            name=str(row["name"]),
            description=str(row["description"]),
            file_path=str(row["file_path"]),
            image_path=str(row["image_path"]) if row["image_path"] else None,
            paypal_link=str(row["paypal_link"]) if row["paypal_link"] else None,
            roblox_gamepass_id=str(row["roblox_gamepass_id"]) if row["roblox_gamepass_id"] else None,
            created_by=int(row["created_by"]) if row["created_by"] is not None else None,
            created_at=str(row["created_at"]),
        )
