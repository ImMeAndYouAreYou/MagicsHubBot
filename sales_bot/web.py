from __future__ import annotations

import html
import logging
from typing import TYPE_CHECKING, Any

from aiohttp import web

from sales_bot.exceptions import ConfigurationError, ExternalServiceError, NotFoundError, PermissionDeniedError
from sales_bot.web_admin import (
    admin_html_response,
    event_create_page,
    event_edit_page,
    giveaway_create_page,
    giveaway_edit_page,
    poll_create_page,
    poll_edit_page,
    system_edit_page,
)
from sales_bot.web_portal import (
    CUSTOM_ORDER_FORM_MAX_BYTES,
    account_payment_page,
    admin_admins_page,
    admin_blacklist_page,
    admin_checkout_orders_page,
    admin_dashboard_page,
    admin_discount_codes_page,
    admin_redeem_codes_page,
    admin_gamepasses_page,
    admin_notifications_page,
    admin_settings_page,
    admin_systems_page,
    blacklist_appeal_page,
    custom_order_image_page,
    custom_order_detail_page,
    custom_orders_list_page,
    custom_orders_page,
    owned_system_download_page,
    public_system_detail_page,
    public_systems_page,
    special_order_detail_page,
    special_orders_list_page,
    special_systems_page,
    special_system_compose_page,
    special_system_edit_page,
    special_system_image_page,
    special_system_page,
    system_gallery_image_page,
    system_image_page,
    website_cart_page,
    website_checkout_page,
    website_home_page,
    website_info_page,
    website_inbox_page,
    website_redeem_page,
    website_callback,
    website_login,
    website_logout,
    website_paypal_cancel_page,
    website_paypal_purchase_page,
    website_paypal_return_page,
    website_profile_page,
    website_vouches_page,
)

if TYPE_CHECKING:
    from sales_bot.bot import SalesBot


LOGGER = logging.getLogger(__name__)


def create_web_app(bot: "SalesBot") -> web.Application:
    app = web.Application(client_max_size=CUSTOM_ORDER_FORM_MAX_BYTES)
    app["bot"] = bot
    app.router.add_get("/", website_home_page)
    app.router.add_get("/info", website_info_page)
    app.router.add_get("/privacy", privacy_page)
    app.router.add_get("/terms", terms_page)
    app.router.add_get("/health", healthcheck)
    app.router.add_get("/auth/discord/login", website_login)
    app.router.add_get("/auth/discord/callback", website_callback)
    app.router.add_get("/auth/logout", website_logout)
    app.router.add_route("*", "/cart", website_cart_page)
    app.router.add_route("*", "/checkout", website_checkout_page)
    app.router.add_get("/checkout/paypal/return", website_paypal_return_page)
    app.router.add_get("/checkout/paypal/cancel", website_paypal_cancel_page)
    app.router.add_route("*", "/inbox", website_inbox_page)
    app.router.add_route("*", "/redeem", website_redeem_page)
    app.router.add_route("*", "/profile", website_profile_page)
    app.router.add_route("*", "/vouches", website_vouches_page)
    app.router.add_get("/systems", public_systems_page)
    app.router.add_get("/systems/{system_id:\\d+}", public_system_detail_page)
    app.router.add_get("/systems/{system_id:\\d+}/buy/paypal", website_paypal_purchase_page)
    app.router.add_get("/system-images/{system_id:\\d+}", system_image_page)
    app.router.add_get("/system-gallery-images/{image_id:\\d+}", system_gallery_image_page)
    app.router.add_get("/downloads/{system_id:\\d+}", owned_system_download_page)
    app.router.add_get("/special-systems", special_systems_page)
    app.router.add_route("*", "/blacklist-appeal", blacklist_appeal_page)
    app.router.add_post("/api/roblox/game/bootstrap", roblox_game_bootstrap)
    app.router.add_get("/oauth/roblox/callback", roblox_callback)
    app.router.add_get("/oauth/roblox/owner/callback", roblox_owner_callback)
    app.router.add_post("/webhooks/paypal/simulate", paypal_webhook)
    app.router.add_post("/webhooks/paypal", paypal_webhook)
    app.router.add_post("/webhooks/roblox/gamepass", roblox_gamepass_webhook)
    app.router.add_get("/admin", admin_dashboard_page)
    app.router.add_route("*", "/admin/admins", admin_admins_page)
    app.router.add_route("*", "/admin/blacklist", admin_blacklist_page)
    app.router.add_route("*", "/admin/checkouts", admin_checkout_orders_page)
    app.router.add_route("*", "/admin/custom-orders", custom_orders_list_page)
    app.router.add_route("*", "/admin/custom-orders/{order_id:\\d+}", custom_order_detail_page)
    app.router.add_get("/admin/custom-order-images/{image_id:\\d+}", custom_order_image_page)
    app.router.add_route("*", "/admin/discount-codes", admin_discount_codes_page)
    app.router.add_route("*", "/admin/redeem-codes", admin_redeem_codes_page)
    app.router.add_route("*", "/admin/systems", admin_systems_page)
    app.router.add_route("*", "/admin/gamepasses", admin_gamepasses_page)
    app.router.add_route("*", "/admin/notifications", admin_notifications_page)
    app.router.add_route("*", "/admin/settings", admin_settings_page)
    app.router.add_route("*", "/admin/special-systems", special_system_compose_page)
    app.router.add_route("*", "/admin/special-systems/{special_system_id:\\d+}/edit", special_system_edit_page)
    app.router.add_route("*", "/admin/special-orders", special_orders_list_page)
    app.router.add_route("*", "/admin/special-orders/{order_id:\\d+}", special_order_detail_page)
    app.router.add_route("*", "/admin/polls/new", poll_create_page)
    app.router.add_route("*", "/admin/polls/{poll_id:\\d+}/edit", poll_edit_page)
    app.router.add_route("*", "/admin/giveaways/new", giveaway_create_page)
    app.router.add_route("*", "/admin/giveaways/{giveaway_id:\\d+}/edit", giveaway_edit_page)
    app.router.add_route("*", "/admin/events/new", event_create_page)
    app.router.add_route("*", "/admin/events/{event_id:\\d+}/edit", event_edit_page)
    app.router.add_route("*", "/admin/systems/{system_id:\\d+}/edit", system_edit_page)
    app.router.add_get("/special-system-images/{image_id:\\d+}", special_system_image_page)
    app.router.add_route("*", "/account-payment", account_payment_page)
    app.router.add_route("*", "/custom-orders", custom_orders_page)
    app.router.add_route("*", "/special-systems/{slug}", special_system_page)
    return app


def html_response(title: str, body: str) -> web.Response:
    return admin_html_response(title, body)


def _roblox_request_token(request: web.Request) -> str:
    return request.headers.get("X-Roblox-Webhook-Token", "") or request.headers.get("X-Webhook-Token", "")


def _authorize_roblox_request(bot: "SalesBot", request: web.Request) -> web.Response | None:
    expected_token = bot.settings.roblox_gamepass_webhook_token or ""
    provided_token = _roblox_request_token(request)
    if not expected_token:
        return web.json_response({"error": "webhook not configured"}, status=503)
    if provided_token != expected_token:
        return web.json_response({"error": "unauthorized"}, status=401)
    return None


def _payload_string(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


async def _resolve_roblox_owner_context(bot: "SalesBot") -> tuple[int, int]:
    if bot.settings.primary_guild_id is not None:
        record = await bot.services.roblox_creator.get_link(bot.settings.primary_guild_id)
        return bot.settings.primary_guild_id, record.discord_user_id

    row = await bot.database.fetchone(
        "SELECT guild_id, discord_user_id FROM roblox_owner_links ORDER BY linked_at DESC LIMIT 1"
    )
    if row is None:
        raise NotFoundError("No Roblox owner access is linked yet.")

    return int(row["guild_id"]), int(row["discord_user_id"])


async def _resolve_connected_account_label(bot: "SalesBot", discord_user_id: int) -> str:
    user = bot.get_user(discord_user_id)
    if user is None:
        try:
            user = await bot.fetch_user(discord_user_id)
        except Exception:
            return str(discord_user_id)

    username = str(getattr(user, "name", "") or "").strip()
    global_name = str(getattr(user, "global_name", "") or "").strip()
    if global_name and username and global_name.casefold() != username.casefold():
        return f"{global_name} (@{username})"
    if username:
        return f"@{username}"
    if global_name:
        return global_name
    return str(discord_user_id)


async def _build_roblox_catalog(bot: "SalesBot") -> tuple[list[dict[str, Any]], str]:
    systems = await bot.services.systems.list_robux_enabled_systems()
    remote_gamepasses_by_id: dict[str, Any] = {}
    display_name_overrides = await bot.services.systems.list_gamepass_display_names(
        [str(system.roblox_gamepass_id) for system in systems if system.roblox_gamepass_id]
    )
    catalog_source = "database"

    if bot.settings.roblox_owner_gamepass_management_enabled:
        try:
            guild_id, discord_user_id = await _resolve_roblox_owner_context(bot)
            remote_gamepasses = await bot.services.roblox_creator.list_gamepasses(bot, guild_id, discord_user_id)
            remote_gamepasses_by_id = {
                str(gamepass.game_pass_id): gamepass for gamepass in remote_gamepasses
            }
            catalog_source = "roblox+database"
        except (NotFoundError, ExternalServiceError, PermissionDeniedError) as exc:
            LOGGER.warning("Roblox catalog sync fell back to database-only data: %s", exc)

    catalog: list[dict[str, Any]] = []
    for system in systems:
        gamepass_id = str(system.roblox_gamepass_id or "").strip()
        if not gamepass_id:
            continue

        remote_gamepass = remote_gamepasses_by_id.get(gamepass_id)
        icon_asset_id = remote_gamepass.icon_asset_id if remote_gamepass is not None else None
        thumbnail = ""
        if icon_asset_id is not None:
            thumbnail = f"rbxthumb://type=Asset&id={icon_asset_id}&w=420&h=420"

        title = display_name_overrides.get(gamepass_id) or system.name
        description = system.description
        price_in_robux: int | None = None
        is_for_sale = True
        if remote_gamepass is not None:
            if not display_name_overrides.get(gamepass_id):
                title = remote_gamepass.name or title
            description = remote_gamepass.description or description
            price_in_robux = remote_gamepass.price_in_robux
            is_for_sale = remote_gamepass.is_for_sale

        catalog.append(
            {
                "system_id": system.id,
                "system_name": system.name,
                "title": title,
                "description": description,
                "gamepass_id": int(gamepass_id),
                "price": price_in_robux,
                "price_in_robux": price_in_robux,
                "icon_asset_id": icon_asset_id,
                "thumbnail": thumbnail,
                "is_for_sale": is_for_sale,
                "purchase_url": bot.services.roblox_creator.gamepass_url(int(gamepass_id)),
            }
        )

    catalog.sort(key=lambda item: (str(item["title"]).lower(), int(item["gamepass_id"])))
    return catalog, catalog_source


async def roblox_game_bootstrap(request: web.Request) -> web.Response:
    bot: SalesBot = request.app["bot"]
    authorization_error = _authorize_roblox_request(bot, request)
    if authorization_error is not None:
        return authorization_error

    try:
        payload = await request.json()
    except ValueError:
        return web.json_response({"error": "invalid json"}, status=400)

    if not isinstance(payload, dict):
        return web.json_response({"error": "invalid payload"}, status=400)

    roblox_user_id = _payload_string(
        payload,
        "roblox_user_id",
        "robloxUserId",
        "player_user_id",
        "playerUserId",
        "user_id",
        "userId",
    )
    if not roblox_user_id.isdigit():
        return web.json_response({"error": "invalid payload"}, status=400)

    player_payload: dict[str, Any] = {
        "roblox_user_id": int(roblox_user_id),
        "is_linked": False,
        "discord_user_id": None,
        "connected_account": "",
    }
    try:
        link = await bot.services.oauth.get_link_by_roblox_sub(roblox_user_id)
    except NotFoundError:
        pass
    except ExternalServiceError as exc:
        return web.json_response({"error": str(exc)}, status=409)
    else:
        player_payload.update(
            {
                "is_linked": True,
                "discord_user_id": link.user_id,
                "connected_account": await _resolve_connected_account_label(bot, link.user_id),
            }
        )

    catalog, catalog_source = await _build_roblox_catalog(bot)
    return web.json_response(
        {
            "player": player_payload,
            "catalog": catalog,
            "catalog_source": catalog_source,
        }
    )


async def landing_page(request: web.Request) -> web.Response:
    bot: SalesBot = request.app["bot"]
    base_url = html.escape(bot.settings.public_base_url)
    body = f"""
    <div class="marketing-shell" dir="ltr">
        <div class="marketing-hero">
            <p class="eyebrow">Magic Studio's Website</p>
            <h1>Magic Systems Hub Bot</h1>
            <p>Discord automation, order handling, account linking, and delivery flows presented in one shared web shell.</p>
        </div>
        <div class="doc-grid">
            <article class="doc-card copy-stack">
                <h2>What this website handles</h2>
                <ul class="doc-list">
                    <li>System sales and delivery flows managed through Discord and the website panels.</li>
                    <li>Roblox OAuth linking and owner flows tied back to your Discord identity.</li>
                    <li>Purchase follow-up pages, admin dashboards, and connected account actions.</li>
                </ul>
            </article>
            <article class="doc-card copy-stack">
                <h2>Need to link Roblox?</h2>
                <p>Return to Discord and use the bot's <strong>/link</strong> command, then finish the authorization flow in your browser.</p>
                <div class="inline-link-grid">
                    <a class="link-button" href="{base_url}/privacy">Privacy Policy</a>
                    <a class="link-button ghost-button" href="{base_url}/terms">Terms of Service</a>
                </div>
            </article>
        </div>
    </div>
    """
    return html_response("Magic Systems Hub Bot", body)


async def privacy_page(request: web.Request) -> web.Response:
    body = """
    <div class="marketing-shell" dir="rtl">
        <div class="marketing-hero">
            <p class="eyebrow">מידע משפטי</p>
            <h1>מדיניות פרטיות</h1>
            <p>Magic Studio's שומר רק את המידע התפעולי שנדרש להפעלת השירות, הרכישות ומסירת המערכות.</p>
        </div>
        <div class="marketing-panel copy-stack">
            <ul class="doc-list">
                <li>ייתכן שיישמרו מזהי משתמש של דיסקורד, רשומות בעלות, נתוני תמיכה, בלאקליסט ודירוגים לצורך תפעול השירות.</li>
                <li>אם חיבור רובלוקס פעיל, ייתכן שיישמרו גם פרטי הזיהוי הציבוריים שמוחזרים על ידי רובלוקס.</li>
                <li>קבצי מערכות נשמרים רק לצורך מסירה לרוכשים מורשים או לצוות מאושר.</li>
                <li>המידע משמש רק להפעלת הבוט, המעקב אחרי רכישות ומסירות, וניהול גישה.</li>
                <li>לא נשתף פרטי גישה בכוונה עם צד שלישי, חוץ מחיבורים שנדרשים על ידי ספקי תשלום או OAuth.</li>
            </ul>
            <p>השימוש בשירות מהווה הסכמה לעיבוד המידע התפעולי הזה לצורך ניהול השרת והשלמת הרכישות.</p>
        </div>
    </div>
    """
    return html_response("מדיניות פרטיות", body)


async def terms_page(request: web.Request) -> web.Response:
    body = """
    <div class="marketing-shell" dir="rtl">
        <div class="marketing-hero">
            <p class="eyebrow">מידע משפטי</p>
            <h1>תנאי שימוש</h1>
            <p>התנאים האלה מתארים את אופן השימוש באתר, בבוט ובחיבורי החשבון השונים.</p>
        </div>
        <div class="marketing-panel copy-stack">
            <ul class="doc-list">
                <li>השימוש ב-Magic Studio's מיועד לחברי שרת ולקוחות מורשים בלבד.</li>
                <li>ניסיון לנצל לרעה רכישות, פקודות, חיבורי חשבון או מערכות האתר עלול לגרום להסרת הגישה.</li>
                <li>מסירת מערכות דיגיטליות יכולה להתבצע בדיסקורד או דרך האתר, לפי תהליך העבודה שנקבע.</li>
                <li>הרכישות כפופות לכללי השרת, לבדיקת הצוות ולמדיניות החזר אם קיימת.</li>
                <li>חיבור חשבון רובלוקס מותר רק עבור חשבונות שבשליטת המשתמש.</li>
            </ul>
            <p>המשך שימוש בשירות אומר שאתה מסכים לתנאים האלה ולכללי השרת הנלווים.</p>
        </div>
    </div>
    """
    return html_response("תנאי שימוש", body)


async def healthcheck(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def roblox_callback(request: web.Request) -> web.Response:
    bot: SalesBot = request.app["bot"]
    if not bot.settings.roblox_oauth_enabled:
        return web.Response(text="Roblox OAuth is not configured for this deployment.", status=503)

    state = request.query.get("state", "")
    code = request.query.get("code", "")

    if not state or not code:
        return web.Response(text="Missing state or code.", status=400)

    try:
        user_id = await bot.services.oauth.consume_state(state)
        tokens = await bot.services.oauth.exchange_code(bot.http_session, code)
        profile = await bot.services.oauth.fetch_profile(bot.http_session, tokens["access_token"])
        record = await bot.services.oauth.link_account(user_id, profile)
        sync_notes = await bot.services.oauth.sync_linked_member(bot, user_id, record)

        user = await bot.fetch_user(user_id)
        success_message = f"חשבון הרובלוקס שלך קושר בהצלחה בתור **{record.roblox_username or record.roblox_sub}**."
        if sync_notes:
            success_message += "\n\n" + "\n".join(f"- {note}" for note in sync_notes)
        await user.send(
            success_message
        )
    except (NotFoundError, ExternalServiceError) as exc:
        LOGGER.warning("Roblox OAuth callback failed: %s", exc)
        return web.Response(text=f"הקישור נכשל: {exc}", status=400)
    except Exception:
        LOGGER.exception("Unexpected Roblox OAuth callback failure")
        return web.Response(text="אירעה שגיאת OAuth לא צפויה.", status=500)

    return web.Response(
        text="חשבון הרובלוקס קושר בהצלחה. אפשר לסגור את החלון.",
        content_type="text/plain",
    )


async def roblox_owner_callback(request: web.Request) -> web.Response:
    bot: SalesBot = request.app["bot"]
    if not bot.settings.roblox_owner_oauth_enabled:
        return web.Response(text="Roblox owner OAuth is not configured for this deployment.", status=503)

    state = request.query.get("state", "")
    code = request.query.get("code", "")

    if not state or not code:
        return web.Response(text="Missing state or code.", status=400)

    try:
        guild_id, discord_user_id = await bot.services.roblox_creator.consume_state(state)
        tokens = await bot.services.roblox_creator.exchange_code(bot.http_session, code)
        profile = await bot.services.roblox_creator.fetch_profile(bot.http_session, tokens["access_token"])
        record = await bot.services.roblox_creator.link_owner(guild_id, discord_user_id, profile, tokens)

        user = await bot.fetch_user(discord_user_id)
        await user.send(
            "Roblox owner access is now linked for your server. "
            f"Connected account: **{record.roblox_username or record.roblox_sub}**."
        )
    except (NotFoundError, ExternalServiceError) as exc:
        LOGGER.warning("Roblox owner OAuth callback failed: %s", exc)
        return web.Response(text=f"Owner linking failed: {exc}", status=400)
    except Exception:
        LOGGER.exception("Unexpected Roblox owner OAuth callback failure")
        return web.Response(text="An unexpected owner OAuth error occurred.", status=500)

    return web.Response(
        text="Roblox owner access linked successfully. You can return to Discord.",
        content_type="text/plain",
    )


async def paypal_webhook(request: web.Request) -> web.Response:
    bot: SalesBot = request.app["bot"]
    payload: dict[str, Any] = await request.json()
    if request.path.endswith("/simulate"):
        provided_token = request.headers.get("X-Webhook-Token", "")
        if not bot.settings.paypal_webhook_token:
            return web.json_response({"error": "simulation token not configured"}, status=503)
        if provided_token != bot.settings.paypal_webhook_token:
            return web.json_response({"error": "unauthorized"}, status=401)

        purchase_id = int(payload.get("purchase_id", 0))
        status = str(payload.get("status", "")).upper()

        if purchase_id <= 0 or status != "COMPLETED":
            return web.json_response({"error": "invalid payload"}, status=400)

        try:
            await bot.services.payments.complete_purchase(bot, purchase_id, payload)
        except NotFoundError as exc:
            return web.json_response({"error": str(exc)}, status=404)
        except Exception:
            LOGGER.exception("PayPal simulation webhook failed")
            return web.json_response({"error": "internal error"}, status=500)

        return web.json_response({"status": "completed", "purchase_id": purchase_id})

    try:
        result = await bot.services.payments.process_paypal_webhook(bot, request.headers, payload)
        return web.json_response(result, status=200 if result.get("handled") else 202)
    except ConfigurationError as exc:
        return web.json_response({"error": str(exc)}, status=503)
    except PermissionDeniedError as exc:
        return web.json_response({"error": str(exc)}, status=401)
    except NotFoundError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    except ExternalServiceError as exc:
        return web.json_response({"error": str(exc)}, status=502)
    except Exception:
        LOGGER.exception("PayPal webhook processing failed")
        return web.json_response({"error": "internal error"}, status=500)


async def roblox_gamepass_webhook(request: web.Request) -> web.Response:
    bot: SalesBot = request.app["bot"]
    authorization_error = _authorize_roblox_request(bot, request)
    if authorization_error is not None:
        return authorization_error

    payload: dict[str, Any] = await request.json()
    roblox_user_id = _payload_string(
        payload,
        "roblox_user_id",
        "robloxUserId",
        "player_user_id",
        "playerUserId",
        "user_id",
        "userId",
    )
    gamepass_id = _payload_string(
        payload,
        "gamepass_id",
        "gamePassId",
        "pass_id",
        "passId",
        "purchased_gamepass_id",
        "purchasedGamePassId",
    )

    if not roblox_user_id.isdigit() or not gamepass_id.isdigit():
        return web.json_response({"error": "invalid payload"}, status=400)

    try:
        system = await bot.services.systems.get_system_by_gamepass_id(gamepass_id)
    except NotFoundError as exc:
        return web.json_response({"error": str(exc)}, status=404)

    try:
        link = await bot.services.oauth.get_link_by_roblox_sub(roblox_user_id)
    except NotFoundError:
        return web.json_response(
            {
                "status": "accepted_unlinked",
                "message": "Purchase accepted, but no linked Discord user was found for this Roblox account yet.",
                "gamepass_id": gamepass_id,
            },
            status=202,
        )
    except ExternalServiceError as exc:
        return web.json_response({"error": str(exc)}, status=409)

    already_owned = await bot.services.ownership.user_owns_system(link.user_id, system.id)
    if already_owned:
        return web.json_response(
            {
                "status": "already_owned",
                "discord_user_id": link.user_id,
                "system_id": system.id,
                "gamepass_id": gamepass_id,
            }
        )

    try:
        user = await bot.fetch_user(link.user_id)
        await bot.services.delivery.deliver_system(
            bot,
            user,
            system,
            source=bot.services.ownership.ROBLOX_CLAIM_SOURCE,
            granted_by=None,
        )
        status = "delivered"
    except ExternalServiceError as exc:
        LOGGER.warning("Roblox webhook delivery DM failed for user %s: %s", link.user_id, exc)
        await bot.services.ownership.grant_system(
            link.user_id,
            system.id,
            None,
            bot.services.ownership.ROBLOX_CLAIM_SOURCE,
        )
        await bot.services.ownership.refresh_claim_role_membership(bot, link.user_id, sync_ownerships=False)
        status = "owned_no_dm"

    return web.json_response(
        {
            "status": status,
            "discord_user_id": link.user_id,
            "system_id": system.id,
            "gamepass_id": gamepass_id,
        }
    )
