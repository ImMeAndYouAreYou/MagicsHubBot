from __future__ import annotations

import aiosqlite

from sales_bot.db import Database
from sales_bot.exceptions import AlreadyExistsError, NotFoundError, PermissionDeniedError
from sales_bot.models import SystemDiscountRecord, SystemRecord


class DiscountService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def set_discount(
        self,
        *,
        user_id: int,
        system: SystemRecord,
        discount_percent: int,
        actor_id: int,
    ) -> SystemDiscountRecord:
        normalized_discount = self._normalize_discount(discount_percent)
        existing = await self.get_discount_optional(user_id, system.id)
        if existing is None:
            await self.database.execute(
                """
                INSERT INTO system_discounts (user_id, system_id, discount_percent, created_by, updated_by)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, system.id, normalized_discount, actor_id, actor_id),
            )
        else:
            await self.database.execute(
                """
                UPDATE system_discounts
                SET discount_percent = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND system_id = ?
                """,
                (normalized_discount, actor_id, user_id, system.id),
            )
        return await self.get_discount(user_id, system.id)

    async def add_discount(
        self,
        *,
        user_id: int,
        system: SystemRecord,
        discount_percent: int,
        actor_id: int,
    ) -> SystemDiscountRecord:
        if await self.get_discount_optional(user_id, system.id) is not None:
            raise AlreadyExistsError("למשתמש הזה כבר קיימת הנחה על המערכת הזאת.")
        return await self.set_discount(
            user_id=user_id,
            system=system,
            discount_percent=discount_percent,
            actor_id=actor_id,
        )

    async def remove_discount(self, *, user_id: int, system_id: int) -> None:
        if await self.get_discount_optional(user_id, system_id) is None:
            raise NotFoundError("לא נמצאה הנחה למשתמש הזה על המערכת הזאת.")
        await self.database.execute(
            "DELETE FROM system_discounts WHERE user_id = ? AND system_id = ?",
            (user_id, system_id),
        )

    async def get_discount(self, user_id: int, system_id: int) -> SystemDiscountRecord:
        row = await self._fetch_discount_row(user_id, system_id)
        if row is None:
            raise NotFoundError("לא נמצאה הנחה למשתמש הזה על המערכת הזאת.")
        return self._map_discount(row)

    async def get_discount_optional(self, user_id: int, system_id: int) -> SystemDiscountRecord | None:
        row = await self._fetch_discount_row(user_id, system_id)
        if row is None:
            return None
        return self._map_discount(row)

    async def list_user_discounts(self, user_id: int) -> list[SystemDiscountRecord]:
        rows = await self.database.fetchall(
            """
            SELECT
                sd.user_id,
                sd.discount_percent,
                sd.created_by AS discount_created_by,
                sd.updated_by AS discount_updated_by,
                sd.created_at AS discount_created_at,
                sd.updated_at AS discount_updated_at,
                s.id AS system_id,
                s.name AS system_name,
                s.description AS system_description,
                s.file_path AS system_file_path,
                s.image_path AS system_image_path,
                s.paypal_link AS system_paypal_link,
                s.roblox_gamepass_id AS system_roblox_gamepass_id,
                s.created_by AS system_created_by,
                s.created_at AS system_created_at
            FROM system_discounts sd
            JOIN systems s ON s.id = sd.system_id
            WHERE sd.user_id = ?
            ORDER BY LOWER(s.name) ASC
            """,
            (user_id,),
        )
        return [self._map_discount(row) for row in rows]

    async def search_user_discounted_systems(self, *, user_id: int, current: str) -> list[SystemDiscountRecord]:
        like_value = f"%{current.strip()}%"
        rows = await self.database.fetchall(
            """
            SELECT
                sd.user_id,
                sd.discount_percent,
                sd.created_by AS discount_created_by,
                sd.updated_by AS discount_updated_by,
                sd.created_at AS discount_created_at,
                sd.updated_at AS discount_updated_at,
                s.id AS system_id,
                s.name AS system_name,
                s.description AS system_description,
                s.file_path AS system_file_path,
                s.image_path AS system_image_path,
                s.paypal_link AS system_paypal_link,
                s.roblox_gamepass_id AS system_roblox_gamepass_id,
                s.created_by AS system_created_by,
                s.created_at AS system_created_at
            FROM system_discounts sd
            JOIN systems s ON s.id = sd.system_id
            WHERE sd.user_id = ? AND LOWER(s.name) LIKE LOWER(?)
            ORDER BY LOWER(s.name) ASC
            LIMIT 25
            """,
            (user_id, like_value),
        )
        return [self._map_discount(row) for row in rows]

    async def _fetch_discount_row(self, user_id: int, system_id: int) -> aiosqlite.Row | None:
        return await self.database.fetchone(
            """
            SELECT
                sd.user_id,
                sd.discount_percent,
                sd.created_by AS discount_created_by,
                sd.updated_by AS discount_updated_by,
                sd.created_at AS discount_created_at,
                sd.updated_at AS discount_updated_at,
                s.id AS system_id,
                s.name AS system_name,
                s.description AS system_description,
                s.file_path AS system_file_path,
                s.image_path AS system_image_path,
                s.paypal_link AS system_paypal_link,
                s.roblox_gamepass_id AS system_roblox_gamepass_id,
                s.created_by AS system_created_by,
                s.created_at AS system_created_at
            FROM system_discounts sd
            JOIN systems s ON s.id = sd.system_id
            WHERE sd.user_id = ? AND sd.system_id = ?
            """,
            (user_id, system_id),
        )

    @staticmethod
    def _normalize_discount(discount_percent: int) -> int:
        if discount_percent <= 0 or discount_percent >= 100:
            raise PermissionDeniedError("אחוז ההנחה חייב להיות בין 1 ל-99.")
        return discount_percent

    @staticmethod
    def _map_system(row: aiosqlite.Row) -> SystemRecord:
        return SystemRecord(
            id=int(row["system_id"]),
            name=str(row["system_name"]),
            description=str(row["system_description"]),
            file_path=str(row["system_file_path"]),
            image_path=str(row["system_image_path"]) if row["system_image_path"] else None,
            paypal_link=str(row["system_paypal_link"]) if row["system_paypal_link"] else None,
            roblox_gamepass_id=str(row["system_roblox_gamepass_id"]) if row["system_roblox_gamepass_id"] else None,
            created_by=int(row["system_created_by"]) if row["system_created_by"] is not None else None,
            created_at=str(row["system_created_at"]),
        )

    def _map_discount(self, row: aiosqlite.Row) -> SystemDiscountRecord:
        return SystemDiscountRecord(
            user_id=int(row["user_id"]),
            system=self._map_system(row),
            discount_percent=int(row["discount_percent"]),
            created_by=int(row["discount_created_by"]) if row["discount_created_by"] is not None else None,
            updated_by=int(row["discount_updated_by"]) if row["discount_updated_by"] is not None else None,
            created_at=str(row["discount_created_at"]),
            updated_at=str(row["discount_updated_at"]),
        )