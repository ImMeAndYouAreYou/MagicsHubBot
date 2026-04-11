from __future__ import annotations

import html
import logging
from typing import TYPE_CHECKING, Any

from aiohttp import web

from sales_bot.exceptions import ExternalServiceError, NotFoundError

if TYPE_CHECKING:
    from sales_bot.bot import SalesBot


LOGGER = logging.getLogger(__name__)


def create_web_app(bot: "SalesBot") -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/", landing_page)
    app.router.add_get("/privacy", privacy_page)
    app.router.add_get("/terms", terms_page)
    app.router.add_get("/health", healthcheck)
    app.router.add_get("/oauth/roblox/callback", roblox_callback)
    app.router.add_post("/webhooks/paypal/simulate", paypal_webhook)
    return app


def html_response(title: str, body: str) -> web.Response:
    content = f"""
    <!doctype html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>{html.escape(title)}</title>
        <style>
            :root {{
                color-scheme: dark;
                --bg: #111827;
                --card: #1f2937;
                --text: #f9fafb;
                --muted: #cbd5e1;
                --accent: #38bdf8;
            }}
            body {{
                margin: 0;
                font-family: Segoe UI, sans-serif;
                background: radial-gradient(circle at top, #1e293b 0%, var(--bg) 55%);
                color: var(--text);
            }}
            main {{
                max-width: 760px;
                margin: 0 auto;
                padding: 48px 20px 80px;
            }}
            section {{
                background: rgba(31, 41, 55, 0.95);
                border: 1px solid rgba(148, 163, 184, 0.2);
                border-radius: 18px;
                padding: 28px;
                box-shadow: 0 20px 60px rgba(0, 0, 0, 0.35);
            }}
            h1 {{
                margin-top: 0;
                font-size: 2rem;
            }}
            p, li {{
                line-height: 1.7;
                color: var(--muted);
            }}
            a {{
                color: var(--accent);
            }}
        </style>
    </head>
    <body>
        <main>
            <section>
                {body}
            </section>
        </main>
    </body>
    </html>
    """
    return web.Response(text=content, content_type="text/html")


async def landing_page(request: web.Request) -> web.Response:
    bot: SalesBot = request.app["bot"]
    base_url = html.escape(bot.settings.public_base_url)
    body = f"""
    <h1>Magic Systems Hub Bot</h1>
    <p>This service powers Discord automation for system sales, DM delivery, Roblox OAuth linking, and payment flows.</p>
    <p>If you are linking your Roblox account, return to Discord and use the bot's <strong>/link</strong> command.</p>
    <p>
        Privacy Policy: <a href="{base_url}/privacy">{base_url}/privacy</a><br>
        Terms of Service: <a href="{base_url}/terms">{base_url}/terms</a>
    </p>
    """
    return html_response("Magic Systems Hub Bot", body)


async def privacy_page(request: web.Request) -> web.Response:
    body = """
    <h1>Privacy Policy</h1>
    <p>Magic Systems Hub Bot stores only the data needed to operate its Discord server features.</p>
    <ul>
        <li>Discord user IDs, system ownership records, blacklist entries, vouch records, and support-related metadata may be stored.</li>
        <li>If Roblox OAuth is enabled, linked Roblox profile identifiers returned by Roblox may also be stored.</li>
        <li>Uploaded system files are stored only for delivery to authorized buyers or staff-approved recipients.</li>
        <li>Data is used strictly to provide bot features, payment handling flows, ownership tracking, and moderation actions.</li>
        <li>No credentials are intentionally shared with third parties except where required by Roblox OAuth or payment providers.</li>
    </ul>
    <p>By using the bot, you consent to this operational data processing for server management and purchase fulfillment.</p>
    """
    return html_response("Privacy Policy", body)


async def terms_page(request: web.Request) -> web.Response:
    body = """
    <h1>Terms of Service</h1>
    <ul>
        <li>Use of Magic Systems Hub Bot is limited to authorized server members and customers.</li>
        <li>Attempting to abuse commands, payment flows, blacklist systems, or account-linking features may result in removal of access.</li>
        <li>Digital system delivery is handled by Discord DM and may require open DMs or manual staff assistance.</li>
        <li>Purchases are subject to server staff review, moderation rules, and any published refund policy.</li>
        <li>Roblox account linking, if enabled, must be used only with accounts you control.</li>
    </ul>
    <p>Continued use of the bot means you agree to these terms and any related server rules.</p>
    """
    return html_response("Terms of Service", body)


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

        user = await bot.fetch_user(user_id)
        await user.send(
            f"חשבון הרובלוקס שלך קושר בהצלחה בתור **{record.roblox_username or record.roblox_sub}**."
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


async def paypal_webhook(request: web.Request) -> web.Response:
    bot: SalesBot = request.app["bot"]
    provided_token = request.headers.get("X-Webhook-Token", "")
    if provided_token != bot.settings.paypal_webhook_token:
        return web.json_response({"error": "unauthorized"}, status=401)

    payload: dict[str, Any] = await request.json()
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
