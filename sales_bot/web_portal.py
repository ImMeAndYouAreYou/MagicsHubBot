from __future__ import annotations

import asyncio
import logging
from io import BytesIO
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import discord
from aiohttp import web

from sales_bot.exceptions import (
    ConfigurationError,
    ExternalServiceError,
    NotFoundError,
    PermissionDeniedError,
    SalesBotError,
)
from sales_bot.models import (
    RobloxGamePassRecord,
    RobloxLinkRecord,
    SpecialOrderRequestRecord,
    SpecialSystemImageRecord,
    SpecialSystemRecord,
    SystemRecord,
    WebsiteSessionRecord,
)
from sales_bot.web_admin import (
    _error_response,
    _escape,
    _list_text_channels,
    _message_link,
    _render_channel_options,
    admin_html_response,
)

if TYPE_CHECKING:
    from sales_bot.bot import SalesBot


LOGGER = logging.getLogger(__name__)


PORTAL_STYLE = """
<style>
.portal-root { display: flex; flex-direction: column; gap: 18px; }
.top-strip { display: flex; justify-content: space-between; gap: 12px; align-items: center; flex-wrap: wrap; }
.user-chip { display: inline-flex; align-items: center; gap: 10px; padding: 10px 14px; border-radius: 999px; background: rgba(163, 190, 213, 0.12); border: 1px solid rgba(163, 190, 213, 0.18); }
.user-chip img { width: 34px; height: 34px; border-radius: 999px; object-fit: cover; }
.nav-links { display: flex; flex-wrap: wrap; gap: 10px; }
.nav-links a { padding: 10px 14px; border-radius: 999px; background: rgba(163, 190, 213, 0.12); border: 1px solid rgba(163, 190, 213, 0.18); text-decoration: none; color: var(--text); }
.hero-grid, .stat-grid, .split-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; }
.card { padding: 18px; border-radius: 18px; background: rgba(9, 21, 36, 0.78); border: 1px solid rgba(134, 167, 201, 0.15); }
.card h2, .card h3 { margin-top: 0; margin-bottom: 10px; }
.stat-value { font-size: 2rem; font-weight: 700; color: var(--text); }
.table-wrap { overflow-x: auto; border-radius: 18px; border: 1px solid rgba(134, 167, 201, 0.15); background: rgba(9, 21, 36, 0.78); }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 14px 16px; text-align: right; border-bottom: 1px solid rgba(134, 167, 201, 0.12); vertical-align: top; }
th { color: var(--text); font-size: 0.95rem; }
td strong { color: var(--text); }
.inline-form { display: inline-flex; gap: 10px; flex-wrap: wrap; align-items: center; margin: 0; }
.inline-form input, .inline-form select { width: auto; min-width: 120px; }
.stack { display: flex; flex-direction: column; gap: 14px; }
.badge { display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 999px; background: rgba(85, 214, 190, 0.12); border: 1px solid rgba(85, 214, 190, 0.22); color: #d9fff8; font-size: 0.9rem; }
.badge.pending { background: rgba(255, 215, 125, 0.12); border-color: rgba(255, 215, 125, 0.28); color: #ffe8ae; }
.badge.rejected { background: rgba(255, 133, 121, 0.12); border-color: rgba(255, 133, 121, 0.28); color: #ffd6d1; }
.price-list { display: flex; flex-direction: column; gap: 10px; }
.price-item { display: flex; justify-content: space-between; gap: 10px; padding: 12px 14px; border-radius: 14px; background: rgba(163, 190, 213, 0.08); border: 1px solid rgba(163, 190, 213, 0.12); }
.gallery { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; }
.gallery img { width: 100%; height: 180px; object-fit: cover; border-radius: 16px; border: 1px solid rgba(134, 167, 201, 0.16); }
.check-card { display: flex; flex-direction: column; gap: 10px; }
.check-line { display: flex; gap: 10px; align-items: center; color: var(--text); }
.check-line input { width: auto; }
.muted { color: var(--muted); }
.mono { font-family: Consolas, "Cascadia Mono", monospace; }
@media (max-width: 700px) {
    .top-strip { align-items: stretch; }
    .nav-links { width: 100%; }
    .nav-links a { flex: 1 1 auto; text-align: center; }
    .price-item { flex-direction: column; }
}
</style>
"""

ORDER_STATUS_LABELS = {
    "pending": "ממתינה",
    "accepted": "התקבלה",
    "rejected": "נדחתה",
}


def _page_response(title: str, body: str) -> web.Response:
    return admin_html_response(title, PORTAL_STYLE + body)


def _session_label(session: WebsiteSessionRecord) -> str:
    global_name = (session.global_name or "").strip()
    username = session.username.strip()
    if global_name and username and global_name.casefold() != username.casefold():
        return f"{global_name} (@{username})"
    return global_name or f"@{username}"


def _session_avatar(session: WebsiteSessionRecord) -> str | None:
    if not session.avatar_hash:
        return None
    return f"https://cdn.discordapp.com/avatars/{session.discord_user_id}/{session.avatar_hash}.png?size=256"


def _admin_shell(
    session: WebsiteSessionRecord,
    *,
    title: str,
    intro: str,
    content: str,
) -> str:
    avatar_url = _session_avatar(session)
    avatar_html = f'<img src="{_escape(avatar_url)}" alt="avatar">' if avatar_url else ""
    return f"""
    <div class="portal-root" dir="rtl">
        <div class="top-strip">
            <div class="user-chip">
                {avatar_html}
                <div>
                    <strong>{_escape(_session_label(session))}</strong><br>
                    <span class="muted mono">{_escape(session.discord_user_id)}</span>
                </div>
            </div>
            <div class="nav-links">
                <a href="/admin">לוח ניהול</a>
                <a href="/admin/admins">אדמינים</a>
                <a href="/admin/systems">מערכות</a>
                <a href="/admin/gamepasses">גיימפאסים</a>
                <a href="/admin/special-systems">מערכות מיוחדות</a>
                <a href="/admin/special-orders">בקשות מיוחדות</a>
                <a href="/admin/polls/new">סקרים</a>
                <a href="/admin/giveaways/new">הגרלות</a>
                <a href="/admin/events/new">אירועים</a>
                <a href="/auth/logout">התנתק</a>
            </div>
        </div>
        <p class="eyebrow">אתר ניהול</p>
        <h1>{_escape(title)}</h1>
        <p>{_escape(intro)}</p>
        {content}
    </div>
    """


def _public_shell(
    session: WebsiteSessionRecord | None,
    *,
    title: str,
    intro: str,
    login_path: str,
    content: str,
) -> str:
    account_block = ""
    if session is None:
        account_block = (
            f'<div class="actions"><a class="link-button" href="/auth/discord/login?next={_escape(login_path)}">'
            "התחברות עם Discord"
            "</a></div>"
        )
    else:
        account_block = f"""
        <div class="user-chip">
            <strong>{_escape(_session_label(session))}</strong>
            <span class="muted mono">{_escape(session.discord_user_id)}</span>
        </div>
        """
    return f"""
    <div class="portal-root" dir="rtl">
        <div class="top-strip">
            <div>
                <p class="eyebrow">מערכות מיוחדות</p>
                <h1>{_escape(title)}</h1>
                <p>{_escape(intro)}</p>
            </div>
            {account_block}
        </div>
        {content}
    </div>
    """


def _notice_html(message: str | None, *, success: bool) -> str:
    if not message:
        return ""
    classes = "notice success" if success else "notice"
    return f'<div class="{classes}">{_escape(message)}</div>'


def _status_badge(status: str) -> str:
    normalized = status.strip().lower()
    extra_class = " pending" if normalized == "pending" else " rejected" if normalized == "rejected" else ""
    return f'<span class="badge{extra_class}">{_escape(ORDER_STATUS_LABELS.get(normalized, normalized))}</span>'


def _redirect_to_login(request: web.Request) -> None:
    next_path = quote(request.path_qs or request.path, safe="/?=&%")
    raise web.HTTPFound(f"/auth/discord/login?next={next_path}")


async def _current_site_session(request: web.Request) -> tuple["SalesBot", WebsiteSessionRecord | None]:
    bot: SalesBot = request.app["bot"]
    token = request.cookies.get(bot.services.web_auth.cookie_name, "").strip()
    if not token:
        return bot, None
    try:
        session = await bot.services.web_auth.get_session(token)
    except SalesBotError:
        return bot, None
    except Exception:
        LOGGER.warning("Ignoring invalid website session cookie during request to %s", request.path, exc_info=True)
        return bot, None
    return bot, session


async def _require_site_session(request: web.Request) -> tuple["SalesBot", WebsiteSessionRecord]:
    bot, session = await _current_site_session(request)
    if session is None:
        _redirect_to_login(request)
    assert session is not None
    return bot, session


async def _require_admin_session(request: web.Request) -> tuple["SalesBot", WebsiteSessionRecord]:
    bot, session = await _require_site_session(request)
    if not await bot.services.admins.is_admin(session.discord_user_id):
        raise PermissionDeniedError("רק אדמינים של הבוט יכולים לפתוח את האתר הזה.")
    return bot, session


def _parse_positive_int(raw_value: Any, field_label: str, *, allow_blank: bool = False) -> int | None:
    value = str(raw_value or "").strip()
    if not value and allow_blank:
        return None
    if not value:
        raise PermissionDeniedError(f"חסר ערך עבור {field_label}.")
    try:
        parsed = int(value)
    except ValueError as exc:
        raise PermissionDeniedError(f"{field_label} חייב להיות מספר תקין.") from exc
    if parsed <= 0:
        raise PermissionDeniedError(f"{field_label} חייב להיות גדול מ-0.")
    return parsed


def _parse_optional_bool(raw_value: Any) -> bool | None:
    value = str(raw_value or "").strip().lower()
    if not value:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    raise PermissionDeniedError("הערך הבוליאני שנשלח לא תקין.")


def _extract_file_upload(field: Any, *, image_only: bool = False) -> tuple[str, bytes, str | None] | None:
    if not isinstance(field, web.FileField) or not field.filename:
        return None
    if image_only and field.content_type and not field.content_type.startswith("image/"):
        raise PermissionDeniedError("הקובץ שנשלח חייב להיות תמונה.")
    payload = field.file.read()
    if not payload:
        return None
    return field.filename, payload, field.content_type


async def _discord_user_label(bot: "SalesBot", user_id: int) -> str:
    user = bot.get_user(user_id)
    if user is None:
        try:
            user = await bot.fetch_user(user_id)
        except discord.HTTPException:
            return str(user_id)
    username = str(getattr(user, "name", "") or "").strip()
    global_name = str(getattr(user, "global_name", "") or "").strip()
    if global_name and username and global_name.casefold() != username.casefold():
        return f"{global_name} (@{username})"
    return global_name or (f"@{username}" if username else str(user_id))


def _system_options(systems: list[SystemRecord], selected_system_id: int | None = None) -> str:
    options = ['<option value="">ללא</option>']
    for system in systems:
        selected = " selected" if selected_system_id == system.id else ""
        options.append(f'<option value="{system.id}"{selected}>{_escape(system.name)}</option>')
    return "\n".join(options)


def _gamepass_options(gamepasses: list[RobloxGamePassRecord], selected_gamepass_id: int | None = None) -> str:
    options = ['<option value="">בחר גיימפאס</option>']
    for gamepass in gamepasses:
        price = _gamepass_price_label(gamepass)
        selected = " selected" if selected_gamepass_id == gamepass.game_pass_id else ""
        label = f"{gamepass.name} ({gamepass.game_pass_id} | {price})"
        options.append(f'<option value="{gamepass.game_pass_id}"{selected}>{_escape(label)}</option>')
    return "\n".join(options)


def _bool_options(selected_value: str = "") -> str:
    options = {"": "ללא שינוי", "true": "כן", "false": "לא"}
    return "\n".join(
        f'<option value="{value}"{" selected" if value == selected_value else ""}>{label}</option>'
        for value, label in options.items()
    )


def _payment_method_editor(service: Any, selected_keys: set[str], prices: dict[str, str]) -> str:
    cards: list[str] = []
    for key, label in service.available_payment_methods():
        checked = " checked" if key in selected_keys else ""
        cards.append(
            f"""
            <label class="meta-card check-card">
                <span class="check-line">
                    <input type="checkbox" name="payment_method" value="{_escape(key)}"{checked}>
                    <strong>{_escape(label)}</strong>
                </span>
                <input type="text" name="price_{_escape(key)}" placeholder="מחיר ב{_escape(label)}" value="{_escape(prices.get(key, ''))}">
            </label>
            """
        )
    return "\n".join(cards)


def _payment_method_select_options(special_system: SpecialSystemRecord, selected_key: str | None = None) -> str:
    options = ['<option value="">בחר שיטת תשלום</option>']
    for method in special_system.payment_methods:
        selected = " selected" if method.key == (selected_key or "") else ""
        label = f"{method.label} | {method.price}"
        options.append(f'<option value="{_escape(method.key)}"{selected}>{_escape(label)}</option>')
    return "\n".join(options)


def _special_system_url(bot: "SalesBot", special_system: SpecialSystemRecord) -> str:
    return f"{bot.settings.public_base_url}/special-systems/{special_system.slug}"


def _special_system_embed(special_system: SpecialSystemRecord) -> discord.Embed:
    embed = discord.Embed(title=special_system.title, description=special_system.description, color=discord.Color.gold())
    embed.add_field(
        name="אמצעי תשלום",
        value="\n".join(f"• {method.label}: {method.price}" for method in special_system.payment_methods),
        inline=False,
    )
    return embed


def _special_system_files(images: list[SpecialSystemImageRecord]) -> tuple[list[discord.File], str | None]:
    attachments: list[discord.File] = []
    first_image_name: str | None = None
    for image in images:
        attachments.append(discord.File(BytesIO(image.asset_bytes), filename=image.asset_name))
        if first_image_name is None and (image.content_type or "").startswith("image/"):
            first_image_name = image.asset_name
    return attachments, first_image_name


def _gamepass_price_label(gamepass: RobloxGamePassRecord) -> str:
    return f"{gamepass.price_in_robux} Robux" if gamepass.price_in_robux is not None else "לא מתומחר"


async def _linked_system_for_gamepass(bot: "SalesBot", game_pass_id: int) -> SystemRecord | None:
    try:
        return await bot.services.systems.get_system_by_gamepass_id(str(game_pass_id))
    except NotFoundError:
        return None


def _gamepass_embed(
    gamepass: RobloxGamePassRecord,
    linked_system: SystemRecord | None,
    *,
    display_gamepass_name: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=gamepass.name,
        description=gamepass.description or "אין כרגע תיאור לגיימפאס הזה.",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="מזהה גיימפאס", value=str(gamepass.game_pass_id), inline=True)
    embed.add_field(name="מחיר", value=_gamepass_price_label(gamepass), inline=True)
    embed.add_field(name="למכירה", value="כן" if gamepass.is_for_sale else "לא", inline=True)
    embed.add_field(name="קישור רכישה", value=bot_gamepass_url(gamepass), inline=False)
    embed.add_field(name="מערכת מקושרת", value=linked_system.name if linked_system else "לא מקושר", inline=False)
    if display_gamepass_name:
        embed.add_field(name="שם תצוגה במשחק", value=display_gamepass_name, inline=False)
    return embed


def bot_gamepass_url(gamepass: RobloxGamePassRecord) -> str:
    return f"https://www.roblox.com/game-pass/{gamepass.game_pass_id}"


async def _resolve_gamepass_context(bot: "SalesBot", discord_user_id: int) -> tuple[int, int]:
    if bot.settings.primary_guild_id is None:
        raise ConfigurationError("כדי לנהל גיימפאסים דרך האתר צריך להגדיר PRIMARY_GUILD_ID.")
    link = await bot.services.roblox_creator.get_link(bot.settings.primary_guild_id)
    if link.discord_user_id != discord_user_id:
        raise PermissionDeniedError(
            "כדי לנהל גיימפאסים מהאתר צריך להתחבר עם חשבון Discord שקישר את owner access דרך /linkasowner."
        )
    return bot.settings.primary_guild_id, discord_user_id


async def _owner_order_embed(
    special_system: SpecialSystemRecord,
    order: SpecialOrderRequestRecord,
) -> discord.Embed:
    embed = discord.Embed(title="יש בקשה לקניית מערכת מיוחדת חדשה", color=discord.Color.gold())
    embed.add_field(name="מערכת מיוחדת", value=special_system.title, inline=False)
    embed.add_field(name="משתמש Discord", value=f"<@{order.user_id}>\n{order.discord_name}\n{order.user_id}", inline=False)
    embed.add_field(name="שם Roblox שנשלח", value=order.roblox_name, inline=False)
    embed.add_field(name="שיטת תשלום", value=f"{order.payment_method_label} | {order.payment_price}", inline=False)
    linked_label = "לא מחובר"
    if order.linked_roblox_sub:
        parts = [order.linked_roblox_display_name or "", order.linked_roblox_username or "", order.linked_roblox_sub]
        linked_label = " | ".join(part for part in parts if part)
    embed.add_field(name="חשבון Roblox מחובר", value=linked_label, inline=False)
    embed.add_field(name="סטטוס", value=ORDER_STATUS_LABELS.get(order.status, order.status), inline=False)
    embed.set_footer(text=f"בקשה #{order.id}")
    return embed


async def _update_owner_order_message(
    bot: "SalesBot",
    special_system: SpecialSystemRecord,
    order: SpecialOrderRequestRecord,
) -> None:
    if order.owner_message_id is None:
        return
    try:
        owner = await bot.fetch_user(bot.settings.owner_user_id)
        owner_dm = owner.dm_channel or await owner.create_dm()
        message = await owner_dm.fetch_message(order.owner_message_id)
        embed = await _owner_order_embed(special_system, order)
        view = discord.ui.View()
        view.add_item(
            discord.ui.Button(
                label="פתח את הבקשה באתר",
                style=discord.ButtonStyle.link,
                url=f"{bot.settings.public_base_url}/admin/special-orders/{order.id}",
            )
        )
        await message.edit(content="עדכון סטטוס לבקשת מערכת מיוחדת", embed=embed, view=view)
    except discord.HTTPException:
        return


async def _send_special_system_message(bot: "SalesBot", special_system: SpecialSystemRecord) -> discord.Message:
    images = await bot.services.special_systems.list_special_system_images(special_system.id)
    channel = bot.get_channel(special_system.channel_id) or await bot.fetch_channel(special_system.channel_id)
    if not isinstance(channel, discord.TextChannel):
        raise PermissionDeniedError("אפשר לפרסם מערכת מיוחדת רק לערוץ טקסט.")
    embed = _special_system_embed(special_system)
    files, first_image_name = _special_system_files(images)
    if first_image_name:
        embed.set_image(url=f"attachment://{first_image_name}")
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="קניה מיוחדת", style=discord.ButtonStyle.link, url=_special_system_url(bot, special_system)))
    send_kwargs: dict[str, Any] = {"embed": embed, "view": view}
    if files:
        send_kwargs["files"] = files
    return await channel.send(**send_kwargs)


async def _delete_special_system_message(bot: "SalesBot", special_system: SpecialSystemRecord) -> None:
    if special_system.message_id is None:
        return
    try:
        channel = bot.get_channel(special_system.channel_id) or await bot.fetch_channel(special_system.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        message = await channel.fetch_message(special_system.message_id)
        await message.delete()
    except discord.HTTPException:
        return


async def _refresh_special_system_public_message(
    bot: "SalesBot",
    special_system: SpecialSystemRecord,
    *,
    previous_record: SpecialSystemRecord | None = None,
) -> SpecialSystemRecord:
    previous = previous_record or special_system
    if not special_system.is_active:
        await _delete_special_system_message(bot, previous)
        return await bot.services.special_systems.clear_public_message(special_system.id)

    message = await _send_special_system_message(bot, special_system)
    updated_system = await bot.services.special_systems.set_public_message(
        special_system.id,
        channel_id=special_system.channel_id,
        message_id=message.id,
    )
    if previous.message_id is not None and previous.message_id != message.id:
        await _delete_special_system_message(bot, previous)
    return updated_system


async def website_login(request: web.Request) -> web.Response:
    bot: SalesBot = request.app["bot"]
    next_path = request.query.get("next") or "/admin"
    try:
        state = await bot.services.web_auth.create_state(next_path)
        raise web.HTTPFound(bot.services.web_auth.build_authorization_url(state))
    except SalesBotError as exc:
        return _error_response("התחברות לאתר", str(exc), status=400)


async def website_callback(request: web.Request) -> web.Response:
    bot: SalesBot = request.app["bot"]
    state = request.query.get("state", "")
    code = request.query.get("code", "")
    if not state or not code:
        return _error_response("התחברות לאתר", "חסרים פרטי התחברות מהחזרה של Discord.", status=400)
    try:
        next_path = await bot.services.web_auth.consume_state(state)
        tokens = await bot.services.web_auth.exchange_code(bot.http_session, code)
        identity = await bot.services.web_auth.fetch_identity(bot.http_session, str(tokens.get("access_token") or ""))
        session = await bot.services.web_auth.create_session(
            discord_user_id=int(str(identity.get("id") or "0")),
            username=str(identity.get("username") or "").strip(),
            global_name=str(identity.get("global_name") or "").strip() or None,
            avatar_hash=str(identity.get("avatar") or "").strip() or None,
        )
        response = web.HTTPFound(next_path)
        response.set_cookie(
            bot.services.web_auth.cookie_name,
            session.token,
            max_age=24 * 60 * 60,
            httponly=True,
            secure=bot.settings.public_base_url.startswith("https://"),
            samesite="Lax",
            path="/",
        )
        return response
    except SalesBotError as exc:
        return _error_response("התחברות לאתר", str(exc), status=400)


async def website_logout(request: web.Request) -> web.Response:
    bot, session = await _current_site_session(request)
    if session is not None:
        await bot.services.web_auth.delete_session(session.token)
    response = web.HTTPFound("/")
    response.del_cookie(bot.services.web_auth.cookie_name, path="/")
    return response


async def admin_dashboard_page(request: web.Request) -> web.Response:
    try:
        bot, session = await _require_admin_session(request)
        admin_ids = await bot.services.admins.list_admin_ids()
        systems = await bot.services.systems.list_systems()
        special_systems = await bot.services.special_systems.list_special_systems(active_only=True)
        rollable_events = await bot.services.events.list_rollable_events()
        pending_special_orders = await bot.services.special_systems.list_order_requests(statuses=("pending",))
        stats = f"""
        <div class="stat-grid">
            <div class="card"><h2>אדמינים</h2><div class="stat-value">{len(admin_ids)}</div></div>
            <div class="card"><h2>מערכות</h2><div class="stat-value">{len(systems)}</div></div>
            <div class="card"><h2>מערכות מיוחדות</h2><div class="stat-value">{len(special_systems)}</div></div>
            <div class="card"><h2>אירועים פתוחים</h2><div class="stat-value">{len(rollable_events)}</div></div>
            <div class="card"><h2>בקשות ממתינות</h2><div class="stat-value">{len(pending_special_orders)}</div></div>
        </div>
        """
        quick_links = """
        <div class="hero-grid">
            <div class="card"><h3>ניהול אדמינים</h3><p>הוספה והסרה של צוות הניהול מתוך האתר.</p><div class="actions"><a class="link-button" href="/admin/admins">פתח</a></div></div>
            <div class="card"><h3>מערכות רגילות</h3><p>יצירת מערכות, עריכה, מחיקה ומתן או הסרה לפי User ID.</p><div class="actions"><a class="link-button" href="/admin/systems">פתח</a></div></div>
            <div class="card"><h3>גיימפאסים</h3><p>יצירה, עדכון, קישור ושליחה של גיימפאסים ישירות מתוך האתר.</p><div class="actions"><a class="link-button" href="/admin/gamepasses">פתח</a></div></div>
            <div class="card"><h3>מערכות מיוחדות</h3><p>פרסום מערכת מיוחדת עם כפתור קניה, תמונות, מחירים ושיטות תשלום.</p><div class="actions"><a class="link-button" href="/admin/special-systems">פתח</a></div></div>
            <div class="card"><h3>בקשות מיוחדות</h3><p>רשימת כל הבקשות, צפייה בפרטים, אישור או דחייה עם הודעה חזרה.</p><div class="actions"><a class="link-button" href="/admin/special-orders">פתח</a></div></div>
            <div class="card"><h3>כלי תוכן קיימים</h3><p>הפאנלים הקיימים של סקרים, הגרלות ואירועים נשארו זמינים גם דרך האתר.</p><div class="actions"><a class="link-button" href="/admin/polls/new">סקרים</a><a class="link-button ghost-button" href="/admin/giveaways/new">הגרלות</a><a class="link-button ghost-button" href="/admin/events/new">אירועים</a></div></div>
        </div>
        """
        config_html = f"""
        <div class="card">
            <h2>סיכום הגדרות ריצה</h2>
            <div class="price-list">
                <div class="price-item"><strong>PUBLIC_BASE_URL</strong><span class="mono">{_escape(bot.settings.public_base_url)}</span></div>
                <div class="price-item"><strong>PRIMARY_GUILD_ID</strong><span class="mono">{_escape(bot.settings.primary_guild_id or 'לא מוגדר')}</span></div>
                <div class="price-item"><strong>OWNER_USER_ID</strong><span class="mono">{_escape(bot.settings.owner_user_id)}</span></div>
                <div class="price-item"><strong>ORDER_CHANNEL_ID</strong><span class="mono">{_escape(bot.settings.order_channel_id)}</span></div>
            </div>
            <p class="muted">הגדרות סביבה עדיין מנוהלות דרך השרת וה-ENV, אבל כל הכלים התפעוליים של הבוט פתוחים מכאן.</p>
        </div>
        """
        body = _admin_shell(session, title="לוח ניהול ראשי", intro="כלי האתר מרוכזים כאן. כל דף משתמש באותם שירותים של פקודות הסלאש.", content=stats + quick_links + config_html)
        return _page_response("לוח ניהול", body)
    except web.HTTPException:
        raise
    except SalesBotError as exc:
        return _error_response("לוח ניהול", str(exc), status=403)


async def admin_admins_page(request: web.Request) -> web.Response:
    notice: str | None = None
    success = True
    try:
        bot, session = await _require_admin_session(request)
        if request.method == "POST":
            form = await request.post()
            action = str(form.get("action", "")).strip()
            if action == "add":
                user_id = _parse_positive_int(form.get("user_id"), "User ID")
                assert user_id is not None
                await bot.services.admins.add_admin(user_id, session.discord_user_id)
                notice = "האדמין נוסף בהצלחה."
            elif action == "remove":
                user_id = _parse_positive_int(form.get("user_id"), "User ID")
                assert user_id is not None
                await bot.services.admins.remove_admin(user_id)
                notice = "האדמין הוסר בהצלחה."
        admin_ids = await bot.services.admins.list_admin_ids()
        labels = await asyncio.gather(*(_discord_user_label(bot, user_id) for user_id in admin_ids))
        rows = "\n".join(
            f"""
            <tr>
                <td><strong>{_escape(label)}</strong><br><span class="mono">{user_id}</span></td>
                <td>{'בעלים' if user_id == bot.settings.owner_user_id else 'אדמין'}</td>
                <td>{'' if user_id == bot.settings.owner_user_id else f'<form method="post" class="inline-form"><input type="hidden" name="action" value="remove"><input type="hidden" name="user_id" value="{user_id}"><button type="submit" class="ghost-button danger">הסר</button></form>'}</td>
            </tr>
            """
            for user_id, label in zip(admin_ids, labels, strict=False)
        )
        content = f"""
        {_notice_html(notice, success=success)}
        <div class="split-grid">
            <div class="card">
                <h2>הוספת אדמין</h2>
                <form method="post">
                    <input type="hidden" name="action" value="add">
                    <div class="grid"><label class="field"><span>User ID</span><input type="number" min="1" name="user_id" required></label></div>
                    <div class="actions"><button type="submit">הוסף אדמין</button></div>
                </form>
            </div>
            <div class="card"><h2>הערה</h2><p>בעל הבוט המוגדר ב-ENV נשאר אדמין קבוע ואי אפשר להסיר אותו דרך האתר.</p></div>
        </div>
        <div class="table-wrap"><table><thead><tr><th>משתמש</th><th>סוג</th><th>פעולה</th></tr></thead><tbody>{rows}</tbody></table></div>
        """
        body = _admin_shell(session, title="ניהול אדמינים", intro="ניהול רשימת האדמינים של הבוט מתוך האתר.", content=content)
        return _page_response("ניהול אדמינים", body)
    except web.HTTPException:
        raise
    except SalesBotError as exc:
        return _error_response("ניהול אדמינים", str(exc), status=400)


async def admin_systems_page(request: web.Request) -> web.Response:
    notice: str | None = None
    success = True
    try:
        bot, session = await _require_admin_session(request)
        if request.method == "POST":
            form = await request.post()
            action = str(form.get("action", "")).strip()
            if action == "create":
                file_upload = _extract_file_upload(form.get("file"))
                if file_upload is None:
                    raise PermissionDeniedError("חובה להעלות קובץ מערכת ראשי.")
                image_upload = _extract_file_upload(form.get("image"), image_only=True)
                created_system = await bot.services.systems.create_system_from_uploads(
                    name=str(form.get("name", "")),
                    description=str(form.get("description", "")),
                    file_upload=(file_upload[0], file_upload[1]),
                    image_upload=(image_upload[0], image_upload[1]) if image_upload else None,
                    created_by=session.discord_user_id,
                    paypal_link=str(form.get("paypal_link", "")).strip() or None,
                    roblox_gamepass_reference=str(form.get("roblox_gamepass", "")).strip() or None,
                )
                notice = f"המערכת {created_system.name} נוצרה בהצלחה."
            elif action == "delete":
                system_id = _parse_positive_int(form.get("system_id"), "מזהה מערכת")
                assert system_id is not None
                deleted = await bot.services.systems.delete_system(system_id)
                notice = f"המערכת {deleted.name} נמחקה."
            elif action == "grant":
                system_id = _parse_positive_int(form.get("system_id"), "מזהה מערכת")
                user_id = _parse_positive_int(form.get("user_id"), "Discord User ID")
                assert system_id is not None and user_id is not None
                system = await bot.services.systems.get_system(system_id)
                user = bot.get_user(user_id) or await bot.fetch_user(user_id)
                await bot.services.delivery.deliver_system(bot, user, system, source="grant", granted_by=session.discord_user_id)
                notice = f"המערכת {system.name} נשלחה למשתמש {user_id}."
            elif action == "revoke":
                system_id = _parse_positive_int(form.get("system_id"), "מזהה מערכת")
                user_id = _parse_positive_int(form.get("user_id"), "Discord User ID")
                assert system_id is not None and user_id is not None
                system = await bot.services.systems.get_system(system_id)
                await bot.services.ownership.revoke_system(user_id, system_id)
                deleted_messages = await bot.services.delivery.purge_deliveries(bot, user_id=user_id, system_id=system_id)
                await bot.services.ownership.refresh_claim_role_membership(bot, user_id, sync_ownerships=False)
                notice = f"המערכת {system.name} הוסרה מ-{user_id}. נמחקו {deleted_messages} הודעות DM ישנות."
        systems = await bot.services.systems.list_systems()
        system_rows = "\n".join(
            f"""
            <tr>
                <td><strong>{_escape(system.name)}</strong><br><span class="muted">{_escape(system.description[:120])}</span></td>
                <td>{_escape(system.paypal_link or 'לא מוגדר')}</td>
                <td>{_escape(system.roblox_gamepass_id or 'לא מוגדר')}</td>
                <td>
                    <div class="actions">
                        <a class="link-button ghost-button" href="/admin/systems/{system.id}/edit">עריכה</a>
                        <form method="post" class="inline-form"><input type="hidden" name="action" value="delete"><input type="hidden" name="system_id" value="{system.id}"><button type="submit" class="ghost-button danger">מחיקה</button></form>
                    </div>
                </td>
            </tr>
            """
            for system in systems
        )
        content = f"""
        {_notice_html(notice, success=success)}
        <div class="split-grid">
            <div class="card">
                <h2>יצירת מערכת חדשה</h2>
                <form method="post" enctype="multipart/form-data">
                    <input type="hidden" name="action" value="create">
                    <div class="grid">
                        <label class="field field-wide"><span>שם</span><input type="text" name="name" required></label>
                        <label class="field field-wide"><span>תיאור</span><textarea name="description" required></textarea></label>
                        <label class="field"><span>PayPal Link</span><input type="url" name="paypal_link"></label>
                        <label class="field"><span>Roblox Gamepass</span><input type="text" name="roblox_gamepass"></label>
                        <label class="field"><span>קובץ מערכת</span><input type="file" name="file" required></label>
                        <label class="field"><span>תמונה</span><input type="file" name="image" accept="image/*"></label>
                    </div>
                    <div class="actions"><button type="submit">צור מערכת</button></div>
                </form>
            </div>
            <div class="card stack">
                <div>
                    <h2>מתן מערכת לפי User ID</h2>
                    <form method="post">
                        <input type="hidden" name="action" value="grant">
                        <div class="grid">
                            <label class="field"><span>User ID</span><input type="number" min="1" name="user_id" required></label>
                            <label class="field"><span>מערכת</span><select name="system_id" required>{_system_options(systems, None)}</select></label>
                        </div>
                        <div class="actions"><button type="submit">שלח מערכת</button></div>
                    </form>
                </div>
                <div>
                    <h2>הסרת מערכת לפי User ID</h2>
                    <form method="post">
                        <input type="hidden" name="action" value="revoke">
                        <div class="grid">
                            <label class="field"><span>User ID</span><input type="number" min="1" name="user_id" required></label>
                            <label class="field"><span>מערכת</span><select name="system_id" required>{_system_options(systems, None)}</select></label>
                        </div>
                        <div class="actions"><button type="submit" class="ghost-button danger">הסר בעלות</button></div>
                    </form>
                </div>
            </div>
        </div>
        <div class="table-wrap"><table><thead><tr><th>מערכת</th><th>PayPal</th><th>גיימפאס</th><th>פעולות</th></tr></thead><tbody>{system_rows}</tbody></table></div>
        """
        body = _admin_shell(session, title="ניהול מערכות", intro="יצירה, עריכה, מחיקה ומתן/הסרה של מערכות דרך האתר.", content=content)
        return _page_response("ניהול מערכות", body)
    except web.HTTPException:
        raise
    except SalesBotError as exc:
        return _error_response("ניהול מערכות", str(exc), status=400)


async def admin_gamepasses_page(request: web.Request) -> web.Response:
    notice: str | None = None
    success = True
    try:
        bot, session = await _require_admin_session(request)
        guild_id, discord_user_id = await _resolve_gamepass_context(bot, session.discord_user_id)
        systems = await bot.services.systems.list_systems()
        channels = await _list_text_channels(bot)
        if request.method == "POST":
            form = await request.post()
            action = str(form.get("action", "")).strip()
            if action == "create":
                price = _parse_positive_int(form.get("price"), "מחיר")
                assert price is not None
                image_upload = _extract_file_upload(form.get("image"), image_only=True)
                selected_system_id = _parse_positive_int(form.get("system_id"), "מערכת", allow_blank=True)
                created_gamepass = await bot.services.roblox_creator.create_gamepass(
                    bot,
                    guild_id,
                    discord_user_id,
                    name=str(form.get("name", "")),
                    description=str(form.get("description", "")).strip() or None,
                    price=price,
                    is_for_sale=str(form.get("for_sale", "")).lower() in {"1", "true", "yes", "on"},
                    is_regional_pricing_enabled=str(form.get("regional_pricing", "")).lower() in {"1", "true", "yes", "on"},
                    image_upload=image_upload,
                )
                if str(form.get("display_gamepass_name", "")).strip():
                    await bot.services.systems.set_gamepass_display_name(str(created_gamepass.game_pass_id), str(form.get("display_gamepass_name", "")).strip())
                if selected_system_id is not None:
                    await bot.services.systems.set_system_gamepass(selected_system_id, str(created_gamepass.game_pass_id))
                notice = f"הגיימפאס {created_gamepass.name} נוצר בהצלחה."
            elif action == "update":
                gamepass_id = _parse_positive_int(form.get("gamepass_id"), "מזהה גיימפאס")
                assert gamepass_id is not None
                image_upload = _extract_file_upload(form.get("image"), image_only=True)
                price = _parse_positive_int(form.get("price"), "מחיר", allow_blank=True)
                for_sale = _parse_optional_bool(form.get("for_sale_state"))
                regional_pricing = _parse_optional_bool(form.get("regional_pricing_state"))
                name = str(form.get("name", "")).strip() or None
                description = str(form.get("description", "")).strip() or None
                display_name = str(form.get("display_gamepass_name", "")).strip()
                clear_display_name = str(form.get("clear_display_gamepass_name", "")).lower() in {"1", "true", "yes", "on"}
                if any(value is not None for value in (name, description, price, for_sale, regional_pricing)) or image_upload is not None:
                    await bot.services.roblox_creator.update_gamepass(
                        bot,
                        guild_id,
                        discord_user_id,
                        game_pass_id=gamepass_id,
                        name=name,
                        description=description,
                        price=price,
                        is_for_sale=for_sale,
                        is_regional_pricing_enabled=regional_pricing,
                        image_upload=image_upload,
                    )
                if clear_display_name:
                    await bot.services.systems.set_gamepass_display_name(str(gamepass_id), None)
                elif display_name:
                    await bot.services.systems.set_gamepass_display_name(str(gamepass_id), display_name)
                elif not any(value is not None for value in (name, description, price, for_sale, regional_pricing)) and image_upload is None:
                    raise PermissionDeniedError("לא נשלח אף שדה לעדכון.")
                notice = f"הגיימפאס {gamepass_id} עודכן."
            elif action == "connect":
                gamepass_id = _parse_positive_int(form.get("gamepass_id"), "מזהה גיימפאס")
                system_id = _parse_positive_int(form.get("system_id"), "מערכת")
                assert gamepass_id is not None and system_id is not None
                await bot.services.roblox_creator.get_gamepass(bot, guild_id, discord_user_id, gamepass_id)
                await bot.services.systems.set_system_gamepass(system_id, str(gamepass_id))
                notice = f"הגיימפאס {gamepass_id} קושר למערכת שנבחרה."
            elif action == "send":
                gamepass_id = _parse_positive_int(form.get("gamepass_id"), "מזהה גיימפאס")
                channel_id = _parse_positive_int(form.get("channel_id"), "ערוץ")
                assert gamepass_id is not None and channel_id is not None
                gamepass_record = await bot.services.roblox_creator.get_gamepass(bot, guild_id, discord_user_id, gamepass_id)
                if not gamepass_record.is_for_sale:
                    raise ExternalServiceError("הגיימפאס הזה לא מוגדר כרגע למכירה.")
                linked_system = await _linked_system_for_gamepass(bot, gamepass_record.game_pass_id)
                if linked_system is None:
                    raise NotFoundError("צריך קודם לקשר את הגיימפאס למערכת.")
                channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
                if not isinstance(channel, discord.TextChannel):
                    raise PermissionDeniedError("אפשר לשלוח את הודעת הגיימפאס רק לערוץ טקסט.")
                embed = _gamepass_embed(gamepass_record, linked_system)
                embed.title = f"קניית {linked_system.name}"
                embed.description = f"קנו את **{linked_system.name}** דרך הגיימפאס הזה.\n\nמחיר: **{_gamepass_price_label(gamepass_record)}**"
                view = discord.ui.View()
                view.add_item(discord.ui.Button(label="קניה ב-Roblox", style=discord.ButtonStyle.link, url=bot.services.roblox_creator.gamepass_url(gamepass_record.game_pass_id)))
                await channel.send(embed=embed, view=view)
                notice = f"הגיימפאס {gamepass_record.name} פורסם בערוץ שנבחר."
        gamepasses = await bot.services.roblox_creator.list_gamepasses(bot, guild_id, discord_user_id)
        gamepass_rows: list[str] = []
        for gamepass in gamepasses[:50]:
            linked_system = await _linked_system_for_gamepass(bot, gamepass.game_pass_id)
            display_name = await bot.services.systems.get_gamepass_display_name(str(gamepass.game_pass_id))
            gamepass_rows.append(f"<tr><td><strong>{_escape(gamepass.name)}</strong><br><span class='mono'>{gamepass.game_pass_id}</span></td><td>{_escape(_gamepass_price_label(gamepass))}</td><td>{'כן' if gamepass.is_for_sale else 'לא'}</td><td>{_escape(linked_system.name if linked_system else 'לא מקושר')}</td><td>{_escape(display_name or 'לא מוגדר')}</td></tr>")
        content = f"""
        {_notice_html(notice, success=success)}
        <div class="split-grid">
            <div class="card">
                <h2>יצירת גיימפאס חדש</h2>
                <form method="post" enctype="multipart/form-data">
                    <input type="hidden" name="action" value="create">
                    <div class="grid">
                        <label class="field field-wide"><span>שם</span><input type="text" name="name" required></label>
                        <label class="field"><span>מחיר</span><input type="number" min="1" name="price" required></label>
                        <label class="field"><span>שם תצוגה במשחק</span><input type="text" name="display_gamepass_name"></label>
                        <label class="field field-wide"><span>תיאור</span><textarea name="description"></textarea></label>
                        <label class="field"><span>קישור למערכת</span><select name="system_id">{_system_options(systems, None)}</select></label>
                        <label class="field"><span>תמונה</span><input type="file" name="image" accept="image/*"></label>
                        <label class="field"><span><input type="checkbox" name="for_sale" value="true" checked> למכירה מיד</span></label>
                        <label class="field"><span><input type="checkbox" name="regional_pricing" value="true" checked> תמחור אזורי</span></label>
                    </div>
                    <div class="actions"><button type="submit">צור גיימפאס</button></div>
                </form>
            </div>
            <div class="card stack">
                <div>
                    <h2>עדכון גיימפאס</h2>
                    <form method="post" enctype="multipart/form-data">
                        <input type="hidden" name="action" value="update">
                        <div class="grid">
                            <label class="field field-wide"><span>גיימפאס</span><select name="gamepass_id" required>{_gamepass_options(gamepasses, None)}</select></label>
                            <label class="field"><span>שם חדש</span><input type="text" name="name"></label>
                            <label class="field"><span>מחיר חדש</span><input type="number" min="1" name="price"></label>
                            <label class="field"><span>שם תצוגה במשחק</span><input type="text" name="display_gamepass_name"></label>
                            <label class="field"><span><input type="checkbox" name="clear_display_gamepass_name" value="true"> נקה שם תצוגה</span></label>
                            <label class="field"><span>למכירה</span><select name="for_sale_state">{_bool_options()}</select></label>
                            <label class="field"><span>תמחור אזורי</span><select name="regional_pricing_state">{_bool_options()}</select></label>
                            <label class="field field-wide"><span>תיאור</span><textarea name="description"></textarea></label>
                            <label class="field"><span>תמונה</span><input type="file" name="image" accept="image/*"></label>
                        </div>
                        <div class="actions"><button type="submit">עדכן גיימפאס</button></div>
                    </form>
                </div>
                <div>
                    <h2>קישור או שליחה</h2>
                    <form method="post" class="stack"><input type="hidden" name="action" value="connect"><div class="grid"><label class="field"><span>גיימפאס</span><select name="gamepass_id" required>{_gamepass_options(gamepasses, None)}</select></label><label class="field"><span>מערכת</span><select name="system_id" required>{_system_options(systems, None)}</select></label></div><div class="actions"><button type="submit">קשר למערכת</button></div></form>
                    <form method="post" class="stack"><input type="hidden" name="action" value="send"><div class="grid"><label class="field"><span>גיימפאס</span><select name="gamepass_id" required>{_gamepass_options(gamepasses, None)}</select></label><label class="field"><span>ערוץ</span><select name="channel_id" required>{_render_channel_options(channels, None)}</select></label></div><div class="actions"><button type="submit">שלח לערוץ</button></div></form>
                </div>
            </div>
        </div>
        <div class="table-wrap"><table><thead><tr><th>גיימפאס</th><th>מחיר</th><th>למכירה</th><th>מערכת</th><th>שם תצוגה</th></tr></thead><tbody>{''.join(gamepass_rows)}</tbody></table></div>
        """
        body = _admin_shell(session, title="ניהול גיימפאסים", intro="אותם כלים של owner gamepass commands, עכשיו דרך האתר.", content=content)
        return _page_response("ניהול גיימפאסים", body)
    except web.HTTPException:
        raise
    except SalesBotError as exc:
        return _error_response("ניהול גיימפאסים", str(exc), status=400)


async def special_system_compose_page(request: web.Request) -> web.Response:
    notice: str | None = None
    success = True
    form_title = request.query.get("title", "")
    form_description = ""
    selected_payment_methods: set[str] = set()
    price_values: dict[str, str] = {}
    selected_channel_id: int | None = None
    try:
        bot, session = await _require_admin_session(request)
        channels = await _list_text_channels(bot)
        if request.method == "POST":
            form = await request.post()
            action = str(form.get("action", "create")).strip().lower()
            if action == "toggle":
                special_system_id = _parse_positive_int(form.get("special_system_id"), "מערכת מיוחדת")
                assert special_system_id is not None
                requested_state = str(form.get("state", "")).strip().lower()
                if requested_state not in {"activate", "deactivate"}:
                    raise PermissionDeniedError("הפעולה שנבחרה על המערכת המיוחדת לא תקינה.")
                current_system = await bot.services.special_systems.get_special_system(special_system_id)
                updated_system = await bot.services.special_systems.set_active(
                    special_system_id,
                    is_active=requested_state == "activate",
                )
                await _refresh_special_system_public_message(
                    bot,
                    updated_system,
                    previous_record=current_system,
                )
                notice = "המערכת המיוחדת הופעלה מחדש ופורסמה." if requested_state == "activate" else "המערכת המיוחדת הושבתה והוסרה מהדף הציבורי."
            else:
                form_title = str(form.get("title", ""))
                form_description = str(form.get("description", ""))
                selected_payment_methods = {str(value) for value in form.getall("payment_method", [])}
                price_values = {key: str(form.get(f"price_{key}", "")) for key, _label in bot.services.special_systems.available_payment_methods()}
                selected_channel_id = _parse_positive_int(form.get("channel_id"), "ערוץ")
                assert selected_channel_id is not None
                images_uploads: list[tuple[str, bytes, str | None]] = []
                for field in form.getall("images", []):
                    upload = _extract_file_upload(field, image_only=True)
                    if upload is not None:
                        images_uploads.append(upload)
                payment_payload = [(key, price_values.get(key, "")) for key in selected_payment_methods]
                special_system = await bot.services.special_systems.create_special_system(
                    title=form_title,
                    description=form_description,
                    payment_methods=payment_payload,
                    images=images_uploads,
                    channel_id=selected_channel_id,
                    created_by=session.discord_user_id,
                )
                await _refresh_special_system_public_message(bot, special_system)
                notice = "המערכת המיוחדת נשמרה ופורסמה בהצלחה."
        existing_special_systems = await bot.services.special_systems.list_special_systems()
        existing_rows = "\n".join(
            f"""
            <tr>
                <td><strong>{_escape(item.title)}</strong><br><span class="mono">/{_escape(item.slug)}</span></td>
                <td><span class="badge{' rejected' if not item.is_active else ''}">{'פעילה' if item.is_active else 'לא פעילה'}</span></td>
                <td>{_escape(', '.join(f'{method.label}: {method.price}' for method in item.payment_methods))}</td>
                <td>{item.channel_id}</td>
                <td>
                    <div class="actions">
                        {'<a class="link-button ghost-button" href="' + _escape(_special_system_url(bot, item)) + '" target="_blank" rel="noreferrer">פתח דף קניה</a>' if item.is_active else ''}
                        <a class="link-button ghost-button" href="/admin/special-systems/{item.id}/edit">ערוך</a>
                        <form method="post" class="inline-form">
                            <input type="hidden" name="action" value="toggle">
                            <input type="hidden" name="special_system_id" value="{item.id}">
                            <input type="hidden" name="state" value="{'deactivate' if item.is_active else 'activate'}">
                            <button type="submit" class="ghost-button{' danger' if item.is_active else ''}">{'השבת' if item.is_active else 'הפעל מחדש'}</button>
                        </form>
                    </div>
                </td>
            </tr>
            """
            for item in existing_special_systems
        )
        content = f"""
        {_notice_html(notice, success=success)}
        <div class="split-grid">
            <div class="card">
                <h2>פרסום מערכת מיוחדת</h2>
                <form method="post" enctype="multipart/form-data">
                    <input type="hidden" name="action" value="create">
                    <div class="grid">
                        <label class="field field-wide"><span>כותרת</span><input type="text" name="title" value="{_escape(form_title)}" required></label>
                        <label class="field field-wide"><span>תיאור</span><textarea name="description" required>{_escape(form_description)}</textarea></label>
                        <div class="field field-wide"><span>אמצעי תשלום ומחיר לכל אמצעי</span><div class="stack">{_payment_method_editor(bot.services.special_systems, selected_payment_methods, price_values)}</div></div>
                        <label class="field field-wide"><span>תמונות</span><input type="file" name="images" accept="image/*" multiple></label>
                        <label class="field"><span>ערוץ לשליחה</span><select name="channel_id" required>{_render_channel_options(channels, selected_channel_id)}</select></label>
                    </div>
                    <div class="actions"><button type="submit">פרסם מערכת מיוחדת</button></div>
                </form>
            </div>
            <div class="card"><h2>מה הדף מייצר</h2><p>האתר ישלח הודעה עם כפתור <strong>קניה מיוחדת</strong>, יבנה דף הזמנה ציבורי בעברית, וישמור את הבקשות לרשימת האדמין.</p></div>
        </div>
        <div class="table-wrap"><table><thead><tr><th>מערכת</th><th>סטטוס</th><th>שיטות תשלום</th><th>ערוץ</th><th>פעולות</th></tr></thead><tbody>{existing_rows}</tbody></table></div>
        """
        body = _admin_shell(session, title="מערכות מיוחדות", intro="יצירת דף קניה מיוחד עם תמונות, מחירים וכפתור קניה יעודי.", content=content)
        return _page_response("מערכות מיוחדות", body)
    except web.HTTPException:
        raise
    except SalesBotError as exc:
        return _error_response("מערכות מיוחדות", str(exc), status=400)


async def special_system_edit_page(request: web.Request) -> web.Response:
    notice: str | None = None
    success = True
    try:
        bot, session = await _require_admin_session(request)
        channels = await _list_text_channels(bot)
        special_system_id = int(request.match_info["special_system_id"])
        current_system = await bot.services.special_systems.get_special_system(special_system_id)
        images = await bot.services.special_systems.list_special_system_images(current_system.id)
        form_title = current_system.title
        form_description = current_system.description
        selected_payment_methods = {method.key for method in current_system.payment_methods}
        price_values = {method.key: method.price for method in current_system.payment_methods}
        selected_channel_id: int | None = current_system.channel_id
        replace_images = False

        if request.method == "POST":
            form = await request.post()
            form_title = str(form.get("title", ""))
            form_description = str(form.get("description", ""))
            selected_payment_methods = {str(value) for value in form.getall("payment_method", [])}
            price_values = {key: str(form.get(f"price_{key}", "")) for key, _label in bot.services.special_systems.available_payment_methods()}
            selected_channel_id = _parse_positive_int(form.get("channel_id"), "ערוץ")
            assert selected_channel_id is not None
            replace_images = str(form.get("replace_images", "")).lower() in {"1", "true", "yes", "on"}
            images_uploads: list[tuple[str, bytes, str | None]] = []
            for field in form.getall("images", []):
                upload = _extract_file_upload(field, image_only=True)
                if upload is not None:
                    images_uploads.append(upload)
            payment_payload = [(key, price_values.get(key, "")) for key in selected_payment_methods]
            updated_system = await bot.services.special_systems.update_special_system(
                current_system.id,
                title=form_title,
                description=form_description,
                payment_methods=payment_payload,
                channel_id=selected_channel_id,
                replace_images=replace_images,
                images=images_uploads,
            )
            if updated_system.is_active:
                updated_system = await _refresh_special_system_public_message(
                    bot,
                    updated_system,
                    previous_record=current_system,
                )
            current_system = updated_system
            images = await bot.services.special_systems.list_special_system_images(current_system.id)
            notice = "המערכת המיוחדת עודכנה בהצלחה."

        public_url = _special_system_url(bot, current_system) if current_system.is_active else None
        message_url = _message_link(bot, current_system.channel_id, current_system.message_id)
        gallery_html = '<div class="gallery">' + ''.join(
            f'<img src="/special-system-images/{image.id}" alt="{_escape(image.asset_name)}">' for image in images
        ) + '</div>' if images else '<p class="muted">אין כרגע תמונות שמורות למערכת הזאת.</p>'
        content = f"""
        {_notice_html(notice, success=success)}
        <div class="split-grid">
            <div class="card stack">
                <div>
                    <h2>עריכת מערכת מיוחדת #{current_system.id}</h2>
                    <p class="muted">ה-slug הציבורי נשאר קבוע כדי לא לשבור קישורים קיימים.</p>
                </div>
                <div class="price-list">
                    <div class="price-item"><strong>Slug</strong><span class="mono">/{_escape(current_system.slug)}</span></div>
                    <div class="price-item"><strong>סטטוס</strong><span>{'פעילה' if current_system.is_active else 'לא פעילה'}</span></div>
                    <div class="price-item"><strong>ערוץ נוכחי</strong><span>{current_system.channel_id}</span></div>
                </div>
                <form method="post" enctype="multipart/form-data">
                    <div class="grid">
                        <label class="field field-wide"><span>כותרת</span><input type="text" name="title" value="{_escape(form_title)}" required></label>
                        <label class="field field-wide"><span>תיאור</span><textarea name="description" required>{_escape(form_description)}</textarea></label>
                        <div class="field field-wide"><span>אמצעי תשלום ומחיר לכל אמצעי</span><div class="stack">{_payment_method_editor(bot.services.special_systems, selected_payment_methods, price_values)}</div></div>
                        <label class="field field-wide"><span>תמונות חדשות</span><input type="file" name="images" accept="image/*" multiple></label>
                        <label class="field"><span>ערוץ לשליחה</span><select name="channel_id" required>{_render_channel_options(channels, selected_channel_id)}</select></label>
                        <label class="field"><span><input type="checkbox" name="replace_images" value="true"{' checked' if replace_images else ''}> החלף את כל התמונות הקיימות</span></label>
                    </div>
                    <div class="actions"><button type="submit">שמור שינויים</button><a class="link-button ghost-button" href="/admin/special-systems">חזרה לרשימה</a></div>
                </form>
            </div>
            <div class="card stack">
                <div><h2>תצוגה נוכחית</h2><p>אפשר להוסיף תמונות חדשות או להחליף את כל הגלריה הקיימת.</p></div>
                {gallery_html}
                <div class="actions">{'<a class="link-button ghost-button" href="' + _escape(public_url) + '" target="_blank" rel="noreferrer">פתח דף קניה</a>' if public_url else ''}{'<a class="link-button ghost-button" href="' + _escape(message_url) + '" target="_blank" rel="noreferrer">פתח הודעה בדיסקורד</a>' if message_url else ''}</div>
            </div>
        </div>
        """
        body = _admin_shell(session, title=f"עריכת מערכת מיוחדת #{current_system.id}", intro="עריכת פרטי המערכת המיוחדת ופרסום מחדש של ההודעה הציבורית לפי הצורך.", content=content)
        return _page_response(f"עריכת מערכת מיוחדת #{current_system.id}", body)
    except web.HTTPException:
        raise
    except SalesBotError as exc:
        return _error_response("עריכת מערכת מיוחדת", str(exc), status=400)


async def special_orders_list_page(request: web.Request) -> web.Response:
    try:
        bot, session = await _require_admin_session(request)
        status_filter = str(request.query.get("status", "all")).strip().lower()
        statuses = None if status_filter == "all" else (status_filter,)
        orders = await bot.services.special_systems.list_order_requests(statuses=statuses)
        systems = {item.id: item for item in await bot.services.special_systems.list_special_systems()}
        rows = "\n".join(
            f"""
            <tr>
                <td><strong>#{order.id}</strong></td>
                <td>{_escape(systems.get(order.special_system_id).title if systems.get(order.special_system_id) else f'#{order.special_system_id}')}</td>
                <td><span class="mono">{order.user_id}</span><br>{_escape(order.discord_name)}</td>
                <td>{_escape(order.payment_method_label)}<br>{_escape(order.payment_price)}</td>
                <td>{_status_badge(order.status)}</td>
                <td><a class="link-button ghost-button" href="/admin/special-orders/{order.id}">פתח</a></td>
            </tr>
            """
            for order in orders
        )
        content = f"""
        <div class="actions"><a class="link-button ghost-button" href="/admin/special-orders?status=all">הכל</a><a class="link-button ghost-button" href="/admin/special-orders?status=pending">ממתינות</a><a class="link-button ghost-button" href="/admin/special-orders?status=accepted">התקבלו</a><a class="link-button ghost-button" href="/admin/special-orders?status=rejected">נדחו</a></div>
        <div class="table-wrap"><table><thead><tr><th>#</th><th>מערכת</th><th>לקוח</th><th>תשלום</th><th>סטטוס</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>
        """
        body = _admin_shell(session, title="בקשות למערכות מיוחדות", intro="ריכוז כל הבקשות שהגיעו דרך דפי הקניה המיוחדים.", content=content)
        return _page_response("בקשות מיוחדות", body)
    except web.HTTPException:
        raise
    except SalesBotError as exc:
        return _error_response("בקשות מיוחדות", str(exc), status=400)


async def special_order_detail_page(request: web.Request) -> web.Response:
    notice: str | None = None
    success = True
    try:
        bot, session = await _require_admin_session(request)
        order_id = int(request.match_info["order_id"])
        order = await bot.services.special_systems.get_order_request(order_id)
        special_system = await bot.services.special_systems.get_special_system(order.special_system_id)
        if request.method == "POST" and order.status == "pending":
            form = await request.post()
            action = str(form.get("action", "")).strip()
            if action not in {"accept", "reject"}:
                raise PermissionDeniedError("הפעולה שנבחרה לא תקינה.")
            admin_reply = str(form.get("admin_reply", "")).strip() or None
            order = await bot.services.special_systems.resolve_order_request(order.id, reviewer_id=session.discord_user_id, status="accepted" if action == "accept" else "rejected", admin_reply=admin_reply)
            try:
                requester = await bot.fetch_user(order.user_id)
                if action == "accept":
                    await requester.send(admin_reply or "הבקשה שלך לקניית מערכת מיוחדת התקבלה.")
                else:
                    decline_message = "הבקשה שלך לקניית מערכת מיוחדת נדחתה"
                    if admin_reply:
                        decline_message += f"\n\n{admin_reply}"
                    await requester.send(decline_message)
            except discord.HTTPException:
                pass
            await _update_owner_order_message(bot, special_system, order)
            notice = "הבקשה עודכנה והלקוח קיבל הודעה ב-DM אם היה אפשר לשלוח לו."
        linked_roblox_label = "לא מחובר"
        if order.linked_roblox_sub:
            linked_roblox_label = " | ".join(part for part in (order.linked_roblox_display_name, order.linked_roblox_username, order.linked_roblox_sub) if part)
        buttons_html = ''
        if order.status == 'pending':
            buttons_html = '<button type="submit" name="action" value="accept">אשר בקשה</button><button type="submit" name="action" value="reject" class="ghost-button danger">דחה בקשה</button>'
        content = f"""
        {_notice_html(notice, success=success)}
        <div class="split-grid">
            <div class="card stack">
                <div><h2>פרטי הבקשה</h2></div>
                <div class="price-list">
                    <div class="price-item"><strong>מערכת מיוחדת</strong><span>{_escape(special_system.title)}</span></div>
                    <div class="price-item"><strong>סטטוס</strong><span>{_status_badge(order.status)}</span></div>
                    <div class="price-item"><strong>Discord</strong><span>{_escape(order.discord_name)}<br><span class="mono">{order.user_id}</span></span></div>
                    <div class="price-item"><strong>Roblox שנשלח</strong><span>{_escape(order.roblox_name)}</span></div>
                    <div class="price-item"><strong>שיטת תשלום</strong><span>{_escape(order.payment_method_label)} | {_escape(order.payment_price)}</span></div>
                    <div class="price-item"><strong>חשבון Roblox מחובר</strong><span>{_escape(linked_roblox_label)}</span></div>
                    <div class="price-item"><strong>נשלח בתאריך</strong><span>{_escape(order.submitted_at)}</span></div>
                </div>
            </div>
            <div class="card">
                <h2>טיפול בבקשה</h2>
                <form method="post">
                    <div class="grid"><label class="field field-wide"><span>הודעה ללקוח</span><textarea name="admin_reply" placeholder="הודעה שתישלח ללקוח אם תאשר, או סיבה אם תדחה.">{_escape(order.admin_reply or '')}</textarea></label></div>
                    <div class="actions">{buttons_html}<a class="link-button ghost-button" href="/admin/special-orders">חזרה לרשימה</a></div>
                </form>
            </div>
        </div>
        """
        body = _admin_shell(session, title=f"בקשה מיוחדת #{order.id}", intro="בדיקת כל הפרטים לפני אישור או דחייה של בקשת הקניה.", content=content)
        return _page_response(f"בקשה מיוחדת #{order.id}", body)
    except web.HTTPException:
        raise
    except SalesBotError as exc:
        return _error_response("פרטי בקשה מיוחדת", str(exc), status=400)


async def special_system_image_page(request: web.Request) -> web.Response:
    bot: SalesBot = request.app["bot"]
    try:
        image = await bot.services.special_systems.get_special_system_image(int(request.match_info["image_id"]))
        return web.Response(body=image.asset_bytes, content_type=image.content_type or "application/octet-stream")
    except SalesBotError as exc:
        return _error_response("תמונת מערכת מיוחדת", str(exc), status=404)


async def special_system_page(request: web.Request) -> web.Response:
    notice: str | None = None
    success = True
    selected_payment_method = ""
    discord_name = ""
    roblox_name = ""
    try:
        bot: SalesBot = request.app["bot"]
        special_system = await bot.services.special_systems.get_special_system_by_slug(request.match_info["slug"])
        images = await bot.services.special_systems.list_special_system_images(special_system.id)
        bot_ref, session = await _current_site_session(request)
        assert bot_ref is bot
        linked_account: RobloxLinkRecord | None = None
        if session is not None:
            discord_name = _session_label(session)
            try:
                linked_account = await bot.services.oauth.get_link(session.discord_user_id)
            except NotFoundError:
                linked_account = None
        if request.method == "POST":
            bot, session = await _require_site_session(request)
            form = await request.post()
            selected_payment_method = str(form.get("payment_method", "")).strip()
            discord_name = str(form.get("discord_name", "")).strip()
            roblox_name = str(form.get("roblox_name", "")).strip()
            if not discord_name or not roblox_name or not selected_payment_method:
                raise PermissionDeniedError("חובה למלא את כל השדות בטופס ההזמנה.")
            try:
                linked_account = await bot.services.oauth.get_link(session.discord_user_id)
            except NotFoundError:
                linked_account = None
            order = await bot.services.special_systems.create_order_request(special_system_id=special_system.id, user_id=session.discord_user_id, discord_name=discord_name, roblox_name=roblox_name, payment_method_key=selected_payment_method, linked_account=linked_account)
            owner = await bot.fetch_user(bot.settings.owner_user_id)
            owner_dm = owner.dm_channel or await owner.create_dm()
            owner_embed = await _owner_order_embed(special_system, order)
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="פתח את הבקשה באתר", style=discord.ButtonStyle.link, url=f"{bot.settings.public_base_url}/admin/special-orders/{order.id}"))
            owner_message = await owner_dm.send(content="יש בקשה לקניית מערכת מיוחדת חדשה", embed=owner_embed, view=view)
            await bot.services.special_systems.set_owner_message(order.id, owner_message.id)
            notice = "הבקשה נשלחה בהצלחה. נחזור אליך ב-DM אחרי שנבדוק אותה."
            success_html = f"""
            {_notice_html(notice, success=True)}
            <div class="card">
                <h2>הבקשה נשלחה</h2>
                <p>שלחנו לבעלים הודעה חדשה עם כל הפרטים, והבקשה מחכה עכשיו ברשימת האדמין.</p>
                <div class="actions">
                    <a class="link-button" href="/special-systems/{_escape(special_system.slug)}">שלח בקשה נוספת</a>
                </div>
            </div>
            """
            body = _public_shell(
                session,
                title=f"הזמנה מיוחדת - {special_system.title}",
                intro="הבקשה שלך התקבלה ונשמרה בבוט.",
                login_path=f"/special-systems/{special_system.slug}",
                content=success_html,
            )
            return _page_response(f"הזמנה מיוחדת - {special_system.title}", body)
        gallery_html = ""
        if images:
            gallery_html = '<div class="gallery">' + "".join(f'<img src="/special-system-images/{image.id}" alt="{_escape(image.asset_name)}">' for image in images) + "</div>"
        linked_label = "לא מחובר"
        if linked_account is not None:
            linked_label = " | ".join(part for part in (linked_account.roblox_display_name, linked_account.roblox_username, linked_account.roblox_sub) if part)
        content = f"""
        {_notice_html(notice, success=success)}
        <div class="split-grid">
            <div class="card stack">
                <div><h2>{_escape(special_system.title)}</h2><p>{_escape(special_system.description)}</p></div>
                <div><h3>אמצעי תשלום</h3><div class="price-list">{''.join(f'<div class="price-item"><strong>{_escape(method.label)}</strong><span>{_escape(method.price)}</span></div>' for method in special_system.payment_methods)}</div></div>
                {gallery_html}
            </div>
            <div class="card">
                <h2>טופס הזמנה</h2>
                <p class="muted">אפשר לשלוח בקשה גם בלי חשבון Roblox מחובר. אם כבר חיברת Roblox, נצרף אותו אוטומטית לבקשה.</p>
                <div class="meta-card"><p><strong>חשבון Roblox מחובר:</strong> {_escape(linked_label)}</p></div>
                <form method="post">
                    <div class="grid">
                        <label class="field field-wide"><span>איזה שיטת תשלום אתה משלם</span><select name="payment_method" required>{_payment_method_select_options(special_system, selected_payment_method)}</select></label>
                        <label class="field"><span>מה השם שלך ברובלוקס</span><input type="text" name="roblox_name" value="{_escape(roblox_name)}" required></label>
                        <label class="field"><span>מה השם שלך בדיסקורד</span><input type="text" name="discord_name" value="{_escape(discord_name)}" required></label>
                    </div>
                    <div class="actions"><button type="submit">שלח בקשה</button></div>
                </form>
            </div>
        </div>
        """
        body = _public_shell(
            session,
            title=f"הזמנה מיוחדת - {special_system.title}",
            intro="מלא את כל הפרטים כדי לשלוח בקשה חדשה לבוט. כל השדות חובה.",
            login_path=f"/special-systems/{special_system.slug}",
            content=content,
        )
        return _page_response(f"הזמנה מיוחדת - {special_system.title}", body)
    except web.HTTPException:
        raise
    except SalesBotError as exc:
        return _error_response("הזמנה מיוחדת", str(exc), status=400)