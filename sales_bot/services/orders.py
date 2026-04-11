from __future__ import annotations

import aiosqlite

from sales_bot.db import Database
from sales_bot.exceptions import NotFoundError, PermissionDeniedError
from sales_bot.models import OrderRequestRecord


class OrderService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_request(
        self,
        *,
        user_id: int,
        requested_item: str,
        required_timeframe: str,
        payment_method: str,
        offered_price: str,
    ) -> OrderRequestRecord:
        order_id = await self.database.insert(
            """
            INSERT INTO order_requests (user_id, requested_item, required_timeframe, payment_method, offered_price)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, requested_item.strip(), required_timeframe.strip(), payment_method.strip(), offered_price.strip()),
        )
        return await self.get_request(order_id)

    async def get_request(self, order_id: int) -> OrderRequestRecord:
        row = await self.database.fetchone("SELECT * FROM order_requests WHERE id = ?", (order_id,))
        if row is None:
            raise NotFoundError("הזמנה לא נמצאה.")
        return self._map_order(row)

    async def list_pending_requests(self) -> list[OrderRequestRecord]:
        rows = await self.database.fetchall(
            "SELECT * FROM order_requests WHERE status = 'pending' ORDER BY submitted_at ASC"
        )
        return [self._map_order(row) for row in rows]

    async def set_owner_message(self, order_id: int, message_id: int) -> None:
        await self.database.execute(
            "UPDATE order_requests SET owner_message_id = ? WHERE id = ?",
            (message_id, order_id),
        )

    async def resolve_request(self, order_id: int, reviewer_id: int, status: str) -> OrderRequestRecord:
        if status not in {"accepted", "rejected"}:
            raise PermissionDeniedError("סטטוס הזמנה לא תקין.")

        order = await self.get_request(order_id)
        if order.status != "pending":
            raise PermissionDeniedError("ההזמנה הזאת כבר טופלה.")

        await self.database.execute(
            """
            UPDATE order_requests
            SET status = ?, reviewed_at = CURRENT_TIMESTAMP, reviewed_by = ?
            WHERE id = ?
            """,
            (status, reviewer_id, order_id),
        )
        return await self.get_request(order_id)

    @staticmethod
    def _map_order(row: aiosqlite.Row) -> OrderRequestRecord:
        return OrderRequestRecord(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            requested_item=str(row["requested_item"]),
            required_timeframe=str(row["required_timeframe"]),
            payment_method=str(row["payment_method"]),
            offered_price=str(row["offered_price"]),
            status=str(row["status"]),
            owner_message_id=int(row["owner_message_id"]) if row["owner_message_id"] is not None else None,
            submitted_at=str(row["submitted_at"]),
            reviewed_at=str(row["reviewed_at"]) if row["reviewed_at"] else None,
            reviewed_by=int(row["reviewed_by"]) if row["reviewed_by"] is not None else None,
        )