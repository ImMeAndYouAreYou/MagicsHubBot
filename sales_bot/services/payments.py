from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import aiosqlite

from sales_bot.db import Database
from sales_bot.exceptions import NotFoundError
from sales_bot.models import PurchaseRecord

if TYPE_CHECKING:
    from sales_bot.bot import SalesBot


class PaymentService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_purchase(self, user_id: int, system_id: int, paypal_link: str) -> PurchaseRecord:
        purchase_id = await self.database.insert(
            "INSERT INTO paypal_purchases (user_id, system_id, paypal_link) VALUES (?, ?, ?)",
            (user_id, system_id, paypal_link),
        )
        return await self.get_purchase(purchase_id)

    async def get_purchase(self, purchase_id: int) -> PurchaseRecord:
        row = await self.database.fetchone(
            "SELECT * FROM paypal_purchases WHERE id = ?",
            (purchase_id,),
        )
        if row is None:
            raise NotFoundError("Purchase not found.")
        return self._map_purchase(row)

    async def complete_purchase(self, bot: "SalesBot", purchase_id: int, payload: dict[str, Any]) -> PurchaseRecord:
        purchase = await self.get_purchase(purchase_id)
        if purchase.status == "completed":
            return purchase

        system = await bot.services.systems.get_system(purchase.system_id)
        user = await bot.fetch_user(purchase.user_id)
        await bot.services.delivery.deliver_system(
            bot,
            user,
            system,
            source=f"paypal:{purchase.id}",
            granted_by=None,
        )

        await self.database.execute(
            """
            UPDATE paypal_purchases
            SET status = 'completed', completed_at = CURRENT_TIMESTAMP, webhook_payload = ?
            WHERE id = ?
            """,
            (json.dumps(payload), purchase_id),
        )
        return await self.get_purchase(purchase_id)

    @staticmethod
    def _map_purchase(row: aiosqlite.Row) -> PurchaseRecord:
        return PurchaseRecord(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            system_id=int(row["system_id"]),
            status=str(row["status"]),
            paypal_link=str(row["paypal_link"]),
            created_at=str(row["created_at"]),
            completed_at=str(row["completed_at"]) if row["completed_at"] else None,
        )
