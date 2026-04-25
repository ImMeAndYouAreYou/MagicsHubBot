from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Iterable
from typing import TYPE_CHECKING, Any

import aiohttp
import aiosqlite
import discord

from sales_bot.db import Database
from sales_bot.exceptions import ConfigurationError, ExternalServiceError, NotFoundError, PermissionDeniedError
from sales_bot.models import CheckoutOrderItemRecord, CheckoutOrderRecord, PurchaseRecord, SystemRecord

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

    async def create_checkout_order(
        self,
        *,
        user_id: int,
        payment_method: str,
        items: Iterable[tuple[SystemRecord, str]],
        subtotal_amount: str,
        discount_amount: str,
        total_amount: str,
        currency: str,
        note: str | None,
        discount_code_id: int | None = None,
        discount_code_text: str | None = None,
    ) -> CheckoutOrderRecord:
        normalized_method = payment_method.strip().lower()
        if normalized_method not in {"card", "paypal"}:
            raise PermissionDeniedError("שיטת התשלום שנבחרה לא נתמכת בקופה.")

        item_list = list(items)
        if not item_list:
            raise PermissionDeniedError("אי אפשר לפתוח קופה בלי מערכות בעגלה.")

        order_id = await self.database.insert(
            """
            INSERT INTO website_checkout_orders (
                user_id,
                payment_method,
                discount_code_id,
                discount_code_text,
                subtotal_amount,
                discount_amount,
                total_amount,
                currency,
                note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                normalized_method,
                discount_code_id,
                discount_code_text.strip().upper() if discount_code_text else None,
                subtotal_amount,
                discount_amount,
                total_amount,
                currency.strip().upper(),
                note.strip() if note else None,
            ),
        )
        try:
            await self.database.executemany(
                """
                INSERT INTO website_checkout_order_items (order_id, system_id, system_name, unit_price, line_total)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (order_id, system.id, system.name, unit_price, unit_price)
                    for system, unit_price in item_list
                ],
            )
        except Exception:
            await self.database.execute("DELETE FROM website_checkout_orders WHERE id = ?", (order_id,))
            raise
        return await self.get_checkout_order(order_id)

    async def get_checkout_order(self, order_id: int) -> CheckoutOrderRecord:
        row = await self.database.fetchone(
            "SELECT * FROM website_checkout_orders WHERE id = ?",
            (order_id,),
        )
        if row is None:
            raise NotFoundError("ההזמנה לא נמצאה.")
        return self._map_checkout_order(row)

    async def get_checkout_order_by_paypal_order_id(self, paypal_order_id: str) -> CheckoutOrderRecord:
        row = await self.database.fetchone(
            "SELECT * FROM website_checkout_orders WHERE paypal_order_id = ?",
            (paypal_order_id.strip(),),
        )
        if row is None:
            raise NotFoundError("לא נמצאה הזמנת אתר שמחוברת להזמנת PayPal הזו.")
        return self._map_checkout_order(row)

    async def list_checkout_order_items(self, order_id: int) -> list[CheckoutOrderItemRecord]:
        rows = await self.database.fetchall(
            "SELECT * FROM website_checkout_order_items WHERE order_id = ? ORDER BY system_name ASC",
            (order_id,),
        )
        return [self._map_checkout_item(row) for row in rows]

    async def list_user_checkout_orders(self, user_id: int) -> list[CheckoutOrderRecord]:
        rows = await self.database.fetchall(
            "SELECT * FROM website_checkout_orders WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        return [self._map_checkout_order(row) for row in rows]

    async def list_pending_checkout_orders(self) -> list[CheckoutOrderRecord]:
        rows = await self.database.fetchall(
            "SELECT * FROM website_checkout_orders WHERE status = 'pending' ORDER BY created_at ASC",
        )
        return [self._map_checkout_order(row) for row in rows]

    async def list_checkout_orders(self, *, limit: int = 100) -> list[CheckoutOrderRecord]:
        rows = await self.database.fetchall(
            "SELECT * FROM website_checkout_orders ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [self._map_checkout_order(row) for row in rows]

    async def start_paypal_checkout(self, bot: "SalesBot", order_id: int) -> CheckoutOrderRecord:
        order = await self.get_checkout_order(order_id)
        if order.payment_method != "paypal":
            raise PermissionDeniedError("אפשר לפתוח הזמנת PayPal רק להזמנות שנוצרו בשיטת PayPal.")
        if order.status != "pending":
            raise PermissionDeniedError("אפשר לפתוח PayPal רק להזמנת קופה שעדיין ממתינה לתשלום.")
        if order.paypal_order_id and order.paypal_approval_url and order.paypal_status.lower() not in {
            "completed",
            "voided",
            "cancelled",
            "failed",
        }:
            return order

        access_token = await self._paypal_access_token(bot)
        items = await self.list_checkout_order_items(order.id)
        payload = self._paypal_order_payload(bot, order, items)
        response = await self._paypal_request_json(
            bot,
            "POST",
            "/v2/checkout/orders",
            access_token=access_token,
            json_body=payload,
        )
        paypal_order_id = self._extract_paypal_order_id(response)
        approval_url = self._extract_paypal_approval_url(response)
        if not paypal_order_id or not approval_url:
            raise ExternalServiceError("PayPal לא החזיר מזהה הזמנה או קישור אישור תקין.")

        return await self._store_paypal_state(
            order.id,
            paypal_status=str(response.get("status") or "CREATED"),
            paypal_order_id=paypal_order_id,
            paypal_capture_id=order.paypal_capture_id,
            paypal_approval_url=approval_url,
            paypal_payload=response,
        )

    async def capture_paypal_checkout(
        self,
        bot: "SalesBot",
        order_id: int,
        *,
        paypal_order_id: str | None = None,
    ) -> CheckoutOrderRecord:
        order = await self.get_checkout_order(order_id)
        if order.payment_method != "paypal":
            raise PermissionDeniedError("ההזמנה הזאת לא נפתחה במסלול PayPal.")
        if order.status == "completed":
            return order

        target_paypal_order_id = (paypal_order_id or order.paypal_order_id or "").strip()
        if not target_paypal_order_id:
            raise PermissionDeniedError("חסר מזהה PayPal להזמנה הזאת.")
        if order.paypal_order_id and order.paypal_order_id != target_paypal_order_id:
            raise PermissionDeniedError("מזהה ה-PayPal שחזר לא תואם להזמנה המקומית.")

        access_token = await self._paypal_access_token(bot)
        response = await self._paypal_request_json(
            bot,
            "POST",
            f"/v2/checkout/orders/{target_paypal_order_id}/capture",
            access_token=access_token,
            json_body={},
        )
        capture_id = self._extract_paypal_capture_id(response)
        paypal_status = str(response.get("status") or "").upper() or "COMPLETED"

        was_completed = order.status == "completed"
        await self._store_paypal_state(
            order.id,
            paypal_status=paypal_status,
            paypal_order_id=target_paypal_order_id,
            paypal_capture_id=capture_id,
            paypal_approval_url=order.paypal_approval_url,
            paypal_payload=response,
        )
        if paypal_status != "COMPLETED":
            raise ExternalServiceError("PayPal החזיר תגובה לא סופית. נסה שוב בעוד רגע או בדוק את סטטוס ההזמנה.")

        if not was_completed:
            order = await self.complete_checkout_order(bot, order.id, reviewer_id=None)
            await self._notify_checkout_paid(bot, order)
        return await self.get_checkout_order(order.id)

    async def process_paypal_webhook(
        self,
        bot: "SalesBot",
        headers: Mapping[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not await self._verify_paypal_webhook(bot, headers, payload):
            raise PermissionDeniedError("אימות ה-Webhook של PayPal נכשל.")

        event_type = str(payload.get("event_type") or "").upper()
        order = await self._find_checkout_order_from_paypal_payload(payload)
        if order is None:
            return {"handled": False, "event_type": event_type, "reason": "no-matching-order"}

        paypal_order_id = self._extract_paypal_order_id(payload) or order.paypal_order_id
        paypal_capture_id = self._extract_paypal_capture_id(payload) or order.paypal_capture_id
        resource = payload.get("resource") if isinstance(payload.get("resource"), dict) else {}
        paypal_status = str(resource.get("status") or "").upper() or event_type

        if event_type == "CHECKOUT.ORDER.APPROVED":
            await self._store_paypal_state(
                order.id,
                paypal_status=paypal_status,
                paypal_order_id=paypal_order_id,
                paypal_capture_id=paypal_capture_id,
                paypal_approval_url=order.paypal_approval_url,
                paypal_payload=payload,
            )
            return {"handled": True, "event_type": event_type, "order_id": order.id}

        if event_type == "PAYMENT.CAPTURE.COMPLETED":
            was_completed = order.status == "completed"
            await self._store_paypal_state(
                order.id,
                paypal_status="COMPLETED",
                paypal_order_id=paypal_order_id,
                paypal_capture_id=paypal_capture_id,
                paypal_approval_url=order.paypal_approval_url,
                paypal_payload=payload,
            )
            if not was_completed:
                order = await self.complete_checkout_order(bot, order.id, reviewer_id=None)
                await self._notify_checkout_paid(bot, order)
            return {"handled": True, "event_type": event_type, "order_id": order.id}

        if event_type in {"PAYMENT.CAPTURE.DENIED", "PAYMENT.CAPTURE.DECLINED", "PAYMENT.CAPTURE.REFUNDED", "CHECKOUT.ORDER.VOIDED"}:
            await self._store_paypal_state(
                order.id,
                paypal_status=paypal_status,
                paypal_order_id=paypal_order_id,
                paypal_capture_id=paypal_capture_id,
                paypal_approval_url=order.paypal_approval_url,
                paypal_payload=payload,
            )
            return {"handled": True, "event_type": event_type, "order_id": order.id}

        return {"handled": False, "event_type": event_type, "reason": "ignored"}

    async def mark_paypal_checkout_cancelled(self, order_id: int, reason: str) -> CheckoutOrderRecord:
        order = await self.get_checkout_order(order_id)
        if order.payment_method != "paypal":
            raise PermissionDeniedError("ההזמנה הזאת לא נפתחה במסלול PayPal.")
        if order.status == "completed":
            return order
        if order.status == "cancelled":
            return order
        await self._store_paypal_state(
            order.id,
            paypal_status="CANCELLED",
            paypal_order_id=order.paypal_order_id,
            paypal_capture_id=order.paypal_capture_id,
            paypal_approval_url=order.paypal_approval_url,
            paypal_payload={"cancel_reason": reason},
        )
        if order.status == "pending":
            return await self.cancel_checkout_order(order.id, reviewer_id=None, reason=reason)
        return await self.get_checkout_order(order.id)

    async def complete_checkout_order(self, bot: "SalesBot", order_id: int, reviewer_id: int | None) -> CheckoutOrderRecord:
        order = await self.get_checkout_order(order_id)
        if order.status == "completed":
            return order
        if order.status != "pending":
            raise PermissionDeniedError("אפשר להשלים רק הזמנות שעדיין ממתינות לאישור.")

        user = bot.get_user(order.user_id) or await bot.fetch_user(order.user_id)
        items = await self.list_checkout_order_items(order.id)
        for item in items:
            if await bot.services.ownership.user_owns_system(order.user_id, item.system_id):
                continue
            system = await bot.services.systems.get_system(item.system_id)
            await bot.services.delivery.deliver_system(
                bot,
                user,
                system,
                source=f"checkout:{order.id}",
                granted_by=reviewer_id,
            )

        await self.database.execute(
            """
            UPDATE website_checkout_orders
            SET status = 'completed', reviewed_at = CURRENT_TIMESTAMP, reviewed_by = ?, completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (reviewer_id, order.id),
        )
        return await self.get_checkout_order(order.id)

    async def cancel_checkout_order(self, order_id: int, reviewer_id: int | None, reason: str | None) -> CheckoutOrderRecord:
        order = await self.get_checkout_order(order_id)
        if order.status == "cancelled":
            return order
        if order.status != "pending":
            raise PermissionDeniedError("אפשר לבטל רק הזמנות שעדיין ממתינות לטיפול.")

        await self.database.execute(
            """
            UPDATE website_checkout_orders
            SET status = 'cancelled', reviewed_at = CURRENT_TIMESTAMP, reviewed_by = ?, cancelled_at = CURRENT_TIMESTAMP, cancel_reason = ?
            WHERE id = ?
            """,
            (reviewer_id, reason.strip() if reason else None, order.id),
        )
        await self.database.execute("DELETE FROM discount_code_redemptions WHERE order_id = ?", (order.id,))
        return await self.get_checkout_order(order.id)

    async def _paypal_access_token(self, bot: "SalesBot") -> str:
        if not bot.settings.paypal_checkout_enabled:
            raise ConfigurationError("PayPal checkout is not configured. Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET first.")
        if bot.http_session is None:
            raise ExternalServiceError("HTTP session is not ready for PayPal requests.")

        async with bot.http_session.post(
            f"{bot.settings.paypal_api_base_url}/v1/oauth2/token",
            data={"grant_type": "client_credentials"},
            auth=aiohttp.BasicAuth(bot.settings.paypal_client_id or "", bot.settings.paypal_client_secret or ""),
            headers={
                "Accept": "application/json",
                "Accept-Language": "en_US",
            },
        ) as response:
            raw_body = await response.text()
            if response.status >= 400:
                raise ExternalServiceError(f"PayPal access token request failed: HTTP {response.status} {raw_body[:300]}")
            data = json.loads(raw_body or "{}")
            access_token = str(data.get("access_token") or "").strip()
            if not access_token:
                raise ExternalServiceError("PayPal did not return an access token.")
            return access_token

    async def _paypal_request_json(
        self,
        bot: "SalesBot",
        method: str,
        path: str,
        *,
        access_token: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if bot.http_session is None:
            raise ExternalServiceError("HTTP session is not ready for PayPal requests.")

        async with bot.http_session.request(
            method,
            f"{bot.settings.paypal_api_base_url}{path}",
            json=json_body,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        ) as response:
            raw_body = await response.text()
            if response.status >= 400:
                raise ExternalServiceError(f"PayPal request failed: HTTP {response.status} {raw_body[:400]}")
            try:
                return json.loads(raw_body or "{}")
            except json.JSONDecodeError as exc:
                raise ExternalServiceError("PayPal returned an invalid JSON response.") from exc

    async def _verify_paypal_webhook(
        self,
        bot: "SalesBot",
        headers: Mapping[str, str],
        payload: dict[str, Any],
    ) -> bool:
        if not bot.settings.paypal_webhook_id:
            raise ConfigurationError("PAYPAL_WEBHOOK_ID is required to verify real PayPal webhooks.")

        required_headers = {
            "PAYPAL-AUTH-ALGO": headers.get("PAYPAL-AUTH-ALGO", ""),
            "PAYPAL-CERT-URL": headers.get("PAYPAL-CERT-URL", ""),
            "PAYPAL-TRANSMISSION-ID": headers.get("PAYPAL-TRANSMISSION-ID", ""),
            "PAYPAL-TRANSMISSION-SIG": headers.get("PAYPAL-TRANSMISSION-SIG", ""),
            "PAYPAL-TRANSMISSION-TIME": headers.get("PAYPAL-TRANSMISSION-TIME", ""),
        }
        if any(not value for value in required_headers.values()):
            raise PermissionDeniedError("Missing required PayPal webhook headers.")

        access_token = await self._paypal_access_token(bot)
        verification_payload = {
            "auth_algo": required_headers["PAYPAL-AUTH-ALGO"],
            "cert_url": required_headers["PAYPAL-CERT-URL"],
            "transmission_id": required_headers["PAYPAL-TRANSMISSION-ID"],
            "transmission_sig": required_headers["PAYPAL-TRANSMISSION-SIG"],
            "transmission_time": required_headers["PAYPAL-TRANSMISSION-TIME"],
            "webhook_id": bot.settings.paypal_webhook_id,
            "webhook_event": payload,
        }
        response = await self._paypal_request_json(
            bot,
            "POST",
            "/v1/notifications/verify-webhook-signature",
            access_token=access_token,
            json_body=verification_payload,
        )
        return str(response.get("verification_status") or "").upper() == "SUCCESS"

    async def _store_paypal_state(
        self,
        order_id: int,
        *,
        paypal_status: str,
        paypal_order_id: str | None,
        paypal_capture_id: str | None,
        paypal_approval_url: str | None,
        paypal_payload: dict[str, Any] | None,
    ) -> CheckoutOrderRecord:
        await self.database.execute(
            """
            UPDATE website_checkout_orders
            SET paypal_status = ?,
                paypal_order_id = ?,
                paypal_capture_id = ?,
                paypal_approval_url = ?,
                paypal_payload_json = ?
            WHERE id = ?
            """,
            (
                paypal_status.strip().upper() if paypal_status else "NOT-STARTED",
                paypal_order_id.strip() if paypal_order_id else None,
                paypal_capture_id.strip() if paypal_capture_id else None,
                paypal_approval_url.strip() if paypal_approval_url else None,
                json.dumps(paypal_payload) if paypal_payload is not None else None,
                order_id,
            ),
        )
        return await self.get_checkout_order(order_id)

    def _paypal_order_payload(
        self,
        bot: "SalesBot",
        order: CheckoutOrderRecord,
        items: list[CheckoutOrderItemRecord],
    ) -> dict[str, Any]:
        item_summary = ", ".join(item.system_name for item in items[:3])
        if len(items) > 3:
            item_summary = f"{item_summary} +{len(items) - 3} נוספים"
        description = f"Magic Studio's checkout #{order.id} - {item_summary}"[:127]
        return {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": f"checkout-{order.id}",
                    "custom_id": str(order.id),
                    "invoice_id": f"checkout-{order.id}",
                    "description": description,
                    "amount": {
                        "currency_code": order.currency.upper(),
                        "value": order.total_amount,
                    },
                }
            ],
            "application_context": {
                "brand_name": "Magic Studio's",
                "landing_page": "LOGIN",
                "user_action": "PAY_NOW",
                "shipping_preference": "NO_SHIPPING",
                "locale": "he-IL",
                "return_url": f"{bot.settings.public_base_url}/checkout/paypal/return?order_id={order.id}",
                "cancel_url": f"{bot.settings.public_base_url}/checkout/paypal/cancel?order_id={order.id}",
            },
        }

    @staticmethod
    def _extract_paypal_order_id(payload: dict[str, Any]) -> str | None:
        direct_id = str(payload.get("id") or "").strip()
        if direct_id:
            return direct_id
        resource = payload.get("resource") if isinstance(payload.get("resource"), dict) else {}
        related_ids = resource.get("supplementary_data", {}).get("related_ids", {}) if isinstance(resource, dict) else {}
        related_order_id = str(related_ids.get("order_id") or "").strip()
        if related_order_id:
            return related_order_id
        resource_id = str(resource.get("id") or "").strip() if isinstance(resource, dict) else ""
        event_type = str(payload.get("event_type") or "").upper()
        if resource_id and event_type.startswith("CHECKOUT.ORDER"):
            return resource_id
        return None

    @staticmethod
    def _extract_paypal_approval_url(payload: dict[str, Any]) -> str | None:
        links = payload.get("links") if isinstance(payload.get("links"), list) else []
        for link in links:
            if not isinstance(link, dict):
                continue
            if str(link.get("rel") or "").lower() == "approve":
                href = str(link.get("href") or "").strip()
                if href:
                    return href
        return None

    @staticmethod
    def _extract_paypal_capture_id(payload: dict[str, Any]) -> str | None:
        event_type = str(payload.get("event_type") or "").upper()
        resource = payload.get("resource") if isinstance(payload.get("resource"), dict) else {}
        if resource and event_type.startswith("PAYMENT.CAPTURE"):
            capture_id = str(resource.get("id") or "").strip()
            if capture_id:
                return capture_id
        purchase_units = payload.get("purchase_units") if isinstance(payload.get("purchase_units"), list) else []
        for unit in purchase_units:
            if not isinstance(unit, dict):
                continue
            captures = unit.get("payments", {}).get("captures", [])
            if not isinstance(captures, list):
                continue
            for capture in captures:
                if not isinstance(capture, dict):
                    continue
                capture_id = str(capture.get("id") or "").strip()
                if capture_id:
                    return capture_id
        return None

    async def _find_checkout_order_from_paypal_payload(self, payload: dict[str, Any]) -> CheckoutOrderRecord | None:
        paypal_order_id = self._extract_paypal_order_id(payload)
        if paypal_order_id:
            try:
                return await self.get_checkout_order_by_paypal_order_id(paypal_order_id)
            except NotFoundError:
                pass

        resource = payload.get("resource") if isinstance(payload.get("resource"), dict) else {}
        purchase_units = resource.get("purchase_units") if isinstance(resource, dict) and isinstance(resource.get("purchase_units"), list) else []
        custom_id = str(resource.get("custom_id") or "").strip() if isinstance(resource, dict) else ""
        if not custom_id and purchase_units:
            first_unit = purchase_units[0] if isinstance(purchase_units[0], dict) else {}
            custom_id = str(first_unit.get("custom_id") or "").strip()
        if custom_id.isdigit():
            try:
                return await self.get_checkout_order(int(custom_id))
            except NotFoundError:
                return None
        return None

    async def _notify_checkout_paid(self, bot: "SalesBot", order: CheckoutOrderRecord) -> None:
        message = (
            f"תשלום PayPal עבור הזמנה #{order.id} התקבל בהצלחה. "
            f"המערכות נמסרו, והסטטוס נשמר במרכז ההתראות שלך."
        )
        await bot.services.notifications.create_notification(
            user_id=order.user_id,
            title=f"PayPal הזמנה #{order.id} הושלמה",
            body=message,
            link_path="/inbox",
            kind="checkout",
        )
        try:
            user = bot.get_user(order.user_id) or await bot.fetch_user(order.user_id)
            dm_channel = user.dm_channel or await user.create_dm()
            await dm_channel.send(
                f"**PayPal הזמנה #{order.id} הושלמה**\n{message}\n{bot.settings.public_base_url}/inbox"
            )
        except (discord.Forbidden, discord.HTTPException):
            return

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

    @staticmethod
    def _map_checkout_order(row: aiosqlite.Row) -> CheckoutOrderRecord:
        return CheckoutOrderRecord(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            payment_method=str(row["payment_method"]),
            status=str(row["status"]),
            paypal_status=str(row["paypal_status"] or "not-started"),
            paypal_order_id=str(row["paypal_order_id"]) if row["paypal_order_id"] else None,
            paypal_capture_id=str(row["paypal_capture_id"]) if row["paypal_capture_id"] else None,
            paypal_approval_url=str(row["paypal_approval_url"]) if row["paypal_approval_url"] else None,
            paypal_payload_json=str(row["paypal_payload_json"]) if row["paypal_payload_json"] else None,
            discount_code_id=int(row["discount_code_id"]) if row["discount_code_id"] is not None else None,
            discount_code_text=str(row["discount_code_text"]) if row["discount_code_text"] else None,
            subtotal_amount=str(row["subtotal_amount"]),
            discount_amount=str(row["discount_amount"]),
            total_amount=str(row["total_amount"]),
            currency=str(row["currency"]),
            note=str(row["note"]) if row["note"] else None,
            reviewed_at=str(row["reviewed_at"]) if row["reviewed_at"] else None,
            reviewed_by=int(row["reviewed_by"]) if row["reviewed_by"] is not None else None,
            completed_at=str(row["completed_at"]) if row["completed_at"] else None,
            cancelled_at=str(row["cancelled_at"]) if row["cancelled_at"] else None,
            cancel_reason=str(row["cancel_reason"]) if row["cancel_reason"] else None,
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _map_checkout_item(row: aiosqlite.Row) -> CheckoutOrderItemRecord:
        return CheckoutOrderItemRecord(
            order_id=int(row["order_id"]),
            system_id=int(row["system_id"]),
            system_name=str(row["system_name"]),
            unit_price=str(row["unit_price"]),
            line_total=str(row["line_total"]),
        )
