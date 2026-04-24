from __future__ import annotations

import json
from typing import Any

import aiosqlite

from sales_bot.db import Database
from sales_bot.exceptions import NotFoundError, PermissionDeniedError
from sales_bot.models import (
    RobloxLinkRecord,
    SpecialOrderRequestRecord,
    SpecialSystemImageRecord,
    SpecialSystemPaymentMethod,
    SpecialSystemRecord,
)
from sales_bot.storage import slugify


class SpecialSystemService:
    PAYMENT_METHODS = (
        ("paypal", "פייפאל"),
        ("bit", "ביט"),
        ("robux", "רובקס"),
        ("users_under_2014", "משתמשים מתחת לשנת 2014"),
        ("jailbreak_items", "דברים במשחק JailBreak"),
    )
    ACTIVE_STATUSES = ("pending", "accepted")

    def __init__(self, database: Database) -> None:
        self.database = database
        self._payment_labels = {key: label for key, label in self.PAYMENT_METHODS}

    def available_payment_methods(self) -> tuple[tuple[str, str], ...]:
        return self.PAYMENT_METHODS

    def payment_label(self, key: str) -> str:
        return self._payment_labels.get(key, key)

    async def create_special_system(
        self,
        *,
        title: str,
        description: str,
        payment_methods: list[tuple[str, str]],
        images: list[tuple[str, bytes, str | None]],
        channel_id: int,
        created_by: int,
    ) -> SpecialSystemRecord:
        cleaned_title = title.strip()
        cleaned_description = description.strip()
        if not cleaned_title:
            raise PermissionDeniedError("חובה להזין כותרת למערכת המיוחדת.")
        if not cleaned_description:
            raise PermissionDeniedError("חובה להזין תיאור למערכת המיוחדת.")
        if channel_id <= 0:
            raise PermissionDeniedError("חובה לבחור ערוץ תקין לשליחת ההודעה.")

        validated_payment_methods = self._normalize_payment_methods(payment_methods)
        slug = await self._allocate_slug(cleaned_title)
        special_system_id = await self.database.insert(
            """
            INSERT INTO special_systems (slug, title, description, payment_methods_json, channel_id, created_by)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                slug,
                cleaned_title,
                cleaned_description,
                json.dumps(validated_payment_methods, ensure_ascii=False),
                channel_id,
                created_by,
            ),
        )

        if images:
            await self.database.executemany(
                """
                INSERT INTO special_system_images (special_system_id, asset_name, content_type, asset_bytes, sort_order)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (special_system_id, asset_name, content_type, asset_bytes, index)
                    for index, (asset_name, asset_bytes, content_type) in enumerate(images)
                ],
            )

        return await self.get_special_system(special_system_id)

    async def list_special_systems(self, *, active_only: bool = False) -> list[SpecialSystemRecord]:
        query = "SELECT * FROM special_systems"
        parameters: tuple[Any, ...] = ()
        if active_only:
            query += " WHERE is_active = ?"
            parameters = (True,)
        query += " ORDER BY LOWER(title) ASC, id ASC"
        rows = await self.database.fetchall(query, parameters)
        return [self._map_special_system(row) for row in rows]

    async def get_special_system(self, special_system_id: int) -> SpecialSystemRecord:
        row = await self.database.fetchone("SELECT * FROM special_systems WHERE id = ?", (special_system_id,))
        if row is None:
            raise NotFoundError("המערכת המיוחדת לא נמצאה.")
        return self._map_special_system(row)

    async def get_special_system_by_slug(self, slug: str) -> SpecialSystemRecord:
        row = await self.database.fetchone(
            "SELECT * FROM special_systems WHERE LOWER(slug) = LOWER(?) AND is_active = ?",
            (slug.strip(), True),
        )
        if row is None:
            raise NotFoundError("המערכת המיוחדת לא נמצאה.")
        return self._map_special_system(row)

    async def list_special_system_images(self, special_system_id: int) -> list[SpecialSystemImageRecord]:
        rows = await self.database.fetchall(
            "SELECT * FROM special_system_images WHERE special_system_id = ? ORDER BY sort_order ASC, id ASC",
            (special_system_id,),
        )
        return [self._map_image(row) for row in rows]

    async def update_special_system(
        self,
        special_system_id: int,
        *,
        title: str,
        description: str,
        payment_methods: list[tuple[str, str]],
        channel_id: int,
        replace_images: bool = False,
        images: list[tuple[str, bytes, str | None]] | None = None,
    ) -> SpecialSystemRecord:
        current = await self.get_special_system(special_system_id)
        cleaned_title = title.strip()
        cleaned_description = description.strip()
        if not cleaned_title:
            raise PermissionDeniedError("חובה להזין כותרת למערכת המיוחדת.")
        if not cleaned_description:
            raise PermissionDeniedError("חובה להזין תיאור למערכת המיוחדת.")
        if channel_id <= 0:
            raise PermissionDeniedError("חובה לבחור ערוץ תקין לשליחת ההודעה.")
        validated_payment_methods = self._normalize_payment_methods(payment_methods)

        await self.database.execute(
            """
            UPDATE special_systems
            SET title = ?,
                description = ?,
                payment_methods_json = ?,
                channel_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                cleaned_title,
                cleaned_description,
                json.dumps(validated_payment_methods, ensure_ascii=False),
                channel_id,
                special_system_id,
            ),
        )

        incoming_images = list(images or [])
        if replace_images:
            await self.database.execute(
                "DELETE FROM special_system_images WHERE special_system_id = ?",
                (special_system_id,),
            )
            if incoming_images:
                await self.database.executemany(
                    """
                    INSERT INTO special_system_images (special_system_id, asset_name, content_type, asset_bytes, sort_order)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        (special_system_id, asset_name, content_type, asset_bytes, index)
                        for index, (asset_name, asset_bytes, content_type) in enumerate(incoming_images)
                    ],
                )
        elif incoming_images:
            existing_images = await self.list_special_system_images(special_system_id)
            start_index = len(existing_images)
            await self.database.executemany(
                """
                INSERT INTO special_system_images (special_system_id, asset_name, content_type, asset_bytes, sort_order)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (special_system_id, asset_name, content_type, asset_bytes, start_index + index)
                    for index, (asset_name, asset_bytes, content_type) in enumerate(incoming_images)
                ],
            )

        return await self.get_special_system(current.id)

    async def set_active(self, special_system_id: int, *, is_active: bool) -> SpecialSystemRecord:
        await self.database.execute(
            """
            UPDATE special_systems
            SET is_active = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (is_active, special_system_id),
        )
        return await self.get_special_system(special_system_id)

    async def get_special_system_image(self, image_id: int) -> SpecialSystemImageRecord:
        row = await self.database.fetchone("SELECT * FROM special_system_images WHERE id = ?", (image_id,))
        if row is None:
            raise NotFoundError("תמונת המערכת המיוחדת לא נמצאה.")
        return self._map_image(row)

    async def set_public_message(self, special_system_id: int, *, channel_id: int, message_id: int) -> SpecialSystemRecord:
        await self.database.execute(
            """
            UPDATE special_systems
            SET channel_id = ?, message_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (channel_id, message_id, special_system_id),
        )
        return await self.get_special_system(special_system_id)

    async def clear_public_message(self, special_system_id: int) -> SpecialSystemRecord:
        await self.database.execute(
            """
            UPDATE special_systems
            SET message_id = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (special_system_id,),
        )
        return await self.get_special_system(special_system_id)

    async def create_order_request(
        self,
        *,
        special_system_id: int,
        user_id: int,
        discord_name: str,
        roblox_name: str,
        payment_method_key: str,
        linked_account: RobloxLinkRecord | None,
    ) -> SpecialOrderRequestRecord:
        special_system = await self.get_special_system(special_system_id)
        payment_method = self._payment_method_from_system(special_system, payment_method_key)
        order_id = await self.database.insert(
            """
            INSERT INTO special_order_requests (
                special_system_id,
                user_id,
                discord_name,
                roblox_name,
                payment_method_key,
                payment_method_label,
                payment_price,
                linked_roblox_sub,
                linked_roblox_username,
                linked_roblox_display_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                special_system_id,
                user_id,
                discord_name.strip(),
                roblox_name.strip(),
                payment_method.key,
                payment_method.label,
                payment_method.price,
                linked_account.roblox_sub if linked_account else None,
                linked_account.roblox_username if linked_account else None,
                linked_account.roblox_display_name if linked_account else None,
            ),
        )
        return await self.get_order_request(order_id)

    async def get_order_request(self, order_id: int) -> SpecialOrderRequestRecord:
        row = await self.database.fetchone("SELECT * FROM special_order_requests WHERE id = ?", (order_id,))
        if row is None:
            raise NotFoundError("בקשת הקנייה המיוחדת לא נמצאה.")
        return self._map_order(row)

    async def list_order_requests(self, *, statuses: tuple[str, ...] | None = None) -> list[SpecialOrderRequestRecord]:
        query = "SELECT * FROM special_order_requests"
        parameters: tuple[Any, ...] = ()
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            query += f" WHERE status IN ({placeholders})"
            parameters = tuple(statuses)
        query += " ORDER BY submitted_at DESC, id DESC"
        rows = await self.database.fetchall(query, parameters)
        return [self._map_order(row) for row in rows]

    async def set_owner_message(self, order_id: int, message_id: int) -> None:
        await self.database.execute(
            "UPDATE special_order_requests SET owner_message_id = ? WHERE id = ?",
            (message_id, order_id),
        )

    async def resolve_order_request(
        self,
        order_id: int,
        *,
        reviewer_id: int,
        status: str,
        admin_reply: str | None,
    ) -> SpecialOrderRequestRecord:
        if status not in {"accepted", "rejected"}:
            raise PermissionDeniedError("סטטוס בקשה לא תקין.")

        order = await self.get_order_request(order_id)
        if order.status != "pending":
            raise PermissionDeniedError("הבקשה הזאת כבר טופלה.")

        await self.database.execute(
            """
            UPDATE special_order_requests
            SET status = ?, admin_reply = ?, reviewed_at = CURRENT_TIMESTAMP, reviewed_by = ?
            WHERE id = ?
            """,
            (status, admin_reply.strip() if admin_reply else None, reviewer_id, order_id),
        )
        return await self.get_order_request(order_id)

    async def _allocate_slug(self, title: str) -> str:
        base_slug = slugify(title)
        slug = base_slug
        suffix = 2
        while await self._slug_exists(slug):
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        return slug

    async def _slug_exists(self, slug: str) -> bool:
        row = await self.database.fetchone(
            "SELECT 1 FROM special_systems WHERE LOWER(slug) = LOWER(?)",
            (slug,),
        )
        return row is not None

    def _normalize_payment_methods(self, payment_methods: list[tuple[str, str]]) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        used_keys: set[str] = set()
        for raw_key, raw_price in payment_methods:
            key = str(raw_key).strip()
            price = str(raw_price).strip()
            if not key:
                continue
            if key not in self._payment_labels:
                raise PermissionDeniedError("נבחרה שיטת תשלום לא תקינה.")
            if key in used_keys:
                raise PermissionDeniedError("אי אפשר לבחור את אותה שיטת התשלום פעמיים.")
            if not price:
                raise PermissionDeniedError(f"חובה להזין מחיר עבור {self.payment_label(key)}.")
            used_keys.add(key)
            normalized.append({"key": key, "label": self.payment_label(key), "price": price})

        if not normalized:
            raise PermissionDeniedError("חובה לבחור לפחות שיטת תשלום אחת.")
        return normalized

    def _payment_method_from_system(self, special_system: SpecialSystemRecord, payment_method_key: str) -> SpecialSystemPaymentMethod:
        requested_key = payment_method_key.strip()
        for method in special_system.payment_methods:
            if method.key == requested_key:
                return method
        raise PermissionDeniedError("שיטת התשלום שנבחרה לא זמינה עבור המערכת הזאת.")

    @staticmethod
    def _map_special_system(row: aiosqlite.Row) -> SpecialSystemRecord:
        raw_payment_methods = json.loads(str(row["payment_methods_json"]))
        payment_methods = tuple(
            SpecialSystemPaymentMethod(
                key=str(item.get("key") or ""),
                label=str(item.get("label") or ""),
                price=str(item.get("price") or ""),
            )
            for item in raw_payment_methods
            if isinstance(item, dict)
        )
        return SpecialSystemRecord(
            id=int(row["id"]),
            slug=str(row["slug"]),
            title=str(row["title"]),
            description=str(row["description"]),
            payment_methods=payment_methods,
            channel_id=int(row["channel_id"]),
            message_id=int(row["message_id"]) if row["message_id"] is not None else None,
            created_by=int(row["created_by"]) if row["created_by"] is not None else None,
            is_active=bool(row["is_active"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _map_image(row: aiosqlite.Row) -> SpecialSystemImageRecord:
        return SpecialSystemImageRecord(
            id=int(row["id"]),
            special_system_id=int(row["special_system_id"]),
            asset_name=str(row["asset_name"]),
            content_type=str(row["content_type"]) if row["content_type"] else None,
            asset_bytes=bytes(row["asset_bytes"]),
            sort_order=int(row["sort_order"]),
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _map_order(row: aiosqlite.Row) -> SpecialOrderRequestRecord:
        return SpecialOrderRequestRecord(
            id=int(row["id"]),
            special_system_id=int(row["special_system_id"]),
            user_id=int(row["user_id"]),
            discord_name=str(row["discord_name"]),
            roblox_name=str(row["roblox_name"]),
            payment_method_key=str(row["payment_method_key"]),
            payment_method_label=str(row["payment_method_label"]),
            payment_price=str(row["payment_price"]),
            linked_roblox_sub=str(row["linked_roblox_sub"]) if row["linked_roblox_sub"] else None,
            linked_roblox_username=str(row["linked_roblox_username"]) if row["linked_roblox_username"] else None,
            linked_roblox_display_name=(
                str(row["linked_roblox_display_name"]) if row["linked_roblox_display_name"] else None
            ),
            status=str(row["status"]),
            owner_message_id=int(row["owner_message_id"]) if row["owner_message_id"] is not None else None,
            admin_reply=str(row["admin_reply"]) if row["admin_reply"] else None,
            submitted_at=str(row["submitted_at"]),
            reviewed_at=str(row["reviewed_at"]) if row["reviewed_at"] else None,
            reviewed_by=int(row["reviewed_by"]) if row["reviewed_by"] is not None else None,
        )