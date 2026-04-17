from __future__ import annotations

import html
import logging
from itertools import zip_longest
from typing import TYPE_CHECKING, Any

import discord
from aiohttp import web

from sales_bot.exceptions import ConfigurationError, PermissionDeniedError, SalesBotError
from sales_bot.models import PollOption

if TYPE_CHECKING:
    from sales_bot.bot import SalesBot


LOGGER = logging.getLogger(__name__)

POLL_FORM_SCRIPT = """
<script>
function escapeHtml(value) {
    return value
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

function buildOptionRow(label = '', emoji = '') {
    return `
        <div class="option-row">
            <input type="text" name="option_emoji" maxlength="32" placeholder="😀" value="${escapeHtml(emoji)}" required>
            <input type="text" name="option_label" maxlength="120" placeholder="טקסט האפשרות" value="${escapeHtml(label)}" required>
            <button type="button" class="ghost-button danger" onclick="removeOptionRow(this)">הסר</button>
        </div>
    `;
}

function addOptionRow(label = '', emoji = '') {
    const container = document.getElementById('poll-options');
    container.insertAdjacentHTML('beforeend', buildOptionRow(label, emoji));
}

function removeOptionRow(button) {
    const container = document.getElementById('poll-options');
    if (container.children.length <= 2) {
        return;
    }
    button.closest('.option-row').remove();
}
</script>
"""


def admin_html_response(title: str, body: str) -> web.Response:
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
                --bg: #07111f;
                --panel: rgba(12, 29, 49, 0.88);
                --panel-border: rgba(133, 198, 255, 0.16);
                --text: #f6fbff;
                --muted: #a3bed5;
                --accent: #55d6be;
                --accent-strong: #26b89d;
                --danger: #ff8579;
                --field: rgba(8, 20, 35, 0.78);
            }}
            * {{ box-sizing: border-box; }}
            body {{
                margin: 0;
                min-height: 100vh;
                font-family: Bahnschrift, "Trebuchet MS", "Aptos", sans-serif;
                color: var(--text);
                background:
                    radial-gradient(circle at 20% 10%, rgba(85, 214, 190, 0.16), transparent 32%),
                    radial-gradient(circle at 80% 0%, rgba(91, 143, 249, 0.18), transparent 30%),
                    linear-gradient(160deg, #03080f 0%, #07111f 48%, #0d1e31 100%);
            }}
            main {{
                max-width: 980px;
                margin: 0 auto;
                padding: 44px 18px 72px;
            }}
            .shell {{
                background: var(--panel);
                border: 1px solid var(--panel-border);
                border-radius: 26px;
                padding: 30px;
                box-shadow: 0 30px 80px rgba(0, 0, 0, 0.4);
                backdrop-filter: blur(14px);
            }}
            .eyebrow {{
                margin: 0 0 10px;
                color: var(--accent);
                text-transform: uppercase;
                letter-spacing: 0.18em;
                font-size: 0.76rem;
            }}
            h1 {{
                margin: 0 0 10px;
                font-size: clamp(2rem, 4vw, 3rem);
                line-height: 1.05;
            }}
            p, li, label, small {{
                color: var(--muted);
                line-height: 1.65;
            }}
            a {{ color: var(--accent); }}
            form {{ margin-top: 24px; }}
            .grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
                gap: 18px;
            }}
            .field {{ display: flex; flex-direction: column; gap: 8px; }}
            .field-wide {{ grid-column: 1 / -1; }}
            input, select, textarea {{
                width: 100%;
                border: 1px solid rgba(140, 175, 211, 0.18);
                border-radius: 14px;
                background: var(--field);
                color: var(--text);
                padding: 14px 16px;
                font: inherit;
            }}
            textarea {{ min-height: 150px; resize: vertical; }}
            .option-list {{ display: flex; flex-direction: column; gap: 12px; }}
            .option-row {{ display: grid; grid-template-columns: 120px 1fr auto; gap: 12px; align-items: center; }}
            .actions {{ display: flex; gap: 12px; flex-wrap: wrap; margin-top: 26px; }}
            button, .link-button {{
                border: 0;
                border-radius: 999px;
                padding: 13px 18px;
                background: linear-gradient(135deg, var(--accent) 0%, var(--accent-strong) 100%);
                color: #041019;
                font: inherit;
                font-weight: 700;
                text-decoration: none;
                cursor: pointer;
            }}
            .ghost-button {{
                background: rgba(163, 190, 213, 0.12);
                color: var(--text);
                border: 1px solid rgba(163, 190, 213, 0.18);
            }}
            .danger {{ color: var(--danger); }}
            .notice {{
                border-radius: 18px;
                padding: 14px 16px;
                margin-top: 18px;
                background: rgba(255, 133, 121, 0.12);
                border: 1px solid rgba(255, 133, 121, 0.26);
                color: #ffd6d1;
            }}
            .success {{
                background: rgba(85, 214, 190, 0.12);
                border-color: rgba(85, 214, 190, 0.24);
                color: #d9fff8;
            }}
            .meta-card {{
                margin-top: 20px;
                padding: 18px;
                border-radius: 18px;
                background: rgba(9, 21, 36, 0.78);
                border: 1px solid rgba(134, 167, 201, 0.15);
            }}
            @media (max-width: 700px) {{
                .shell {{ padding: 22px; border-radius: 22px; }}
                .option-row {{ grid-template-columns: 1fr; }}
            }}
        </style>
    </head>
    <body>
        <main>
            <section class="shell">
                {body}
            </section>
        </main>
    </body>
    </html>
    """
    return web.Response(text=content, content_type="text/html")


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _error_response(title: str, message: str, *, status: int) -> web.Response:
    body = f"""
    <p class="eyebrow">פאנל ניהול</p>
    <h1>{_escape(title)}</h1>
    <div class="notice">{_escape(message)}</div>
    """
    response = admin_html_response(title, body)
    response.set_status(status)
    return response


async def _authorize_panel_request(
    request: web.Request,
    *,
    panel_type: str,
    target_id: int | None = None,
) -> tuple["SalesBot", int]:
    bot: SalesBot = request.app["bot"]
    token = request.query.get("token", "").strip()
    if not token:
        raise PermissionDeniedError("חסר טוקן גישה לפאנל הניהול.")

    session = await bot.services.panels.get_session(token, expected_panel_type=panel_type)
    if target_id is None and session.target_id is not None:
        raise PermissionDeniedError("קישור פאנל הניהול הזה שייך לרשומה אחרת.")
    if target_id is not None and session.target_id != target_id:
        raise PermissionDeniedError("קישור פאנל הניהול הזה לא תואם לרשומה שביקשת.")
    if not await bot.services.admins.is_admin(session.admin_user_id):
        raise PermissionDeniedError("קישור פאנל הניהול הזה כבר לא משויך לאדמין של הבוט.")
    return bot, session.admin_user_id


async def _list_text_channels(bot: "SalesBot") -> list[discord.TextChannel]:
    if bot.settings.primary_guild_id is None:
        raise ConfigurationError("חובה להגדיר PRIMARY_GUILD_ID לפני שימוש בפאנלי הניהול.")

    try:
        guild = bot.get_guild(bot.settings.primary_guild_id)
        if guild is None:
            guild = await bot.fetch_guild(bot.settings.primary_guild_id)
            channels = await guild.fetch_channels()
        else:
            channels = guild.channels
            if not channels:
                channels = await guild.fetch_channels()
    except discord.Forbidden as exc:
        raise PermissionDeniedError(
            "לבוט אין הרשאה לטעון ערוצים מתוך PRIMARY_GUILD_ID."
        ) from exc
    except discord.HTTPException as exc:
        raise ConfigurationError(
            "לא הצלחתי לטעון ערוצים מתוך PRIMARY_GUILD_ID. בדקו שהמזהה נכון ושהבוט נמצא בשרת הזה."
        ) from exc

    text_channels = [channel for channel in channels if isinstance(channel, discord.TextChannel)]
    if not text_channels:
        raise ConfigurationError("לא נמצאו ערוצי טקסט בשרת הראשי שהוגדר.")

    return sorted(text_channels, key=lambda channel: (channel.position, channel.name.casefold()))


def _render_channel_options(channels: list[discord.TextChannel], selected_channel_id: int | None) -> str:
    option_lines: list[str] = []
    for channel in channels:
        selected = " selected" if selected_channel_id == channel.id else ""
        option_lines.append(
            f'<option value="{channel.id}"{selected}>#{_escape(channel.name)}</option>'
        )
    return "\n".join(option_lines)


def _render_duration_unit_options(selected_unit: str) -> str:
    unit_labels = {
        "minutes": "דקות",
        "hours": "שעות",
        "days": "ימים",
        "weeks": "שבועות",
    }
    return "\n".join(
        f'<option value="{unit}"{" selected" if unit == selected_unit else ""}>{label}</option>'
        for unit, label in unit_labels.items()
    )


def _message_link(bot: "SalesBot", channel_id: int, message_id: int | None) -> str | None:
    if bot.settings.primary_guild_id is None or message_id is None:
        return None
    return f"https://discord.com/channels/{bot.settings.primary_guild_id}/{channel_id}/{message_id}"


def _render_success_body(title: str, message: str, *, record_id: int, message_url: str | None) -> str:
    link_html = (
        f'<a class="link-button" href="{_escape(message_url)}" target="_blank" rel="noreferrer">פתח את ההודעה בדיסקורד</a>'
        if message_url
        else ""
    )
    return f"""
    <p class="eyebrow">פאנל ניהול</p>
    <h1>{_escape(title)}</h1>
    <div class="notice success">{_escape(message)}</div>
    <div class="meta-card">
        <p><strong>מזהה שמור:</strong> {_escape(record_id)}</p>
        <p>אפשר להשתמש במזהה הזה אחר כך עם פקודת העריכה המתאימה.</p>
        <div class="actions">{link_html}</div>
    </div>
    """


def _poll_form_defaults() -> dict[str, Any]:
    return {
        "question": "",
        "channel_id": None,
        "duration_value": 1,
        "duration_unit": "hours",
        "options": [{"label": "", "emoji": ""}, {"label": "", "emoji": ""}],
    }


def _poll_values_from_record(poll: Any) -> dict[str, Any]:
    return {
        "question": poll.question,
        "channel_id": poll.channel_id,
        "duration_value": poll.duration_value,
        "duration_unit": poll.duration_unit,
        "options": [{"label": option.label, "emoji": option.emoji} for option in poll.options],
    }


def _extract_poll_form_values(post_data: Any) -> dict[str, Any]:
    labels = post_data.getall("option_label", [])
    emojis = post_data.getall("option_emoji", [])
    options = [
        {"label": str(label), "emoji": str(emoji)}
        for label, emoji in zip_longest(labels, emojis, fillvalue="")
    ]
    return {
        "question": str(post_data.get("question", "")),
        "channel_id": int(str(post_data.get("channel_id", "0")) or 0),
        "duration_value": int(str(post_data.get("duration_value", "0")) or 0),
        "duration_unit": str(post_data.get("duration_unit", "hours")),
        "options": options,
    }


def _build_poll_options(form_values: dict[str, Any]) -> list[PollOption]:
    return [
        PollOption(emoji=str(item.get("emoji", "")), label=str(item.get("label", "")))
        for item in form_values["options"]
    ]


def _render_poll_form(
    *,
    mode_label: str,
    channels: list[discord.TextChannel],
    values: dict[str, Any],
    error_text: str | None = None,
) -> str:
    option_rows = "\n".join(
        f"""
        <div class="option-row">
            <input type="text" name="option_emoji" maxlength="32" placeholder="😀" value="{_escape(option['emoji'])}" required>
            <input type="text" name="option_label" maxlength="120" placeholder="טקסט האפשרות" value="{_escape(option['label'])}" required>
            <button type="button" class="ghost-button danger" onclick="removeOptionRow(this)">הסר</button>
        </div>
        """
        for option in values["options"]
    )
    error_html = f'<div class="notice">{_escape(error_text)}</div>' if error_text else ""
    return f"""
    <p class="eyebrow">פאנל סקרים</p>
    <h1>{_escape(mode_label)} סקר</h1>
    <p>צרו או ערכו סקר בסגנון דיסקורד עם כמה אפשרויות שתרצו. לכל אפשרות חייב להיות אימוג'י משלה.</p>
    {error_html}
    <form method="post">
        <div class="grid">
            <label class="field field-wide">
                <span>שאלה</span>
                <textarea name="question" required>{_escape(values['question'])}</textarea>
            </label>
            <label class="field">
                <span>שלח לערוץ</span>
                <select name="channel_id" required>
                    {_render_channel_options(channels, values['channel_id'])}
                </select>
            </label>
            <label class="field">
                <span>משך זמן</span>
                <input type="number" min="1" name="duration_value" value="{_escape(values['duration_value'])}" required>
            </label>
            <label class="field">
                <span>יחידת זמן</span>
                <select name="duration_unit" required>
                    {_render_duration_unit_options(str(values['duration_unit']))}
                </select>
            </label>
            <div class="field field-wide">
                <span>אפשרויות הסקר</span>
                <div class="option-list" id="poll-options">
                    {option_rows}
                </div>
                <div class="actions">
                    <button type="button" class="ghost-button" onclick="addOptionRow()">הוסף אפשרות</button>
                </div>
            </div>
        </div>
        <div class="actions">
            <button type="submit">{_escape(mode_label)} סקר</button>
        </div>
    </form>
    {POLL_FORM_SCRIPT}
    """


def _giveaway_form_defaults() -> dict[str, Any]:
    return {
        "title": "",
        "description": "",
        "requirements": "",
        "channel_id": None,
        "winner_count": 1,
        "duration_value": 1,
        "duration_unit": "hours",
    }


def _giveaway_values_from_record(giveaway: Any) -> dict[str, Any]:
    return {
        "title": giveaway.title,
        "description": giveaway.description or "",
        "requirements": giveaway.requirements or "",
        "channel_id": giveaway.channel_id,
        "winner_count": giveaway.winner_count,
        "duration_value": giveaway.duration_value,
        "duration_unit": giveaway.duration_unit,
    }


def _extract_giveaway_form_values(post_data: Any) -> dict[str, Any]:
    return {
        "title": str(post_data.get("title", "")),
        "description": str(post_data.get("description", "")),
        "requirements": str(post_data.get("requirements", "")),
        "channel_id": int(str(post_data.get("channel_id", "0")) or 0),
        "winner_count": int(str(post_data.get("winner_count", "0")) or 0),
        "duration_value": int(str(post_data.get("duration_value", "0")) or 0),
        "duration_unit": str(post_data.get("duration_unit", "hours")),
    }


def _render_giveaway_form(
    *,
    mode_label: str,
    channels: list[discord.TextChannel],
    values: dict[str, Any],
    error_text: str | None = None,
) -> str:
    error_html = f'<div class="notice">{_escape(error_text)}</div>' if error_text else ""
    return f"""
    <p class="eyebrow">פאנל הגרלות</p>
    <h1>{_escape(mode_label)} הגרלה</h1>
    <p>צרו או ערכו הגרלה, בחרו לאיזה ערוץ לשלוח אותה, כמה זמן היא תימשך, כמה זוכים יהיו ומה יוצג בתנאים.</p>
    {error_html}
    <form method="post">
        <div class="grid">
            <label class="field field-wide">
                <span>כותרת ההגרלה</span>
                <input type="text" maxlength="180" name="title" value="{_escape(values['title'])}" required>
            </label>
            <label class="field field-wide">
                <span>תיאור</span>
                <textarea name="description">{_escape(values['description'])}</textarea>
            </label>
            <label class="field field-wide">
                <span>דרישות</span>
                <textarea name="requirements">{_escape(values['requirements'])}</textarea>
            </label>
            <label class="field">
                <span>שלח לערוץ</span>
                <select name="channel_id" required>
                    {_render_channel_options(channels, values['channel_id'])}
                </select>
            </label>
            <label class="field">
                <span>מספר זוכים</span>
                <input type="number" min="1" name="winner_count" value="{_escape(values['winner_count'])}" required>
            </label>
            <label class="field">
                <span>משך זמן</span>
                <input type="number" min="1" name="duration_value" value="{_escape(values['duration_value'])}" required>
            </label>
            <label class="field">
                <span>יחידת זמן</span>
                <select name="duration_unit" required>
                    {_render_duration_unit_options(str(values['duration_unit']))}
                </select>
            </label>
        </div>
        <div class="actions">
            <button type="submit">{_escape(mode_label)} הגרלה</button>
        </div>
    </form>
    """


def _system_values_from_record(system: Any) -> dict[str, Any]:
    return {
        "name": system.name,
        "description": system.description,
        "paypal_link": system.paypal_link or "",
        "roblox_gamepass": system.roblox_gamepass_id or "",
        "clear_image": False,
    }


def _extract_system_form_values(post_data: Any) -> dict[str, Any]:
    return {
        "name": str(post_data.get("name", "")),
        "description": str(post_data.get("description", "")),
        "paypal_link": str(post_data.get("paypal_link", "")),
        "roblox_gamepass": str(post_data.get("roblox_gamepass", "")),
        "clear_image": str(post_data.get("clear_image", "")).lower() in {"1", "true", "yes", "on"},
    }


def _extract_upload(field: Any) -> tuple[str, bytes] | None:
    if not isinstance(field, web.FileField) or not field.filename:
        return None
    payload = field.file.read()
    if not payload:
        return None
    return field.filename, payload


def _render_system_form(
    *,
    system: Any,
    values: dict[str, Any],
    error_text: str | None = None,
) -> str:
    error_html = f'<div class="notice">{_escape(error_text)}</div>' if error_text else ""
    current_image = f"<p>Current image: {_escape(system.image_path)}</p>" if system.image_path else "<p>No current image.</p>"
    return f"""
    <p class="eyebrow">Admin System Editor</p>
    <h1>Edit System #{_escape(system.id)}</h1>
    <p>Update the text fields below or replace the stored file/image uploads.</p>
    {error_html}
    <div class="meta-card">
        <p><strong>Current file:</strong> {_escape(system.file_path)}</p>
        {current_image}
    </div>
    <form method="post" enctype="multipart/form-data">
        <div class="grid">
            <label class="field field-wide">
                <span>Name</span>
                <input type="text" maxlength="180" name="name" value="{_escape(values['name'])}" required>
            </label>
            <label class="field field-wide">
                <span>Description</span>
                <textarea name="description" required>{_escape(values['description'])}</textarea>
            </label>
            <label class="field">
                <span>PayPal Link</span>
                <input type="url" name="paypal_link" value="{_escape(values['paypal_link'])}">
            </label>
            <label class="field">
                <span>Roblox Gamepass ID or URL</span>
                <input type="text" name="roblox_gamepass" value="{_escape(values['roblox_gamepass'])}">
            </label>
            <label class="field">
                <span>Replace File</span>
                <input type="file" name="file">
            </label>
            <label class="field">
                <span>Replace Image</span>
                <input type="file" name="image" accept="image/*">
            </label>
            <label class="field field-wide">
                <span>
                    <input type="checkbox" name="clear_image" value="true"{' checked' if values['clear_image'] else ''}>
                    Remove the stored image entirely
                </span>
            </label>
        </div>
        <div class="actions">
            <button type="submit">Save System Changes</button>
        </div>
    </form>
    """


async def poll_create_page(request: web.Request) -> web.Response:
    return await _handle_poll_form(request, poll_id=None, panel_type="poll-create")


async def poll_edit_page(request: web.Request) -> web.Response:
    return await _handle_poll_form(
        request,
        poll_id=int(request.match_info["poll_id"]),
        panel_type="poll-edit",
    )


async def giveaway_create_page(request: web.Request) -> web.Response:
    return await _handle_giveaway_form(request, giveaway_id=None, panel_type="giveaway-create")


async def giveaway_edit_page(request: web.Request) -> web.Response:
    return await _handle_giveaway_form(
        request,
        giveaway_id=int(request.match_info["giveaway_id"]),
        panel_type="giveaway-edit",
    )


async def system_edit_page(request: web.Request) -> web.Response:
    system_id = int(request.match_info["system_id"])
    try:
        bot, _ = await _authorize_panel_request(request, panel_type="system-edit", target_id=system_id)
        system = await bot.services.systems.get_system(system_id)
        values = _system_values_from_record(system)

        if request.method == "POST":
            form_data = await request.post()
            values = _extract_system_form_values(form_data)
            try:
                image_field = form_data.get("image")
                if isinstance(image_field, web.FileField) and image_field.content_type and not image_field.content_type.startswith("image/"):
                    raise PermissionDeniedError("The uploaded image must be a valid image file.")

                updated_system = await bot.services.systems.update_system(
                    system_id,
                    name=values["name"],
                    description=values["description"],
                    paypal_link=values["paypal_link"] or None,
                    roblox_gamepass_reference=values["roblox_gamepass"] or None,
                    file_upload=_extract_upload(form_data.get("file")),
                    image_upload=_extract_upload(image_field),
                    clear_image=bool(values["clear_image"]),
                )
                return admin_html_response(
                    "System Updated",
                    _render_success_body(
                        f"System #{updated_system.id} Updated",
                        f"{updated_system.name} was updated successfully.",
                        record_id=updated_system.id,
                        message_url=None,
                    ),
                )
            except SalesBotError as exc:
                return admin_html_response(
                    f"Edit System #{system.id}",
                    _render_system_form(system=system, values=values, error_text=str(exc)),
                )

        return admin_html_response(
            f"Edit System #{system.id}",
            _render_system_form(system=system, values=values),
        )
    except SalesBotError as exc:
        return _error_response("System Editor", str(exc), status=400)
    except Exception:
        LOGGER.exception("Unexpected system edit panel failure")
        return _error_response("System Editor", "An unexpected error occurred while loading the system editor.", status=500)


async def _handle_poll_form(
    request: web.Request,
    *,
    poll_id: int | None,
    panel_type: str,
) -> web.Response:
    try:
        bot, admin_user_id = await _authorize_panel_request(request, panel_type=panel_type, target_id=poll_id)
        channels = await _list_text_channels(bot)
        values = _poll_form_defaults()
        if poll_id is not None:
            values = _poll_values_from_record(await bot.services.polls.get_editable_poll(poll_id))

        if request.method == "POST":
            form_data = await request.post()
            values = _extract_poll_form_values(form_data)
            try:
                poll_options = _build_poll_options(values)
                if poll_id is None:
                    saved_poll = await bot.services.polls.create_poll(
                        bot,
                        created_by=admin_user_id,
                        channel_id=values["channel_id"],
                        question=values["question"],
                        options=poll_options,
                        duration_value=values["duration_value"],
                        duration_unit=values["duration_unit"],
                    )
                    success_title = f"הסקר #{saved_poll.id} נוצר"
                    success_message = "הסקר פורסם בהצלחה."
                else:
                    saved_poll = await bot.services.polls.update_poll(
                        bot,
                        poll_id,
                        channel_id=values["channel_id"],
                        question=values["question"],
                        options=poll_options,
                        duration_value=values["duration_value"],
                        duration_unit=values["duration_unit"],
                    )
                    success_title = f"הסקר #{saved_poll.id} עודכן"
                    success_message = "הודעת הסקר עודכנה בהצלחה."

                return admin_html_response(
                    success_title,
                    _render_success_body(
                        success_title,
                        success_message,
                        record_id=saved_poll.id,
                        message_url=_message_link(bot, saved_poll.channel_id, saved_poll.message_id),
                    ),
                )
            except SalesBotError as exc:
                return admin_html_response(
                    "פאנל סקרים",
                    _render_poll_form(
                        mode_label="ערוך" if poll_id is not None else "צור",
                        channels=channels,
                        values=values,
                        error_text=str(exc),
                    ),
                )

        return admin_html_response(
            "פאנל סקרים",
            _render_poll_form(
                mode_label="ערוך" if poll_id is not None else "צור",
                channels=channels,
                values=values,
            ),
        )
    except SalesBotError as exc:
        return _error_response("פאנל סקרים", str(exc), status=400)
    except Exception:
        LOGGER.exception("Unexpected poll panel failure")
        return _error_response("פאנל סקרים", "אירעה שגיאה לא צפויה בזמן טעינת פאנל הסקרים.", status=500)


async def _handle_giveaway_form(
    request: web.Request,
    *,
    giveaway_id: int | None,
    panel_type: str,
) -> web.Response:
    try:
        bot, admin_user_id = await _authorize_panel_request(request, panel_type=panel_type, target_id=giveaway_id)
        channels = await _list_text_channels(bot)
        values = _giveaway_form_defaults()
        if giveaway_id is not None:
            values = _giveaway_values_from_record(await bot.services.giveaways.get_editable_giveaway(giveaway_id))

        if request.method == "POST":
            form_data = await request.post()
            values = _extract_giveaway_form_values(form_data)
            try:
                if giveaway_id is None:
                    saved_giveaway = await bot.services.giveaways.create_giveaway(
                        bot,
                        created_by=admin_user_id,
                        channel_id=values["channel_id"],
                        title=values["title"],
                        description=values["description"],
                        requirements=values["requirements"],
                        winner_count=values["winner_count"],
                        duration_value=values["duration_value"],
                        duration_unit=values["duration_unit"],
                    )
                    success_title = f"ההגרלה #{saved_giveaway.id} נוצרה"
                    success_message = "ההגרלה פורסמה בהצלחה."
                else:
                    saved_giveaway = await bot.services.giveaways.update_giveaway(
                        bot,
                        giveaway_id,
                        channel_id=values["channel_id"],
                        title=values["title"],
                        description=values["description"],
                        requirements=values["requirements"],
                        winner_count=values["winner_count"],
                        duration_value=values["duration_value"],
                        duration_unit=values["duration_unit"],
                    )
                    success_title = f"ההגרלה #{saved_giveaway.id} עודכנה"
                    success_message = "הודעת ההגרלה עודכנה בהצלחה."

                return admin_html_response(
                    success_title,
                    _render_success_body(
                        success_title,
                        success_message,
                        record_id=saved_giveaway.id,
                        message_url=_message_link(bot, saved_giveaway.channel_id, saved_giveaway.message_id),
                    ),
                )
            except SalesBotError as exc:
                return admin_html_response(
                    "פאנל הגרלות",
                    _render_giveaway_form(
                        mode_label="ערוך" if giveaway_id is not None else "צור",
                        channels=channels,
                        values=values,
                        error_text=str(exc),
                    ),
                )

        return admin_html_response(
            "פאנל הגרלות",
            _render_giveaway_form(
                mode_label="ערוך" if giveaway_id is not None else "צור",
                channels=channels,
                values=values,
            ),
        )
    except SalesBotError as exc:
        return _error_response("פאנל הגרלות", str(exc), status=400)
    except Exception:
        LOGGER.exception("Unexpected giveaway panel failure")
        return _error_response("פאנל הגרלות", "אירעה שגיאה לא צפויה בזמן טעינת פאנל ההגרלות.", status=500)