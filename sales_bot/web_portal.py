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
    OrderRequestRecord,
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

THEME_COOKIE_NAME = "magic_admin_theme"
THEME_LABELS = {
    "default": "ברירת מחדל",
    "dark": "כהה",
    "light": "בהיר",
}

ADMIN_NAV_SECTIONS = (
    (
        "ראשי",
        (
            {"label": "לוח ניהול", "href": "/admin", "matches": ("/admin",)},
            {"label": "אדמינים", "href": "/admin/admins", "matches": ("/admin/admins",)},
        ),
    ),
    (
        "יצירה",
        (
            {"label": "מערכות", "href": "/admin/systems", "matches": ("/admin/systems",)},
            {"label": "גיימפאסים", "href": "/admin/gamepasses", "matches": ("/admin/gamepasses",)},
            {"label": "מערכות מיוחדות", "href": "/admin/special-systems", "matches": ("/admin/special-systems",)},
        ),
    ),
    (
        "הזמנות",
        (
            {"label": "הזמנות אישיות", "href": "/admin/custom-orders", "matches": ("/admin/custom-orders",)},
            {"label": "הזמנות מיוחדות", "href": "/admin/special-orders", "matches": ("/admin/special-orders",)},
        ),
    ),
    (
        "אירועים",
        (
            {"label": "הגרלות", "href": "/admin/giveaways/new", "matches": ("/admin/giveaways",)},
            {"label": "סקרים", "href": "/admin/polls/new", "matches": ("/admin/polls",)},
            {"label": "אירועים", "href": "/admin/events/new", "matches": ("/admin/events",)},
        ),
    ),
    (
        "אחר",
        (
            {"label": "הגדרות", "href": "/admin/settings", "matches": ("/admin/settings",)},
            {"label": "התנתק", "href": "/auth/logout", "matches": (), "danger": True},
        ),
    ),
)


PORTAL_STYLE = """
<style>
.portal-root { display: flex; flex-direction: column; gap: 24px; }
.top-strip { display: flex; justify-content: space-between; gap: 14px; align-items: center; flex-wrap: wrap; }
.user-chip { display: inline-flex; align-items: center; gap: 12px; padding: 10px 16px; border-radius: 18px; background: var(--surface-strong); border: 1px solid var(--surface-border); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04); max-width: 100%; }
.user-chip div { min-width: 0; }
.user-chip img { width: 42px; height: 42px; border-radius: 14px; object-fit: cover; border: 1px solid var(--surface-border-strong); }
.admin-shell { gap: 22px; }
.admin-topbar { display: flex; justify-content: flex-start; direction: ltr; }
.user-chip-profile { direction: rtl; }
.admin-layout { display: grid; grid-template-columns: 1fr; grid-template-areas: "sidebar" "main"; gap: 20px; align-items: start; direction: rtl; }
.admin-sidebar { grid-area: sidebar; direction: rtl; }
.admin-sidebar-card { display: flex; flex-wrap: wrap; align-items: flex-start; gap: 18px; padding: 18px 20px; border-radius: 22px; background: var(--surface-card); border: 1px solid var(--surface-border); position: sticky; top: 18px; box-shadow: var(--shadow-md); }
.admin-sidebar-card p { margin: 0; }
.sidebar-copy { display: flex; flex-direction: column; gap: 8px; flex: 0 1 280px; min-width: 220px; }
.sidebar-copy .eyebrow { margin-bottom: 0; }
.sidebar-sections { display: flex; flex-wrap: wrap; gap: 12px 16px; flex: 1 1 680px; }
.nav-section { display: flex; flex-direction: column; gap: 8px; min-width: 180px; flex: 1 1 180px; }
.nav-section-title { color: var(--muted); font-size: 0.76rem; letter-spacing: 0.16em; text-transform: uppercase; }
.admin-main { grid-area: main; min-width: 0; display: flex; flex-direction: column; gap: 22px; direction: rtl; }
.admin-hero { position: relative; overflow: hidden; padding: 30px 32px 38px; border-radius: 24px; background: linear-gradient(135deg, var(--surface-hero-start) 0%, var(--surface-hero-end) 100%); border: 1px solid var(--surface-border-strong); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04); }
.admin-hero::after { content: ""; position: absolute; inset: auto 26px 20px; height: 2px; border-radius: 999px; background: linear-gradient(90deg, transparent 0%, var(--accent) 50%, transparent 100%); opacity: 0.9; }
.admin-hero h1 { margin-bottom: 12px; }
.admin-hero p:last-child { margin-bottom: 0; }
.nav-links { display: flex; flex-wrap: wrap; gap: 8px; }
.nav-links a { padding: 11px 16px; border-radius: 999px; background: var(--surface-soft); border: 1px solid var(--surface-border); text-decoration: none; color: var(--text); font-weight: 700; transition: background 0.18s ease, border-color 0.18s ease, transform 0.18s ease, color 0.18s ease, box-shadow 0.18s ease; }
.nav-links a:hover { background: var(--surface-strong); border-color: var(--accent-border); transform: translateY(-1px); }
.nav-links a.is-active { color: var(--button-text); background: linear-gradient(135deg, var(--accent) 0%, var(--accent-strong) 100%); border-color: transparent; box-shadow: 0 14px 24px rgba(19, 143, 208, 0.2); }
.nav-links a.danger-link { color: var(--danger); background: var(--danger-soft); border-color: var(--danger-border); }
.nav-links a.danger-link:hover { background: rgba(255, 133, 121, 0.18); border-color: rgba(255, 133, 121, 0.34); }
.hero-grid, .stat-grid, .split-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 18px; }
.card { padding: 24px; border-radius: 22px; background: var(--surface-card); border: 1px solid var(--surface-border); box-shadow: var(--shadow-md); }
.card h2, .card h3 { margin-top: 0; margin-bottom: 10px; }
.stat-value { font-size: clamp(2rem, 4vw, 2.75rem); font-weight: 700; color: var(--text); }
.table-wrap { overflow-x: auto; border-radius: 20px; border: 1px solid var(--surface-border); background: var(--surface-strong); }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 15px 17px; text-align: right; border-bottom: 1px solid var(--surface-border); vertical-align: top; }
th { color: var(--text); font-size: 0.95rem; background: rgba(255, 255, 255, 0.02); }
tbody tr:hover { background: rgba(255, 255, 255, 0.02); }
td strong { color: var(--text); }
.inline-form { display: inline-flex; gap: 10px; flex-wrap: wrap; align-items: center; margin: 0; }
.inline-form input, .inline-form select { width: auto; min-width: 120px; }
.stack { display: flex; flex-direction: column; gap: 14px; }
.badge { display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 999px; background: var(--success-soft); border: 1px solid var(--success-border); color: var(--success-text); font-size: 0.9rem; }
.badge.pending { background: var(--warning-soft); border-color: var(--warning-border); color: var(--warning-text); }
.badge.rejected { background: var(--danger-soft); border-color: var(--danger-border); color: var(--danger); }
.price-list { display: flex; flex-direction: column; gap: 10px; }
.price-item { display: flex; justify-content: space-between; gap: 10px; padding: 14px 16px; border-radius: 18px; background: var(--surface-strong); border: 1px solid var(--surface-border); }
.gallery { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; }
.gallery img { width: 100%; height: 180px; object-fit: cover; border-radius: 18px; border: 1px solid var(--surface-border); background: var(--surface-strong); }
.check-card { display: flex; flex-direction: column; gap: 10px; }
.check-line { display: flex; gap: 10px; align-items: center; color: var(--text); }
.check-line input { width: auto; }
.warning-note { color: #ff8579; font-weight: 700; }
.muted { color: var(--muted); }
.mono { font-family: Consolas, "Cascadia Mono", monospace; }
.table-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.table-actions form { margin: 0; }
.profile-grid { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(280px, 0.85fr); gap: 18px; }
.profile-hero { display: flex; gap: 18px; align-items: center; }
.profile-avatar { width: 74px; height: 74px; border-radius: 22px; object-fit: cover; border: 1px solid var(--surface-border-strong); background: var(--surface-strong); }
.settings-list { display: flex; flex-direction: column; gap: 12px; }
.setting-hint { margin: 0; }
@media (max-width: 1100px) {
    .admin-sidebar-card { position: static; }
    .profile-grid { grid-template-columns: 1fr; }
    .sidebar-copy { flex-basis: 100%; max-width: none; }
}
@media (max-width: 700px) {
    .top-strip { align-items: stretch; }
    .admin-topbar { justify-content: stretch; }
    .user-chip-profile { width: 100%; }
    .admin-sidebar-card { padding: 16px; }
    .sidebar-sections { flex-direction: column; }
    .nav-section { width: 100%; }
    .nav-links { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .nav-links a { display: flex; align-items: center; justify-content: center; min-height: 46px; text-align: center; }
    .profile-hero { flex-direction: column; align-items: flex-start; }
    .price-item { flex-direction: column; }
    .admin-hero { padding: 24px 22px 30px; }
}
</style>
"""

ORDER_STATUS_LABELS = {
    "pending": "ממתינה",
    "accepted": "התקבלה",
    "rejected": "נדחתה",
    "completed": "הושלמה",
}


def _page_response(title: str, body: str) -> web.Response:
    return admin_html_response(title, PORTAL_STYLE + body)


def _theme_mode_from_request(request: web.Request) -> str:
    theme_mode = str(request.cookies.get(THEME_COOKIE_NAME, "default") or "default").strip().lower()
    if theme_mode not in THEME_LABELS:
        return "default"
    return theme_mode


def _set_theme_cookie(response: web.StreamResponse, theme_mode: str, *, secure: bool) -> None:
    response.set_cookie(
        THEME_COOKIE_NAME,
        theme_mode,
        max_age=365 * 24 * 60 * 60,
        httponly=False,
        secure=secure,
        samesite="Lax",
        path="/",
    )


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


def _nav_item_is_active(current_path: str, matches: tuple[str, ...]) -> bool:
    return any(current_path == value or current_path.startswith(f"{value}/") for value in matches)


def _admin_nav_html(current_path: str) -> str:
    sections: list[str] = []
    for section_label, items in ADMIN_NAV_SECTIONS:
        links: list[str] = []
        for item in items:
            classes: list[str] = []
            matches = tuple(item.get("matches", ()))
            if matches and _nav_item_is_active(current_path, matches):
                classes.append("is-active")
            if item.get("danger"):
                classes.append("danger-link")
            class_attr = f' class="{" ".join(classes)}"' if classes else ""
            links.append(f'<a href="{_escape(item["href"])}"{class_attr}>{_escape(item["label"])}</a>')
        sections.append(
            f"""
            <section class="nav-section">
                <span class="nav-section-title">{_escape(section_label)}</span>
                <div class="nav-links">{''.join(links)}</div>
            </section>
            """
        )
    return '<div class="sidebar-sections">' + ''.join(sections) + '</div>'


def _admin_rank_label(bot: "SalesBot", user_id: int) -> str:
    return "בעלים" if user_id == bot.settings.owner_user_id else "אדמין"


def _theme_options(selected_theme: str) -> str:
    return "\n".join(
        f'<option value="{value}"{" selected" if value == selected_theme else ""}>{_escape(label)}</option>'
        for value, label in THEME_LABELS.items()
    )


def _admin_shell(
    session: WebsiteSessionRecord,
    *,
    current_path: str,
    title: str,
    intro: str,
    content: str,
) -> str:
    avatar_url = _session_avatar(session)
    avatar_html = f'<img src="{_escape(avatar_url)}" alt="avatar">' if avatar_url else ""
    return f"""
    <div class="portal-root admin-shell" dir="rtl">
        <div class="admin-topbar">
            <div class="user-chip user-chip-profile">
                {avatar_html}
                <div>
                    <strong>{_escape(_session_label(session))}</strong><br>
                    <span class="muted mono">{_escape(session.discord_user_id)}</span>
                </div>
            </div>
        </div>
        <div class="admin-layout">
            <aside class="admin-sidebar">
                <div class="admin-sidebar-card">
                    <div class="sidebar-copy">
                        <p class="eyebrow">ניווט מהיר</p>
                        <p>חלוקה לפי אזורים כדי לעבור בין ניהול, יצירה, הזמנות והגדרות בלי שורת כפתורים צפופה.</p>
                    </div>
                    {_admin_nav_html(current_path)}
                </div>
            </aside>
            <div class="admin-main">
                <div class="admin-hero">
                    <p class="eyebrow">אתר ניהול</p>
                    <h1>{_escape(title)}</h1>
                    <p>{_escape(intro)}</p>
                </div>
                {content}
            </div>
        </div>
    </div>
    """


def _public_shell(
    session: WebsiteSessionRecord | None,
    *,
    title: str,
    intro: str,
    login_path: str,
    section_label: str = "מערכות מיוחדות",
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
                <p class="eyebrow">{_escape(section_label)}</p>
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


def _order_payment_method_select_options(order_service: Any, selected_key: str | None = None) -> str:
    normalized = (selected_key or "").strip()
    options = ['<option value="">בחר שיטת תשלום</option>']
    for key, label in order_service.available_payment_methods():
        selected = " selected" if normalized in {key, label} else ""
        options.append(f'<option value="{_escape(key)}"{selected}>{_escape(label)}</option>')
    return "\n".join(options)


def _yes_no_select_options(selected_value: str | None = None) -> str:
    normalized = (selected_value or "").strip().lower()
    options = ['<option value="">בחר</option>']
    for value, label in (("yes", "כן"), ("no", "לא")):
        selected = " selected" if normalized == value else ""
        options.append(f'<option value="{value}"{selected}>{label}</option>')
    return "\n".join(options)


def _special_system_url(bot: "SalesBot", special_system: SpecialSystemRecord) -> str:
    return f"{bot.settings.public_base_url}/special-systems/{special_system.slug}"


def _custom_order_admin_url(bot: "SalesBot", order_id: int) -> str:
    return f"{bot.settings.public_base_url}/admin/custom-orders/{order_id}"


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


async def _owner_custom_order_embed(bot: "SalesBot", order: OrderRequestRecord) -> discord.Embed:
    requester_label = await _discord_user_label(bot, order.user_id)
    embed = discord.Embed(title="יש הזמנה אישית חדשה", color=discord.Color.gold())
    embed.add_field(name="משתמש Discord", value=f"<@{order.user_id}>\n{requester_label}\n{order.user_id}", inline=False)
    embed.add_field(name="מה אתה רוצה להזמין", value=order.requested_item, inline=False)
    embed.add_field(name="תוך כמה זמן אתה צריך את זה", value=order.required_timeframe, inline=False)
    embed.add_field(name="איך אתה משלם", value=order.payment_method, inline=False)
    embed.add_field(name="כמה אתה מוכן לשלם", value=order.offered_price, inline=False)
    embed.add_field(name="מה השם שלך ברובלוקס", value=order.roblox_username or "לא צוין", inline=False)
    embed.add_field(name="סטטוס", value=ORDER_STATUS_LABELS.get(order.status, order.status), inline=False)
    if order.admin_reply:
        note_label = "סיבת דחייה" if order.status == "rejected" else "הודעת אדמין"
        embed.add_field(name=note_label, value=order.admin_reply, inline=False)
    embed.set_footer(text=f"הזמנה #{order.id}")
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


async def _update_owner_custom_order_message(bot: "SalesBot", order: OrderRequestRecord) -> None:
    if order.owner_message_id is None:
        return
    try:
        owner = await bot.fetch_user(bot.settings.owner_user_id)
        owner_dm = owner.dm_channel or await owner.create_dm()
        message = await owner_dm.fetch_message(order.owner_message_id)
        embed = await _owner_custom_order_embed(bot, order)
        view = discord.ui.View()
        view.add_item(
            discord.ui.Button(
                label="פתח את ההזמנה באתר",
                style=discord.ButtonStyle.link,
                url=_custom_order_admin_url(bot, order.id),
            )
        )
        await message.edit(content="עדכון סטטוס להזמנה אישית", embed=embed, view=view)
    except discord.HTTPException:
        return


async def _notify_custom_order_requester(
    bot: "SalesBot",
    order: OrderRequestRecord,
    *,
    admin_reply: str | None,
) -> None:
    try:
        requester = await bot.fetch_user(order.user_id)
    except discord.HTTPException:
        return

    if order.status == "accepted":
        message = "ההזמנה האישית שלך התקבלה. הבעלים יחזור אליך בהמשך."
    elif order.status == "rejected":
        message = "ההזמנה האישית שלך נדחתה."
    elif order.status == "completed":
        message = "ההזמנה שלך הושלמה בהצלחה. נשמח מאוד שתשאיר הוכחה באמצעות הפקודה: '/Vouch'. זה יוערך מאוד."
    else:
        return

    if admin_reply:
        if order.status == "rejected":
            message = f"{message}\n\nסיבה: {admin_reply}"
        else:
            message = f"{message}\n\n{admin_reply}"

    try:
        await requester.send(message)
    except discord.HTTPException:
        return


async def _send_account_payment_submission_to_admins(
    bot: "SalesBot",
    *,
    session: WebsiteSessionRecord,
    roblox_username: str,
    roblox_password: str,
    profile_link: str | None,
    profile_image: tuple[str, bytes, str | None] | None,
    has_email: bool,
    has_phone: bool,
    has_two_factor: bool,
) -> int:
    admin_ids = list(dict.fromkeys(await bot.services.admins.list_admin_ids()))
    sender_label = _session_label(session)
    successful_deliveries = 0

    for admin_id in admin_ids:
        try:
            admin_user = bot.get_user(admin_id) or await bot.fetch_user(admin_id)
            admin_dm = admin_user.dm_channel or await admin_user.create_dm()
        except discord.HTTPException:
            continue

        embed = discord.Embed(title="נשלח משתמש Roblox בתור תשלום", color=discord.Color.orange())
        embed.add_field(name="שולח", value=f"{sender_label}\n{session.discord_user_id}", inline=False)
        embed.add_field(name="השם של המשתמש רובלוקס", value=roblox_username, inline=False)
        embed.add_field(name="סיסמא של המשתמש רובלוקס", value=roblox_password, inline=False)
        embed.add_field(name="קישור לפרופיל", value=profile_link or "לא נשלח", inline=False)
        embed.add_field(name="האם יש על המשתמש מייל", value="כן" if has_email else "לא", inline=True)
        embed.add_field(name="האם יש מספר טלפון על המשתמש", value="כן" if has_phone else "לא", inline=True)
        embed.add_field(name="האם יש אימות דו שלבי", value="כן" if has_two_factor else "לא", inline=True)
        embed.set_footer(text="המשתמש אישר שכל הפרטים נכונים ושהחשבון לא יחזור אליו לאחר מכן.")

        send_kwargs: dict[str, Any] = {"embed": embed}
        if profile_link:
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="פתח את הפרופיל", style=discord.ButtonStyle.link, url=profile_link))
            send_kwargs["view"] = view
        if profile_image is not None:
            image_name, image_bytes, _content_type = profile_image
            safe_name = image_name or "profile-image"
            send_kwargs["file"] = discord.File(BytesIO(image_bytes), filename=safe_name)
            embed.set_image(url=f"attachment://{safe_name}")

        try:
            await admin_dm.send(**send_kwargs)
            successful_deliveries += 1
        except discord.HTTPException:
            continue

    return successful_deliveries


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


async def admin_settings_page(request: web.Request) -> web.Response:
    try:
        bot, session = await _require_admin_session(request)
        if request.method == "POST":
            form = await request.post()
            action = str(form.get("action", "")).strip().lower()
            if action != "save-theme":
                raise PermissionDeniedError("הפעולה שנשלחה להגדרות לא תקינה.")
            theme_mode = str(form.get("theme_mode", "default")).strip().lower()
            if theme_mode not in THEME_LABELS:
                raise PermissionDeniedError("מצב התצוגה שנבחר לא תקין.")
            response = web.HTTPFound("/admin/settings?saved=theme")
            _set_theme_cookie(response, theme_mode, secure=bot.settings.public_base_url.startswith("https://"))
            return response

        notice = "ערכת הנושא עודכנה בהצלחה." if request.query.get("saved") == "theme" else None
        theme_mode = _theme_mode_from_request(request)
        avatar_url = _session_avatar(session)
        avatar_html = f'<img class="profile-avatar" src="{_escape(avatar_url)}" alt="avatar">' if avatar_url else '<div class="profile-avatar"></div>'
        try:
            roblox_link = await bot.services.oauth.get_link(session.discord_user_id)
        except SalesBotError:
            roblox_link = None

        if roblox_link is None:
            roblox_profile = '<div class="price-item"><strong>Roblox</strong><span>אין חשבון Roblox מחובר כרגע.</span></div>'
        else:
            roblox_parts = [part for part in (roblox_link.roblox_display_name, roblox_link.roblox_username, roblox_link.roblox_sub) if part]
            roblox_summary = " | ".join(roblox_parts) if roblox_parts else roblox_link.roblox_sub
            profile_link_html = f'<a href="{_escape(roblox_link.profile_url)}" target="_blank" rel="noreferrer">פתח פרופיל</a>' if roblox_link.profile_url else 'אין קישור פרופיל'
            roblox_profile = f"""
            <div class="price-item"><strong>Roblox</strong><span>{_escape(roblox_summary)}</span></div>
            <div class="price-item"><strong>קישור</strong><span>{profile_link_html}</span></div>
            <div class="price-item"><strong>קושר בתאריך</strong><span>{_escape(roblox_link.linked_at)}</span></div>
            """

        content = f"""
        {_notice_html(notice, success=True)}
        <div class="profile-grid">
            <div class="card stack">
                <div class="profile-hero">
                    {avatar_html}
                    <div>
                        <p class="eyebrow">הפרופיל שלך</p>
                        <h2>{_escape(_session_label(session))}</h2>
                        <p class="muted">פרטי Discord, חיבור Roblox קיים והדרגה של החשבון שמחובר כרגע לאתר.</p>
                    </div>
                </div>
                <div class="price-list">
                    <div class="price-item"><strong>Discord</strong><span>{_escape(_session_label(session))}</span></div>
                    <div class="price-item"><strong>User ID</strong><span class="mono">{_escape(session.discord_user_id)}</span></div>
                    <div class="price-item"><strong>דרגה</strong><span>{_escape(_admin_rank_label(bot, session.discord_user_id))}</span></div>
                    <div class="price-item"><strong>סשן נוצר</strong><span>{_escape(session.created_at)}</span></div>
                    <div class="price-item"><strong>נראה לאחרונה</strong><span>{_escape(session.last_seen_at)}</span></div>
                    {roblox_profile}
                </div>
            </div>
            <div class="card stack">
                <div>
                    <p class="eyebrow">מראה האתר</p>
                    <h2>ערכת נושא</h2>
                    <p class="setting-hint">ברירת מחדל שומרת על הסגנון הנוכחי, כהה מוסיפה יותר ניגודיות, ובהיר מתאים לעבודה ביום.</p>
                </div>
                <form method="post" class="settings-list">
                    <input type="hidden" name="action" value="save-theme">
                    <label class="field"><span>מצב תצוגה</span><select name="theme_mode">{_theme_options(theme_mode)}</select></label>
                    <div class="actions"><button type="submit">שמור העדפה</button></div>
                </form>
                <div class="price-list">
                    <div class="price-item"><strong>ברירת מחדל</strong><span>המראה הרגיל של האתר.</span></div>
                    <div class="price-item"><strong>כהה</strong><span>רקע עמוק יותר וניגודיות חזקה יותר.</span></div>
                    <div class="price-item"><strong>בהיר</strong><span>תצוגה בהירה לקריאה נוחה על מסכים מוארים.</span></div>
                </div>
            </div>
        </div>
        """
        body = _admin_shell(session, current_path=request.path, title="הגדרות", intro="ניהול פרטי החשבון המחובר והעדפת התצוגה של האתר.", content=content)
        return _page_response("הגדרות", body)
    except web.HTTPException:
        raise
    except SalesBotError as exc:
        return _error_response("הגדרות", str(exc), status=400)


async def admin_dashboard_page(request: web.Request) -> web.Response:
    try:
        bot, session = await _require_admin_session(request)
        (
            admin_ids,
            systems,
            pending_custom_orders,
            special_systems,
            rollable_events,
            pending_special_orders,
        ) = await asyncio.gather(
            bot.services.admins.list_admin_ids(),
            bot.services.systems.list_systems(),
            bot.services.orders.list_requests(statuses=("pending",)),
            bot.services.special_systems.list_special_systems(active_only=True),
            bot.services.events.list_rollable_events(),
            bot.services.special_systems.list_order_requests(statuses=("pending",)),
        )
        stats = f"""
        <div class="stat-grid">
            <div class="card"><h2>אדמינים</h2><div class="stat-value">{len(admin_ids)}</div></div>
            <div class="card"><h2>מערכות</h2><div class="stat-value">{len(systems)}</div></div>
            <div class="card"><h2>הזמנות אישיות ממתינות</h2><div class="stat-value">{len(pending_custom_orders)}</div></div>
            <div class="card"><h2>מערכות מיוחדות</h2><div class="stat-value">{len(special_systems)}</div></div>
            <div class="card"><h2>אירועים פתוחים</h2><div class="stat-value">{len(rollable_events)}</div></div>
            <div class="card"><h2>בקשות ממתינות</h2><div class="stat-value">{len(pending_special_orders)}</div></div>
        </div>
        """
        quick_links = """
        <div class="hero-grid">
            <div class="card"><h3>ניהול אדמינים</h3><p>הוספה והסרה של צוות הניהול מתוך האתר.</p><div class="actions"><a class="link-button" href="/admin/admins">פתח</a></div></div>
            <div class="card"><h3>הזמנות אישיות</h3><p>רשימת כל ההזמנות האישיות, צפייה בפרטים, אישור, דחייה וסימון כהושלמה.</p><div class="actions"><a class="link-button" href="/admin/custom-orders">פתח</a></div></div>
            <div class="card"><h3>מערכות רגילות</h3><p>יצירת מערכות, עריכה, מחיקה ומתן או הסרה לפי User ID.</p><div class="actions"><a class="link-button" href="/admin/systems">פתח</a></div></div>
            <div class="card"><h3>גיימפאסים</h3><p>יצירה, עדכון, קישור ושליחה של גיימפאסים ישירות מתוך האתר.</p><div class="actions"><a class="link-button" href="/admin/gamepasses">פתח</a></div></div>
            <div class="card"><h3>מערכות מיוחדות</h3><p>פרסום מערכת מיוחדת עם כפתור קניה, תמונות, מחירים ושיטות תשלום.</p><div class="actions"><a class="link-button" href="/admin/special-systems">פתח</a></div></div>
            <div class="card"><h3>בקשות מיוחדות</h3><p>רשימת כל הבקשות, צפייה בפרטים, אישור או דחייה עם הודעה חזרה.</p><div class="actions"><a class="link-button" href="/admin/special-orders">פתח</a></div></div>
            <div class="card"><h3>כלי תוכן קיימים</h3><p>הפאנלים הקיימים של סקרים, הגרלות ואירועים נשארו זמינים גם דרך האתר.</p><div class="actions"><a class="link-button" href="/admin/polls/new">סקרים</a><a class="link-button ghost-button" href="/admin/giveaways/new">הגרלות</a><a class="link-button ghost-button" href="/admin/events/new">אירועים</a></div></div>
            <div class="card"><h3>הגדרות אישיות</h3><p>פרטי החשבון המחובר, הדרגה שלך והעדפת ערכת הנושא של האתר.</p><div class="actions"><a class="link-button" href="/admin/settings">פתח</a></div></div>
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
        body = _admin_shell(session, current_path=request.path, title="לוח ניהול ראשי", intro="כלי האתר מרוכזים כאן. כל דף משתמש באותם שירותים של פקודות הסלאש.", content=stats + quick_links + config_html)
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
        body = _admin_shell(session, current_path=request.path, title="ניהול אדמינים", intro="ניהול רשימת האדמינים של הבוט מתוך האתר.", content=content)
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
        body = _admin_shell(session, current_path=request.path, title="ניהול מערכות", intro="יצירה, עריכה, מחיקה ומתן/הסרה של מערכות דרך האתר.", content=content)
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
        body = _admin_shell(session, current_path=request.path, title="ניהול גיימפאסים", intro="אותם כלים של owner gamepass commands, עכשיו דרך האתר.", content=content)
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
        body = _admin_shell(session, current_path=request.path, title="מערכות מיוחדות", intro="יצירת דף קניה מיוחד עם תמונות, מחירים וכפתור קניה יעודי.", content=content)
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
        body = _admin_shell(session, current_path=request.path, title=f"עריכת מערכת מיוחדת #{current_system.id}", intro="עריכת פרטי המערכת המיוחדת ופרסום מחדש של ההודעה הציבורית לפי הצורך.", content=content)
        return _page_response(f"עריכת מערכת מיוחדת #{current_system.id}", body)
    except web.HTTPException:
        raise
    except SalesBotError as exc:
        return _error_response("עריכת מערכת מיוחדת", str(exc), status=400)


async def special_orders_list_page(request: web.Request) -> web.Response:
    try:
        bot, session = await _require_admin_session(request)
        notice: str | None = None
        if request.method == "POST":
            form = await request.post()
            action = str(form.get("action", "")).strip().lower()
            if action != "delete":
                raise PermissionDeniedError("הפעולה שנשלחה לבקשות המיוחדות לא תקינה.")
            order_id = _parse_positive_int(form.get("order_id"), "מזהה בקשה")
            assert order_id is not None
            deleted = await bot.services.special_systems.delete_order_request(order_id)
            notice = f"בקשה מיוחדת #{deleted.id} נמחקה ממסד הנתונים."
        elif str(request.query.get("deleted", "")).strip().isdigit():
            notice = f"בקשה מיוחדת #{_escape(request.query.get('deleted'))} נמחקה ממסד הנתונים."
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
                <td><div class="table-actions"><a class="link-button ghost-button" href="/admin/special-orders/{order.id}">פתח</a><form method="post" class="inline-form"><input type="hidden" name="action" value="delete"><input type="hidden" name="order_id" value="{order.id}"><button type="submit" class="ghost-button danger">מחק</button></form></div></td>
            </tr>
            """
            for order in orders
        )
        if not rows:
            rows = '<tr><td colspan="6">אין כרגע בקשות שתואמות למסנן שבחרת.</td></tr>'
        content = f"""
        {_notice_html(notice, success=True)}
        <div class="actions"><a class="link-button ghost-button" href="/admin/special-orders?status=all">הכל</a><a class="link-button ghost-button" href="/admin/special-orders?status=pending">ממתינות</a><a class="link-button ghost-button" href="/admin/special-orders?status=accepted">התקבלו</a><a class="link-button ghost-button" href="/admin/special-orders?status=rejected">נדחו</a></div>
        <div class="table-wrap"><table><thead><tr><th>#</th><th>מערכת</th><th>לקוח</th><th>תשלום</th><th>סטטוס</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>
        """
        body = _admin_shell(session, current_path=request.path, title="בקשות למערכות מיוחדות", intro="ריכוז כל הבקשות שהגיעו דרך דפי הקניה המיוחדים.", content=content)
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
        if request.method == "POST":
            form = await request.post()
            action = str(form.get("action", "")).strip()
            if action == "delete":
                deleted = await bot.services.special_systems.delete_order_request(order.id)
                raise web.HTTPFound(f"/admin/special-orders?deleted={deleted.id}")
            if action not in {"accept", "reject"}:
                raise PermissionDeniedError("הפעולה שנבחרה לא תקינה.")
            if order.status != "pending":
                raise PermissionDeniedError("אפשר לאשר או לדחות רק בקשה שעדיין ממתינה לטיפול.")
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
        buttons_html = '<button type="submit" name="action" value="delete" class="ghost-button danger">מחק בקשה</button>'
        if order.status == 'pending':
            buttons_html = '<button type="submit" name="action" value="accept">אשר בקשה</button><button type="submit" name="action" value="reject" class="ghost-button danger">דחה בקשה</button>' + buttons_html
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
        body = _admin_shell(session, current_path=request.path, title=f"בקשה מיוחדת #{order.id}", intro="בדיקת כל הפרטים לפני אישור, דחייה או מחיקה של בקשת הקניה.", content=content)
        return _page_response(f"בקשה מיוחדת #{order.id}", body)
    except web.HTTPException:
        raise
    except SalesBotError as exc:
        return _error_response("פרטי בקשה מיוחדת", str(exc), status=400)


async def custom_orders_list_page(request: web.Request) -> web.Response:
    try:
        bot, session = await _require_admin_session(request)
        notice: str | None = None
        if request.method == "POST":
            form = await request.post()
            action = str(form.get("action", "")).strip().lower()
            if action != "delete":
                raise PermissionDeniedError("הפעולה שנשלחה להזמנות האישיות לא תקינה.")
            order_id = _parse_positive_int(form.get("order_id"), "מזהה הזמנה")
            assert order_id is not None
            deleted = await bot.services.orders.delete_request(order_id)
            notice = f"הזמנה אישית #{deleted.id} נמחקה ממסד הנתונים."
        elif str(request.query.get("deleted", "")).strip().isdigit():
            notice = f"הזמנה אישית #{_escape(request.query.get('deleted'))} נמחקה ממסד הנתונים."
        status_filter = str(request.query.get("status", "all")).strip().lower()
        statuses = None if status_filter == "all" else (status_filter,)
        orders = await bot.services.orders.list_requests(statuses=statuses)
        requester_labels = await asyncio.gather(*(_discord_user_label(bot, order.user_id) for order in orders)) if orders else []
        rows = "\n".join(
            f"""
            <tr>
                <td><strong>#{order.id}</strong></td>
                <td>{_escape(requester_label)}<br><span class="mono">{order.user_id}</span></td>
                <td><strong>{_escape(order.requested_item)}</strong><br><span class="muted">{_escape(order.required_timeframe)}</span></td>
                <td>{_escape(order.payment_method)}<br>{_escape(order.offered_price)}</td>
                <td>{_escape(order.roblox_username or 'לא צוין')}</td>
                <td>{_status_badge(order.status)}</td>
                <td><div class="table-actions"><a class="link-button ghost-button" href="/admin/custom-orders/{order.id}">פתח</a><form method="post" class="inline-form"><input type="hidden" name="action" value="delete"><input type="hidden" name="order_id" value="{order.id}"><button type="submit" class="ghost-button danger">מחק</button></form></div></td>
            </tr>
            """
            for order, requester_label in zip(orders, requester_labels)
        )
        if not rows:
            rows = '<tr><td colspan="7">אין כרגע הזמנות שתואמות למסנן שבחרת.</td></tr>'
        content = f"""
        {_notice_html(notice, success=True)}
        <div class="actions"><a class="link-button ghost-button" href="/admin/custom-orders?status=all">הכל</a><a class="link-button ghost-button" href="/admin/custom-orders?status=pending">ממתינות</a><a class="link-button ghost-button" href="/admin/custom-orders?status=accepted">התקבלו</a><a class="link-button ghost-button" href="/admin/custom-orders?status=completed">הושלמו</a><a class="link-button ghost-button" href="/admin/custom-orders?status=rejected">נדחו</a></div>
        <div class="table-wrap"><table><thead><tr><th>#</th><th>לקוח</th><th>מה הוזמן</th><th>תשלום</th><th>Roblox</th><th>סטטוס</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>
        """
        body = _admin_shell(session, current_path=request.path, title="הזמנות אישיות", intro="ריכוז כל ההזמנות האישיות שנשלחו דרך דף האתר החדש.", content=content)
        return _page_response("הזמנות אישיות", body)
    except web.HTTPException:
        raise
    except SalesBotError as exc:
        return _error_response("הזמנות אישיות", str(exc), status=400)


async def custom_order_detail_page(request: web.Request) -> web.Response:
    notice: str | None = None
    success = True
    try:
        bot, session = await _require_admin_session(request)
        order_id = int(request.match_info["order_id"])
        order = await bot.services.orders.get_request(order_id)

        if request.method == "POST":
            form = await request.post()
            action = str(form.get("action", "")).strip().lower()
            if action == "delete":
                deleted = await bot.services.orders.delete_request(order.id)
                raise web.HTTPFound(f"/admin/custom-orders?deleted={deleted.id}")
            if action not in {"accept", "reject", "complete"}:
                raise PermissionDeniedError("הפעולה שנבחרה להזמנה האישית לא תקינה.")
            if order.status in {"rejected", "completed"}:
                raise PermissionDeniedError("אי אפשר לשנות הזמנה שכבר נדחתה או הושלמה.")
            if order.status == "pending" and action == "complete":
                raise PermissionDeniedError("אפשר לסמן כהושלמה רק הזמנה שכבר התקבלה.")

            admin_reply = str(form.get("admin_reply", "")).strip() or None
            target_status = {
                "accept": "accepted",
                "reject": "rejected",
                "complete": "completed",
            }[action]
            order = await bot.services.orders.resolve_request(
                order.id,
                reviewer_id=session.discord_user_id,
                status=target_status,
                admin_reply=admin_reply,
            )
            await _notify_custom_order_requester(bot, order, admin_reply=admin_reply)
            await _update_owner_custom_order_message(bot, order)
            notice = {
                "accept": "ההזמנה התקבלה והלקוח קיבל עדכון ב-DM אם היה אפשר לשלוח.",
                "reject": "ההזמנה נדחתה והלקוח קיבל את הסיבה ב-DM אם היה אפשר לשלוח.",
                "complete": "ההזמנה סומנה כהושלמה והלקוח קיבל עדכון ב-DM אם היה אפשר לשלוח.",
            }[action]

        requester_label = await _discord_user_label(bot, order.user_id)
        reviewer_label = await _discord_user_label(bot, order.reviewed_by) if order.reviewed_by is not None else None
        admin_note_label = ""
        if order.admin_reply:
            admin_note_label = "סיבת דחייה" if order.status == "rejected" else "הודעת אדמין"

        buttons_html = ""
        if order.status == "pending":
            buttons_html = '<button type="submit" name="action" value="accept">אשר הזמנה</button><button type="submit" name="action" value="reject" class="ghost-button danger">דחה הזמנה</button>'
        elif order.status == "accepted":
            buttons_html = '<button type="submit" name="action" value="complete">סמן כהושלמה</button><button type="submit" name="action" value="reject" class="ghost-button danger">דחה הזמנה</button>'

        review_meta = ""
        if order.reviewed_at:
            review_meta = f'<div class="price-item"><strong>טופלה בתאריך</strong><span>{_escape(order.reviewed_at)}</span></div>'
        if reviewer_label is not None:
            review_meta += f'<div class="price-item"><strong>טופלה על ידי</strong><span>{_escape(reviewer_label)}<br><span class="mono">{order.reviewed_by}</span></span></div>'
        if order.admin_reply and admin_note_label:
            review_meta += f'<div class="price-item"><strong>{_escape(admin_note_label)}</strong><span>{_escape(order.admin_reply)}</span></div>'

        delete_button_html = '<button type="submit" name="action" value="delete" class="ghost-button danger">מחק הזמנה</button>'
        content = f"""
        {_notice_html(notice, success=success)}
        <div class="split-grid">
            <div class="card stack">
                <div><h2>פרטי ההזמנה</h2></div>
                <div class="price-list">
                    <div class="price-item"><strong>סטטוס</strong><span>{_status_badge(order.status)}</span></div>
                    <div class="price-item"><strong>Discord</strong><span>{_escape(requester_label)}<br><span class="mono">{order.user_id}</span></span></div>
                    <div class="price-item"><strong>מה הוזמן</strong><span>{_escape(order.requested_item)}</span></div>
                    <div class="price-item"><strong>דדליין שביקש הלקוח</strong><span>{_escape(order.required_timeframe)}</span></div>
                    <div class="price-item"><strong>שיטת תשלום</strong><span>{_escape(order.payment_method)}</span></div>
                    <div class="price-item"><strong>הצעת מחיר / תמורה</strong><span>{_escape(order.offered_price)}</span></div>
                    <div class="price-item"><strong>שם Roblox</strong><span>{_escape(order.roblox_username or 'לא צוין')}</span></div>
                    <div class="price-item"><strong>נשלח בתאריך</strong><span>{_escape(order.submitted_at)}</span></div>
                    {review_meta}
                </div>
            </div>
            <div class="card">
                <h2>טיפול בהזמנה</h2>
                <form method="post">
                    <div class="grid"><label class="field field-wide"><span>הודעה ללקוח</span><textarea name="admin_reply" placeholder="הודעה שתישלח ללקוח אם תאשר, תדחה או תסמן כהושלמה.">{_escape(order.admin_reply or '')}</textarea></label></div>
                    <div class="actions">{buttons_html}{delete_button_html}<a class="link-button ghost-button" href="/admin/custom-orders">חזרה לרשימה</a></div>
                </form>
            </div>
        </div>
        """
        body = _admin_shell(session, current_path=request.path, title=f"הזמנה אישית #{order.id}", intro="בדיקה, אישור, דחייה, סיום או מחיקה של הזמנה אישית שנשלחה מהאתר.", content=content)
        return _page_response(f"הזמנה אישית #{order.id}", body)
    except web.HTTPException:
        raise
    except SalesBotError as exc:
        return _error_response("פרטי הזמנה אישית", str(exc), status=400)


async def special_system_image_page(request: web.Request) -> web.Response:
    bot: SalesBot = request.app["bot"]
    try:
        image = await bot.services.special_systems.get_special_system_image(int(request.match_info["image_id"]))
        return web.Response(body=image.asset_bytes, content_type=image.content_type or "application/octet-stream")
    except SalesBotError as exc:
        return _error_response("תמונת מערכת מיוחדת", str(exc), status=404)


async def custom_orders_page(request: web.Request) -> web.Response:
    notice: str | None = None
    success = True
    requested_item = ""
    required_timeframe = ""
    selected_payment_method = ""
    offered_price = ""
    roblox_username = ""
    try:
        bot_ref, session = await _current_site_session(request)
        bot = bot_ref

        if request.method == "POST":
            try:
                bot, session = await _require_site_session(request)
                form = await request.post()
                requested_item = str(form.get("requested_item", "")).strip()
                required_timeframe = str(form.get("required_timeframe", "")).strip()
                selected_payment_method = str(form.get("payment_method", "")).strip()
                offered_price = str(form.get("offered_price", "")).strip()
                roblox_username = str(form.get("roblox_username", "")).strip()
                if not requested_item or not required_timeframe or not selected_payment_method or not offered_price or not roblox_username:
                    raise PermissionDeniedError("חובה למלא את כל השדות בטופס ההזמנה.")

                order = await bot.services.orders.create_request(
                    user_id=session.discord_user_id,
                    requested_item=requested_item,
                    required_timeframe=required_timeframe,
                    payment_method=selected_payment_method,
                    offered_price=offered_price,
                    roblox_username=roblox_username,
                )

                try:
                    owner = await bot.fetch_user(bot.settings.owner_user_id)
                    owner_dm = owner.dm_channel or await owner.create_dm()
                    owner_embed = await _owner_custom_order_embed(bot, order)
                    view = discord.ui.View()
                    view.add_item(
                        discord.ui.Button(
                            label="פתח את ההזמנה באתר",
                            style=discord.ButtonStyle.link,
                            url=_custom_order_admin_url(bot, order.id),
                        )
                    )
                    owner_message = await owner_dm.send(content="יש הזמנה אישית חדשה", embed=owner_embed, view=view)
                except discord.HTTPException as exc:
                    raise ExternalServiceError("לא הצלחתי לשלוח את ההזמנה לבעלים ב-DM.") from exc
                await bot.services.orders.set_owner_message(order.id, owner_message.id)

                success_html = """
                <div class="card stack">
                    <div><h2>ההזמנה נשלחה</h2><p>שלחנו לבעלים את כל הפרטים, וההזמנה מחכה עכשיו ברשימת האדמין באתר.</p></div>
                    <div class="actions"><a class="link-button" href="/custom-orders">שלח הזמנה נוספת</a></div>
                </div>
                """
                body = _public_shell(
                    session,
                    title="הזמנה אישית",
                    intro="ההזמנה שלך נשמרה ונשלחה לבעלים.",
                    login_path="/custom-orders",
                    section_label="הזמנות אישיות",
                    content=_notice_html("ההזמנה נשלחה בהצלחה. נחזור אליך ב-DM אחרי שנבדוק אותה.", success=True) + success_html,
                )
                return _page_response("הזמנה אישית", body)
            except SalesBotError as exc:
                notice = str(exc)
                success = False
                bot_ref, session = await _current_site_session(request)
                bot = bot_ref

        payment_methods_html = ''.join(
            f'<div class="price-item"><strong>{_escape(label)}</strong><span>אפשר לבחור בטופס</span></div>'
            for _key, label in bot.services.orders.available_payment_methods()
        )
        connected_account_html = ''
        if session is not None:
            connected_account_html = f'<div class="meta-card"><p><strong>חשבון Discord מחובר:</strong> {_escape(_session_label(session))}</p></div>'
        content = f"""
        {_notice_html(notice, success=success)}
        <div class="split-grid">
            <div class="card stack">
                <div><h2>מה מקבלים בדף הזה</h2><p>אפשר לשלוח הזמנה אישית בלי לחבר חשבון Roblox ל-Discord. כל מה שצריך הוא להתחבר עם Discord ולמלא את הפרטים.</p></div>
                <div><h3>שיטות תשלום זמינות</h3><div class="price-list">{payment_methods_html}</div></div>
            </div>
            <div class="card">
                <h2>טופס הזמנה אישית</h2>
                <p class="muted">כל השדות חובה. שם ה-Discord שלך נלקח אוטומטית מההתחברות לאתר.</p>
                {connected_account_html}
                <form method="post">
                    <div class="grid">
                        <label class="field field-wide"><span>מה אתה רוצה להזמין</span><textarea name="requested_item" required>{_escape(requested_item)}</textarea></label>
                        <label class="field"><span>תוך כמה זמן אתה צריך את זה</span><input type="text" name="required_timeframe" value="{_escape(required_timeframe)}" required></label>
                        <label class="field"><span>איך אתה משלם</span><select name="payment_method" required>{_order_payment_method_select_options(bot.services.orders, selected_payment_method)}</select></label>
                        <label class="field field-wide"><span>כמה אתה מוכן לשלם (או מה אתה מביא אם זה דברים במשחק)</span><textarea name="offered_price" required>{_escape(offered_price)}</textarea></label>
                        <label class="field"><span>מה השם שלך ברובלוקס</span><input type="text" name="roblox_username" value="{_escape(roblox_username)}" required></label>
                    </div>
                    <div class="actions"><button type="submit">שלח הזמנה</button></div>
                </form>
            </div>
        </div>
        """
        body = _public_shell(
            session,
            title="הזמנה אישית",
            intro="שלח כאן הזמנה אישית חדשה במקום הטופס הישן של Discord.",
            login_path="/custom-orders",
            section_label="הזמנות אישיות",
            content=content,
        )
        return _page_response("הזמנה אישית", body)
    except web.HTTPException:
        raise
    except SalesBotError as exc:
        return _error_response("הזמנה אישית", str(exc), status=400)


async def account_payment_page(request: web.Request) -> web.Response:
    notice: str | None = None
    success = True
    roblox_username = ""
    roblox_password = ""
    profile_link = ""
    has_email = ""
    has_phone = ""
    has_two_factor = ""
    confirmed = False
    try:
        bot_ref, session = await _current_site_session(request)
        bot = bot_ref

        if request.method == "POST":
            try:
                bot, session = await _require_site_session(request)
                form = await request.post()
                roblox_username = str(form.get("roblox_username", "")).strip()
                roblox_password = str(form.get("roblox_password", "")).strip()
                profile_link = str(form.get("profile_link", "")).strip()
                has_email = str(form.get("has_email", "")).strip().lower()
                has_phone = str(form.get("has_phone", "")).strip().lower()
                has_two_factor = str(form.get("has_two_factor", "")).strip().lower()
                confirmed = str(form.get("confirmed", "")).strip().lower() in {"1", "true", "yes", "on"}
                profile_image = _extract_file_upload(form.get("profile_image"), image_only=True)

                if not roblox_username or not roblox_password or not has_email or not has_phone or not has_two_factor:
                    raise PermissionDeniedError("חובה למלא את כל שדות החובה בטופס הזה.")
                if not confirmed:
                    raise PermissionDeniedError("חובה לאשר שאתה מבין שאין החזרות ושכל הפרטים נכונים.")

                delivered_count = await _send_account_payment_submission_to_admins(
                    bot,
                    session=session,
                    roblox_username=roblox_username,
                    roblox_password=roblox_password,
                    profile_link=profile_link or None,
                    profile_image=profile_image,
                    has_email=has_email == "yes",
                    has_phone=has_phone == "yes",
                    has_two_factor=has_two_factor == "yes",
                )
                if delivered_count <= 0:
                    raise ExternalServiceError("לא הצלחתי להעביר את פרטי המשתמש לאף אדמין ב-DM. נסה שוב בעוד רגע.")

                success_html = """
                <div class="card stack">
                    <div><h2>הטופס נשלח</h2><p>הפרטים הועברו לאדמינים בהצלחה. אחרי האימות המלא וההגעה של המשתמש ליוצרים, תקבלו את מה שסוכם.</p></div>
                    <div class="actions"><a class="link-button" href="/account-payment">שלח טופס נוסף</a></div>
                </div>
                """
                body = _public_shell(
                    session,
                    title="שליחת משתמש בתור תשלום",
                    intro="הטופס נשלח לאדמינים בהצלחה.",
                    login_path="/account-payment",
                    section_label="תשלום במשתמש Roblox",
                    content=_notice_html("הטופס נשלח בהצלחה לאדמינים.", success=True) + success_html,
                )
                return _page_response("שליחת משתמש בתור תשלום", body)
            except SalesBotError as exc:
                notice = str(exc)
                success = False
                bot_ref, session = await _current_site_session(request)
                bot = bot_ref

        connected_account_html = ""
        if session is not None:
            connected_account_html = f'<div class="meta-card"><p><strong>חשבון Discord מחובר:</strong> {_escape(_session_label(session))}</p></div>'

        content = f"""
        {_notice_html(notice, success=success)}
        <div class="split-grid">
            <div class="card stack">
                <div>
                    <h2>לפני שליחת הטופס</h2>
                    <p class="warning-note"><strong>הדף הזה הוא דף שליחת משתמש בתור תשלום. יש כמה דברים חשובים שתצטרך לדעת ובעת שליחת הטופס אתה מסכים להם</strong></p>
                    <p class="warning-note"><strong>אתה שולח כאן את הפרטים של המשתמש רובלוקס שאתה רוצה לתת לנו בתור תשלום</strong></p>
                    <p class="warning-note"><strong>אתה נותן את הסיסמא שלך למשתמש שאתה רוצה לתת לנו בתור תשלום</strong></p>
                    <p class="warning-note"><strong>אתה מסכים לכך שאין החזרות ורק לאחר האימות המלא וההגעה של המשתמש ליוצרים אתה תקבל את מה שהזמנת</strong></p>
                </div>
            </div>
            <div class="card">
                <h2>טופס שליחת משתמש</h2>
                <p class="muted">הטופס הזה דורש התחברות עם Discord כדי שנדע מי שלח את הפרטים.</p>
                {connected_account_html}
                <form method="post" enctype="multipart/form-data">
                    <div class="grid">
                        <label class="field"><span>השם של המשתמש רובלוקס (שם!!!! לא כינוי!!!!)</span><input type="text" name="roblox_username" value="{_escape(roblox_username)}" required></label>
                        <label class="field"><span>סיסמא של המשתמש רובלוקס</span><input type="text" name="roblox_password" value="{_escape(roblox_password)}" required></label>
                        <label class="field field-wide"><span>קישור לפרופיל ברובלוקס במידה ואתה יכול לשלוח</span><input type="url" name="profile_link" value="{_escape(profile_link)}"></label>
                        <label class="field field-wide"><span>תמונה של הפרופיל במידה ואתה יכול להוסיף</span><input type="file" name="profile_image" accept="image/*"></label>
                        <label class="field"><span>האם יש על המשתמש מייל שלך</span><select name="has_email" required>{_yes_no_select_options(has_email)}</select></label>
                        <div class="field field-wide">
                            <span>האם יש מספר טלפון על המשתמש</span>
                            <select name="has_phone" required>{_yes_no_select_options(has_phone)}</select>
                            <p class="warning-note"><strong>מומלץ להוריד את המספר טלפון מהמשתמש לפני שתשלח את זה</strong></p>
                        </div>
                        <div class="field field-wide">
                            <span>האם יש אימות דו שלבי על המשתמש</span>
                            <select name="has_two_factor" required>{_yes_no_select_options(has_two_factor)}</select>
                            <p class="warning-note"><strong>אנא תוריד את האימות דו שלבי לפני שתשלח את המשתמש</strong></p>
                        </div>
                        <label class="meta-card check-card field-wide">
                            <span class="check-line warning-note">
                                <input type="checkbox" name="confirmed" value="true"{' checked' if confirmed else ''} required>
                                <strong>האם אתה מבין שאתה מביא לנו את המשתמש הזה והוא לא יחזור אלייך אחר כך, ובנוסף לכך אתה מאשר בכך שהבאת פרטים נכונים ולא זייפת אף פרט? (במידה ותזייף פרטים אתה תקבל בלאקליסט מהמשחק והשרת שלנו)</strong>
                            </span>
                        </label>
                    </div>
                    <div class="actions"><button type="submit">שלח את המשתמש לאדמינים</button></div>
                </form>
            </div>
        </div>
        """
        body = _public_shell(
            session,
            title="שליחת משתמש בתור תשלום",
            intro="שלח כאן את פרטי המשתמש שאתה מביא כתשלום, אחרי התחברות עם Discord.",
            login_path="/account-payment",
            section_label="תשלום במשתמש Roblox",
            content=content,
        )
        return _page_response("שליחת משתמש בתור תשלום", body)
    except web.HTTPException:
        raise
    except SalesBotError as exc:
        return _error_response("שליחת משתמש בתור תשלום", str(exc), status=400)


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