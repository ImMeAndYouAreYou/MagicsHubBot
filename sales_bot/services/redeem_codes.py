from __future__ import annotations

from datetime import datetime
import re
import secrets
from typing import TYPE_CHECKING

import aiosqlite
import asyncpg

from sales_bot.db import Database
from sales_bot.exceptions import AlreadyExistsError, ExternalServiceError, NotFoundError, PermissionDeniedError
from sales_bot.models import RedeemCodeRecord, RedeemCodeRedemptionRecord, SystemRecord

if TYPE_CHECKING:
    from sales_bot.bot import SalesBot


class RedeemCodeService:
    ADMIN_SOURCE = "admin"
    CHECKOUT_GIFT_SOURCE = "checkout-gift"
    RANDOM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    RANDOM_LENGTH = 10

    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_code(
        self,
        *,
        code: str | None,
        system_id: int | None,
        max_redemptions: int = 1,
        expires_at: str | None = None,
        created_by: int | None,
        issued_to_user_id: int | None = None,
        checkout_order_id: int | None = None,
        source: str = ADMIN_SOURCE,
    ) -> RedeemCodeRecord:
        normalized_source = self._normalize_source(source)
        normalized_max_redemptions = self._normalize_max_redemptions(max_redemptions)
        normalized_expires_at = self._normalize_expires_at(expires_at)
        custom_code = str(code or "").strip()

        for _attempt in range(8 if not custom_code else 1):
            prepared_code = self._normalize_code(custom_code) if custom_code else self._generate_code(system_id)
            try:
                code_id = await self.database.insert(
                    """
                    INSERT INTO redeem_codes (
                        code,
                        system_id,
                        issued_to_user_id,
                        checkout_order_id,
                        source,
                        max_redemptions,
                        expires_at,
                        created_by
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        prepared_code,
                        system_id,
                        issued_to_user_id,
                        checkout_order_id,
                        normalized_source,
                        normalized_max_redemptions,
                        normalized_expires_at,
                        created_by,
                    ),
                )
                return await self.get_code(code_id)
            except (aiosqlite.IntegrityError, asyncpg.UniqueViolationError) as exc:
                if custom_code:
                    raise AlreadyExistsError("קוד המימוש הזה כבר קיים.") from exc

        raise ExternalServiceError("לא הצלחתי ליצור קוד מימוש ייחודי. נסה שוב.")

    async def get_code(self, code_id: int) -> RedeemCodeRecord:
        row = await self.database.fetchone(
            """
            SELECT rc.*, (
                SELECT COUNT(*)
                FROM redeem_code_redemptions rcr
                WHERE rcr.redeem_code_id = rc.id
            ) AS redeemed_count
            FROM redeem_codes rc
            WHERE rc.id = ?
            """,
            (code_id,),
        )
        if row is None:
            raise NotFoundError("קוד המימוש לא נמצא.")
        return self._map_code(row)

    async def get_code_optional(self, code_text: str) -> RedeemCodeRecord | None:
        normalized_code = self._normalize_code(code_text)
        row = await self.database.fetchone(
            """
            SELECT rc.*, (
                SELECT COUNT(*)
                FROM redeem_code_redemptions rcr
                WHERE rcr.redeem_code_id = rc.id
            ) AS redeemed_count
            FROM redeem_codes rc
            WHERE rc.code = ?
            """,
            (normalized_code,),
        )
        return self._map_code(row) if row is not None else None

    async def list_codes(self, *, limit: int = 200) -> list[RedeemCodeRecord]:
        rows = await self.database.fetchall(
            """
            SELECT rc.*, (
                SELECT COUNT(*)
                FROM redeem_code_redemptions rcr
                WHERE rcr.redeem_code_id = rc.id
            ) AS redeemed_count
            FROM redeem_codes rc
            ORDER BY rc.created_at DESC, rc.id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [self._map_code(row) for row in rows]

    async def list_codes_for_user(self, user_id: int, *, limit: int = 100) -> list[RedeemCodeRecord]:
        rows = await self.database.fetchall(
            """
            SELECT rc.*, (
                SELECT COUNT(*)
                FROM redeem_code_redemptions rcr
                WHERE rcr.redeem_code_id = rc.id
            ) AS redeemed_count
            FROM redeem_codes rc
            WHERE rc.issued_to_user_id = ?
            ORDER BY rc.created_at DESC, rc.id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        return [self._map_code(row) for row in rows]

    async def list_codes_for_order(self, order_id: int) -> list[RedeemCodeRecord]:
        rows = await self.database.fetchall(
            """
            SELECT rc.*, (
                SELECT COUNT(*)
                FROM redeem_code_redemptions rcr
                WHERE rcr.redeem_code_id = rc.id
            ) AS redeemed_count
            FROM redeem_codes rc
            WHERE rc.checkout_order_id = ?
            ORDER BY rc.created_at ASC, rc.id ASC
            """,
            (order_id,),
        )
        return [self._map_code(row) for row in rows]

    async def list_redemptions(self, code_id: int) -> list[RedeemCodeRedemptionRecord]:
        rows = await self.database.fetchall(
            "SELECT * FROM redeem_code_redemptions WHERE redeem_code_id = ? ORDER BY redeemed_at ASC, id ASC",
            (code_id,),
        )
        return [self._map_redemption(row) for row in rows]

    async def set_active(self, code_id: int, is_active: bool) -> RedeemCodeRecord:
        await self.database.execute(
            "UPDATE redeem_codes SET is_active = ? WHERE id = ?",
            (bool(is_active), code_id),
        )
        return await self.get_code(code_id)

    async def delete_code(self, code_id: int) -> None:
        await self.get_code(code_id)
        await self.database.execute("DELETE FROM redeem_codes WHERE id = ?", (code_id,))

    async def issue_checkout_gift_codes(
        self,
        *,
        order_id: int,
        issued_to_user_id: int,
        systems: list[SystemRecord],
        created_by: int | None,
    ) -> list[RedeemCodeRecord]:
        existing_codes = await self.list_codes_for_order(order_id)
        existing_system_ids = {code.system_id for code in existing_codes if code.system_id is not None}
        issued_codes = list(existing_codes)

        for system in systems:
            if system.id in existing_system_ids:
                continue
            issued_codes.append(
                await self.create_code(
                    code=None,
                    system_id=system.id,
                    max_redemptions=1,
                    expires_at=None,
                    created_by=created_by,
                    issued_to_user_id=issued_to_user_id,
                    checkout_order_id=order_id,
                    source=self.CHECKOUT_GIFT_SOURCE,
                )
            )

        return sorted(issued_codes, key=lambda issued_code: issued_code.id)

    async def redeem_code(
        self,
        bot: "SalesBot",
        *,
        user_id: int,
        code_text: str,
    ) -> tuple[RedeemCodeRecord, SystemRecord]:
        code = await self.get_code_optional(code_text)
        if code is None:
            raise NotFoundError("קוד המימוש הזה לא קיים.")
        if not code.is_active:
            raise PermissionDeniedError("קוד המימוש הזה כבוי כרגע.")
        if code.expires_at and self._is_expired(code.expires_at):
            raise PermissionDeniedError("קוד המימוש הזה כבר פג תוקף.")
        if code.system_id is None:
            raise PermissionDeniedError("הקוד הזה עדיין לא מחובר למערכת שאפשר לממש.")
        if code.redeemed_count >= code.max_redemptions:
            raise PermissionDeniedError("כבר ניצלו את כל המימושים הזמינים לקוד הזה.")
        if await self._user_redeemed_code(code.id, user_id):
            raise PermissionDeniedError("כבר מימשת את הקוד הזה בחשבון שלך.")
        if await bot.services.ownership.user_owns_system(user_id, code.system_id):
            raise PermissionDeniedError("המערכת שמחוברת לקוד הזה כבר בבעלותך, ולכן אי אפשר לממש אותו.")

        redemption_id = await self.database.insert(
            "INSERT INTO redeem_code_redemptions (redeem_code_id, user_id) VALUES (?, ?)",
            (code.id, user_id),
        )
        current_count = await self._count_redemptions(code.id)
        if current_count > code.max_redemptions:
            await self.database.execute("DELETE FROM redeem_code_redemptions WHERE id = ?", (redemption_id,))
            raise PermissionDeniedError("כבר ניצלו את כל המימושים הזמינים לקוד הזה.")

        system = await bot.services.systems.get_system(code.system_id)
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        try:
            await bot.services.delivery.deliver_system(
                bot,
                user,
                system,
                source=f"redeem-code:{code.id}",
                granted_by=code.created_by,
            )
        except Exception:
            await self.database.execute("DELETE FROM redeem_code_redemptions WHERE id = ?", (redemption_id,))
            raise

        await bot.services.notifications.create_notification(
            user_id=user_id,
            title=f"קוד מומש עבור {system.name}",
            body=f"קוד המימוש {code.code} מומש בהצלחה, והמערכת {system.name} נשלחה אליך ב-DM ונרשמה בבעלותך.",
            link_path="/profile",
            kind="redeem-code",
            created_by=code.created_by,
        )
        return await self.get_code(code.id), system

    async def _count_redemptions(self, code_id: int) -> int:
        row = await self.database.fetchone(
            "SELECT COUNT(*) AS total FROM redeem_code_redemptions WHERE redeem_code_id = ?",
            (code_id,),
        )
        return int(row["total"]) if row is not None else 0

    async def _user_redeemed_code(self, code_id: int, user_id: int) -> bool:
        row = await self.database.fetchone(
            "SELECT 1 FROM redeem_code_redemptions WHERE redeem_code_id = ? AND user_id = ?",
            (code_id, user_id),
        )
        return row is not None

    @staticmethod
    def _normalize_code(code_text: str) -> str:
        normalized = str(code_text or "").strip().upper()
        if not normalized:
            raise PermissionDeniedError("חובה להזין קוד מימוש.")
        if not re.fullmatch(r"[A-Z0-9_-]{4,64}", normalized):
            raise PermissionDeniedError("קוד המימוש יכול להכיל רק אותיות באנגלית, מספרים, מקף וקו תחתון.")
        return normalized

    @staticmethod
    def _normalize_max_redemptions(max_redemptions: int) -> int:
        if max_redemptions <= 0:
            raise PermissionDeniedError("מספר המימושים המקסימלי חייב להיות גדול מאפס.")
        return int(max_redemptions)

    @classmethod
    def _normalize_source(cls, source: str) -> str:
        normalized = str(source or cls.ADMIN_SOURCE).strip().lower()
        if normalized not in {cls.ADMIN_SOURCE, cls.CHECKOUT_GIFT_SOURCE}:
            raise PermissionDeniedError("מקור קוד המימוש לא נתמך.")
        return normalized

    @staticmethod
    def _normalize_expires_at(expires_at: str | None) -> str | None:
        cleaned = str(expires_at or "").strip()
        if not cleaned:
            return None
        try:
            parsed = datetime.fromisoformat(cleaned)
        except ValueError as exc:
            raise PermissionDeniedError("תאריך התפוגה של קוד המימוש לא תקין.") from exc
        return parsed.isoformat(timespec="seconds")

    @staticmethod
    def _is_expired(expires_at: str) -> bool:
        try:
            parsed = datetime.fromisoformat(str(expires_at))
        except ValueError:
            return False
        return parsed <= datetime.now(parsed.tzinfo)

    @classmethod
    def _generate_code(cls, system_id: int | None) -> str:
        prefix = f"S{system_id}X" if system_id is not None else "GIFTX"
        random_part = "".join(secrets.choice(cls.RANDOM_ALPHABET) for _ in range(cls.RANDOM_LENGTH))
        return f"{prefix}{random_part}"

    @staticmethod
    def _map_code(row: aiosqlite.Row | asyncpg.Record) -> RedeemCodeRecord:
        row_keys = set(row.keys())
        return RedeemCodeRecord(
            id=int(row["id"]),
            code=str(row["code"]),
            system_id=int(row["system_id"]) if row["system_id"] is not None else None,
            issued_to_user_id=int(row["issued_to_user_id"]) if row["issued_to_user_id"] is not None else None,
            checkout_order_id=int(row["checkout_order_id"]) if row["checkout_order_id"] is not None else None,
            source=str(row["source"]),
            max_redemptions=int(row["max_redemptions"]),
            is_active=bool(row["is_active"]),
            expires_at=str(row["expires_at"]) if row["expires_at"] else None,
            created_by=int(row["created_by"]) if row["created_by"] is not None else None,
            created_at=str(row["created_at"]),
            redeemed_count=int(row["redeemed_count"]) if "redeemed_count" in row_keys and row["redeemed_count"] is not None else 0,
        )

    @staticmethod
    def _map_redemption(row: aiosqlite.Row | asyncpg.Record) -> RedeemCodeRedemptionRecord:
        return RedeemCodeRedemptionRecord(
            id=int(row["id"]),
            redeem_code_id=int(row["redeem_code_id"]),
            user_id=int(row["user_id"]),
            redeemed_at=str(row["redeemed_at"]),
        )