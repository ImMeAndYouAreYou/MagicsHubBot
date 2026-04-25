from __future__ import annotations

import aiosqlite

from sales_bot.db import Database
from sales_bot.exceptions import NotFoundError, PermissionDeniedError
from sales_bot.models import OrderRequestImageRecord, OrderRequestRecord


class OrderService:
    ACTIVE_STATUSES = ("pending", "accepted")
    PAYMENT_METHODS = (
        ("paypal", "פייפאל"),
        ("bit", "ביט"),
        ("robux", "רובקס"),
        ("users_under_2014", "משתמשים מתחת לשנת 2014"),
        ("jailbreak_items", "דברים במשחק JailBreak"),
    )

    def __init__(self, database: Database) -> None:
        self.database = database
        self._payment_labels = {key: label for key, label in self.PAYMENT_METHODS}

    def available_payment_methods(self) -> tuple[tuple[str, str], ...]:
        return self.PAYMENT_METHODS

    def payment_label(self, key: str) -> str:
        return self._payment_labels.get(key, key)

    async def create_request(
        self,
        *,
        user_id: int,
        requested_item: str,
        required_timeframe: str,
        payment_method: str,
        offered_price: str,
        roblox_username: str,
        images: list[tuple[str, bytes, str | None]] | None = None,
    ) -> OrderRequestRecord:
        payment_method_label = self._normalize_payment_method(payment_method)
        order_id = await self.database.insert(
            """
            INSERT INTO order_requests (
                user_id,
                requested_item,
                required_timeframe,
                payment_method,
                offered_price,
                roblox_username
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                requested_item.strip(),
                required_timeframe.strip(),
                payment_method_label,
                offered_price.strip(),
                roblox_username.strip(),
            ),
        )
        normalized_images = list(images or [])
        if normalized_images:
            await self.database.executemany(
                """
                INSERT INTO order_request_images (order_id, asset_name, content_type, asset_bytes, sort_order)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (order_id, asset_name, content_type, asset_bytes, index)
                    for index, (asset_name, asset_bytes, content_type) in enumerate(normalized_images)
                ],
            )
        return await self.get_request(order_id)

    async def get_request(self, order_id: int) -> OrderRequestRecord:
        row = await self.database.fetchone("SELECT * FROM order_requests WHERE id = ?", (order_id,))
        if row is None:
            raise NotFoundError("הזמנה לא נמצאה.")
        return self._map_order(row)

    async def list_pending_requests(self) -> list[OrderRequestRecord]:
        return await self.list_requests(statuses=("pending",))

    async def list_active_requests(self) -> list[OrderRequestRecord]:
        return await self.list_requests(statuses=self.ACTIVE_STATUSES)

    async def list_requests(self, *, statuses: tuple[str, ...] | None = None) -> list[OrderRequestRecord]:
        query = "SELECT * FROM order_requests"
        parameters: tuple[object, ...] = ()
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            query += f" WHERE status IN ({placeholders})"
            parameters = tuple(statuses)
        query += " ORDER BY submitted_at DESC, id DESC"
        rows = await self.database.fetchall(query, parameters)
        return [self._map_order(row) for row in rows]

    async def list_request_images(self, order_id: int) -> list[OrderRequestImageRecord]:
        rows = await self.database.fetchall(
            "SELECT * FROM order_request_images WHERE order_id = ? ORDER BY sort_order ASC, id ASC",
            (order_id,),
        )
        return [self._map_image(row) for row in rows]

    async def get_request_image(self, image_id: int) -> OrderRequestImageRecord:
        row = await self.database.fetchone("SELECT * FROM order_request_images WHERE id = ?", (image_id,))
        if row is None:
            raise NotFoundError("תמונת ההזמנה האישית לא נמצאה.")
        return self._map_image(row)

    async def set_owner_message(self, order_id: int, message_id: int) -> None:
        await self.database.execute(
            "UPDATE order_requests SET owner_message_id = ? WHERE id = ?",
            (message_id, order_id),
        )

    async def resolve_request(
        self,
        order_id: int,
        reviewer_id: int,
        status: str,
        admin_reply: str | None = None,
    ) -> OrderRequestRecord:
        if status not in {"accepted", "rejected", "completed"}:
            raise PermissionDeniedError("סטטוס הזמנה לא תקין.")

        order = await self.get_request(order_id)
        if order.status in {"completed", "rejected"}:
            raise PermissionDeniedError("ההזמנה הזאת כבר טופלה.")

        if status == "accepted" and order.status != "pending":
            raise PermissionDeniedError("אפשר לקבל הזמנה רק כשהיא עדיין ממתינה לטיפול.")

        await self.database.execute(
            """
            UPDATE order_requests
            SET status = ?, admin_reply = ?, reviewed_at = CURRENT_TIMESTAMP, reviewed_by = ?
            WHERE id = ?
            """,
            (status, admin_reply.strip() if admin_reply else None, reviewer_id, order_id),
        )
        return await self.get_request(order_id)

    async def delete_request(self, order_id: int) -> OrderRequestRecord:
        order = await self.get_request(order_id)
        await self.database.execute("DELETE FROM order_requests WHERE id = ?", (order_id,))
        return order

    def _normalize_payment_method(self, payment_method: str) -> str:
        raw_value = payment_method.strip()
        if not raw_value:
            raise PermissionDeniedError("חובה לבחור שיטת תשלום.")
        if raw_value in self._payment_labels:
            return self.payment_label(raw_value)

        normalized = raw_value.casefold()
        for key, label in self.PAYMENT_METHODS:
            if label.casefold() == normalized or key.casefold() == normalized:
                return label

        raise PermissionDeniedError("נבחרה שיטת תשלום לא תקינה.")

    @staticmethod
    def _map_order(row: aiosqlite.Row) -> OrderRequestRecord:
        return OrderRequestRecord(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            requested_item=str(row["requested_item"]),
            required_timeframe=str(row["required_timeframe"]),
            payment_method=str(row["payment_method"]),
            offered_price=str(row["offered_price"]),
            roblox_username=str(row["roblox_username"]) if row["roblox_username"] else None,
            status=str(row["status"]),
            owner_message_id=int(row["owner_message_id"]) if row["owner_message_id"] is not None else None,
            admin_reply=str(row["admin_reply"]) if row["admin_reply"] else None,
            submitted_at=str(row["submitted_at"]),
            reviewed_at=str(row["reviewed_at"]) if row["reviewed_at"] else None,
            reviewed_by=int(row["reviewed_by"]) if row["reviewed_by"] is not None else None,
        )

    @staticmethod
    def _map_image(row: aiosqlite.Row) -> OrderRequestImageRecord:
        return OrderRequestImageRecord(
            id=int(row["id"]),
            order_id=int(row["order_id"]),
            asset_name=str(row["asset_name"]),
            content_type=str(row["content_type"]) if row["content_type"] else None,
            asset_bytes=bytes(row["asset_bytes"]),
            sort_order=int(row["sort_order"]),
            created_at=str(row["created_at"]),
        )