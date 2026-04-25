from __future__ import annotations

import aiosqlite

from sales_bot.db import Database
from sales_bot.exceptions import AlreadyExistsError, NotFoundError, PermissionDeniedError
from sales_bot.models import CartItemRecord, SystemRecord


class CartService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def add_system(self, user_id: int, system: SystemRecord) -> CartItemRecord:
        if not system.website_price:
            raise PermissionDeniedError("אי אפשר להוסיף את המערכת הזאת לעגלה לפני שמוגדר לה מחיר אתר.")
        if system.is_special_system:
            raise PermissionDeniedError("מערכת שמסומנת כמיוחדת לא זמינה לעגלת המערכות הרגילה.")
        if not system.is_visible_on_website or not system.is_for_sale or not system.is_in_stock:
            raise PermissionDeniedError("המערכת הזאת לא זמינה כרגע לקופה באתר.")

        existing_ownership = await self.database.fetchone(
            "SELECT 1 FROM user_systems WHERE user_id = ? AND system_id = ?",
            (user_id, system.id),
        )
        if existing_ownership is not None:
            raise AlreadyExistsError("המערכת הזאת כבר בבעלותך.")

        await self.database.execute(
            """
            INSERT INTO website_cart_items (user_id, system_id)
            VALUES (?, ?)
            ON CONFLICT(user_id, system_id)
            DO UPDATE SET added_at = CURRENT_TIMESTAMP
            """,
            (user_id, system.id),
        )
        return await self.get_item(user_id, system.id)

    async def get_item(self, user_id: int, system_id: int) -> CartItemRecord:
        row = await self.database.fetchone(
            """
            SELECT c.user_id AS cart_user_id, c.added_at AS cart_added_at, s.*
            FROM website_cart_items c
            JOIN systems s ON s.id = c.system_id
            WHERE c.user_id = ? AND c.system_id = ?
            """,
            (user_id, system_id),
        )
        if row is None:
            raise NotFoundError("המערכת הזאת לא נמצאת כרגע בעגלה שלך.")
        return self._map_cart_item(row)

    async def list_items(self, user_id: int) -> list[CartItemRecord]:
        rows = await self.database.fetchall(
            """
            SELECT c.user_id AS cart_user_id, c.added_at AS cart_added_at, s.*
            FROM website_cart_items c
            JOIN systems s ON s.id = c.system_id
            WHERE c.user_id = ?
            ORDER BY c.added_at DESC, LOWER(s.name) ASC
            """,
            (user_id,),
        )
        return [self._map_cart_item(row) for row in rows]

    async def remove_system(self, user_id: int, system_id: int) -> None:
        existing = await self.database.fetchone(
            "SELECT 1 FROM website_cart_items WHERE user_id = ? AND system_id = ?",
            (user_id, system_id),
        )
        if existing is None:
            raise NotFoundError("המערכת הזאת לא נמצאת בעגלה שלך.")
        await self.database.execute(
            "DELETE FROM website_cart_items WHERE user_id = ? AND system_id = ?",
            (user_id, system_id),
        )

    async def clear_cart(self, user_id: int) -> None:
        await self.database.execute("DELETE FROM website_cart_items WHERE user_id = ?", (user_id,))

    async def count_items(self, user_id: int) -> int:
        row = await self.database.fetchone(
            "SELECT COUNT(*) AS total FROM website_cart_items WHERE user_id = ?",
            (user_id,),
        )
        return int(row["total"]) if row is not None else 0

    @staticmethod
    def _map_cart_item(row: aiosqlite.Row) -> CartItemRecord:
        row_keys = set(row.keys())
        return CartItemRecord(
            user_id=int(row["cart_user_id"]),
            system=SystemRecord(
                id=int(row["id"]),
                name=str(row["name"]),
                description=str(row["description"]),
                file_path=str(row["file_path"]),
                image_path=str(row["image_path"]) if row["image_path"] else None,
                paypal_link=str(row["paypal_link"]) if row["paypal_link"] else None,
                roblox_gamepass_id=str(row["roblox_gamepass_id"]) if row["roblox_gamepass_id"] else None,
                is_visible_on_website=bool(row["is_visible_on_website"]) if "is_visible_on_website" in row_keys else True,
                is_for_sale=bool(row["is_for_sale"]) if "is_for_sale" in row_keys else True,
                is_in_stock=bool(row["is_in_stock"]) if "is_in_stock" in row_keys else True,
                website_price=(str(row["website_price"]) if "website_price" in row_keys and row["website_price"] else None),
                website_currency=(str(row["website_currency"]).upper() if "website_currency" in row_keys and row["website_currency"] else "USD"),
                is_special_system=bool(row["is_special_system"]) if "is_special_system" in row_keys else False,
                created_by=int(row["created_by"]) if row["created_by"] is not None else None,
                created_at=str(row["created_at"]),
            ),
            added_at=str(row["cart_added_at"]),
        )