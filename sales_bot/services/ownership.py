from __future__ import annotations

import aiosqlite

from sales_bot.db import Database
from sales_bot.exceptions import NotFoundError, PermissionDeniedError
from sales_bot.models import DeliveryRecord, OwnedSystemRecord, SavedSystemRecord, SystemRecord


class OwnershipService:
    TRANSFER_SOURCE = "transfer"
    ROBLOX_CLAIM_SOURCE = "roblox-gamepass-claim"

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
            ORDER BY LOWER(s.name) ASC
            """,
            (user_id,),
        )
        return [self._map_system(row) for row in rows]

    async def list_user_ownerships(self, user_id: int) -> list[OwnedSystemRecord]:
        rows = await self.database.fetchall(
            """
            SELECT us.user_id, us.system_id, us.granted_by, us.source, us.granted_at, s.*
            FROM user_systems us
            JOIN systems s ON s.id = us.system_id
            WHERE us.user_id = ?
            ORDER BY LOWER(s.name) ASC
            """,
            (user_id,),
        )
        return [self._map_owned_system(row) for row in rows]

    async def list_transferable_ownerships(self, user_id: int) -> list[OwnedSystemRecord]:
        rows = await self.database.fetchall(
            """
            SELECT us.user_id, us.system_id, us.granted_by, us.source, us.granted_at, s.*
            FROM user_systems us
            JOIN systems s ON s.id = us.system_id
            WHERE us.user_id = ?
              AND us.source != ?
              AND (us.granted_by IS NOT NULL OR us.source = ?)
            ORDER BY LOWER(s.name) ASC
            """,
            (user_id, self.TRANSFER_SOURCE, self.ROBLOX_CLAIM_SOURCE),
        )
        return [self._map_owned_system(row) for row in rows]

    async def user_owns_system(self, user_id: int, system_id: int) -> bool:
        row = await self.database.fetchone(
            "SELECT 1 FROM user_systems WHERE user_id = ? AND system_id = ?",
            (user_id, system_id),
        )
        return row is not None

    async def save_transferable_systems(self, user_id: int, saved_by: int | None) -> list[SavedSystemRecord]:
        ownerships = await self.list_transferable_ownerships(user_id)
        await self.database.execute("DELETE FROM temp_saved_systems WHERE user_id = ?", (user_id,))

        if ownerships:
            await self.database.executemany(
                """
                INSERT INTO temp_saved_systems (user_id, system_id, source, saved_by)
                VALUES (?, ?, ?, ?)
                """,
                [(user_id, ownership.system.id, ownership.source, saved_by) for ownership in ownerships],
            )

        return await self.list_saved_systems(user_id)

    async def list_saved_systems(self, user_id: int) -> list[SavedSystemRecord]:
        rows = await self.database.fetchall(
            """
            SELECT t.user_id, t.system_id, t.source, t.saved_by, t.saved_at, s.*
            FROM temp_saved_systems t
            JOIN systems s ON s.id = t.system_id
            WHERE t.user_id = ?
            ORDER BY LOWER(s.name) ASC
            """,
            (user_id,),
        )
        return [self._map_saved_system(row) for row in rows]

    async def clear_saved_systems(self, user_id: int) -> None:
        await self.database.execute("DELETE FROM temp_saved_systems WHERE user_id = ?", (user_id,))

    async def add_transfer_lock(self, user_id: int, system_id: int, locked_by: int | None) -> None:
        await self.database.execute(
            """
            INSERT INTO transfer_locks (user_id, system_id, locked_by, reason)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, system_id)
            DO UPDATE SET locked_by = excluded.locked_by, reason = excluded.reason, locked_at = CURRENT_TIMESTAMP
            """,
            (user_id, system_id, locked_by, self.TRANSFER_SOURCE),
        )

    async def is_transfer_locked(self, user_id: int, system_id: int) -> bool:
        row = await self.database.fetchone(
            "SELECT 1 FROM transfer_locks WHERE user_id = ? AND system_id = ?",
            (user_id, system_id),
        )
        return row is not None

    async def list_transfer_locked_system_ids(self, user_id: int) -> set[int]:
        rows = await self.database.fetchall(
            "SELECT system_id FROM transfer_locks WHERE user_id = ?",
            (user_id,),
        )
        return {int(row["system_id"]) for row in rows}

    async def transfer_all_systems(
        self,
        *,
        from_user_id: int,
        to_user_id: int,
        transferred_by: int,
    ) -> list[SystemRecord]:
        if from_user_id == to_user_id:
            raise PermissionDeniedError("אי אפשר להעביר מערכות לאותו המשתמש.")

        saved_systems = await self.save_transferable_systems(from_user_id, transferred_by)
        if not saved_systems:
            raise NotFoundError("למשתמש הזה אין מערכות שניתן לשמור ולהעביר כרגע.")

        transferred_systems: list[SystemRecord] = []
        for saved_system in saved_systems:
            if not await self.user_owns_system(from_user_id, saved_system.system.id):
                continue

            if not await self.user_owns_system(to_user_id, saved_system.system.id):
                await self.grant_system(to_user_id, saved_system.system.id, transferred_by, self.TRANSFER_SOURCE)

            await self.database.execute(
                "DELETE FROM user_systems WHERE user_id = ? AND system_id = ?",
                (from_user_id, saved_system.system.id),
            )
            await self.add_transfer_lock(from_user_id, saved_system.system.id, transferred_by)
            transferred_systems.append(saved_system.system)

        await self.clear_saved_systems(from_user_id)

        if not transferred_systems:
            raise NotFoundError("לא נמצאו מערכות פעילות להעברה עבור המשתמש הזה.")

        return transferred_systems

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

    async def list_claim_role_owned_systems(self, user_id: int) -> list[SystemRecord]:
        rows = await self.database.fetchall(
            """
            SELECT s.*
            FROM user_systems us
            JOIN systems s ON s.id = us.system_id
            WHERE us.user_id = ?
              AND us.source != ?
              AND (us.granted_by IS NOT NULL OR us.source = ?)
            ORDER BY LOWER(s.name) ASC
            """,
            (user_id, self.TRANSFER_SOURCE, self.ROBLOX_CLAIM_SOURCE),
        )
        return [self._map_system(row) for row in rows]

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
    def _map_owned_system(row: aiosqlite.Row) -> OwnedSystemRecord:
        return OwnedSystemRecord(
            system=OwnershipService._map_system(row),
            source=str(row["source"]),
            granted_by=int(row["granted_by"]) if row["granted_by"] is not None else None,
            granted_at=str(row["granted_at"]),
        )

    @staticmethod
    def _map_saved_system(row: aiosqlite.Row) -> SavedSystemRecord:
        return SavedSystemRecord(
            system=OwnershipService._map_system(row),
            source=str(row["source"]),
            saved_by=int(row["saved_by"]) if row["saved_by"] is not None else None,
            saved_at=str(row["saved_at"]),
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
