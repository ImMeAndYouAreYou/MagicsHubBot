from __future__ import annotations

from typing import Any

import discord

from sales_bot.exceptions import ExternalServiceError, PermissionDeniedError
from sales_bot.ui.common import RestrictedView, defer_interaction_response, edit_interaction_response


def parse_vouch_rating(raw_value: str) -> int:
    try:
        rating = int(raw_value)
    except ValueError as exc:
        raise PermissionDeniedError("הדירוג חייב להיות מספר בלבד בין 1 ל-5.") from exc

    if rating not in {1, 2, 3, 4, 5}:
        raise PermissionDeniedError("הדירוג חייב להיות בין 1 ל-5.")

    return rating


class VouchCreateModal(discord.ui.Modal):
    def __init__(
        self,
        bot: discord.Client,
        *,
        actor_id: int,
        admin_user: discord.abc.User,
    ) -> None:
        super().__init__(title="יצירת הוכחה")
        self.bot = bot
        self.actor_id = actor_id
        self.admin_user = admin_user
        self.reason_input = discord.ui.TextInput(
            label="הסבר בקצרה על החוויה שלך, השירות",
            style=discord.TextStyle.paragraph,
            max_length=500,
        )
        self.rating_input = discord.ui.TextInput(
            label="כמה אתה מדרג אותנו (1-5)",
            style=discord.TextStyle.short,
            max_length=1,
        )
        self.add_item(self.reason_input)
        self.add_item(self.rating_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        rating = parse_vouch_rating(str(self.rating_input))
        view = VouchPreviewView(
            self.bot,
            actor_id=self.actor_id,
            admin_user=self.admin_user,
            reason=str(self.reason_input),
            rating=rating,
        )
        await interaction.response.send_message(
            "בדוק את ההוכחה שלך לפני פרסומה.",
            embed=view.build_preview_embed(),
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()


class VouchEditModal(discord.ui.Modal):
    def __init__(self, view: "VouchPreviewView") -> None:
        super().__init__(title="עריכת הוכחה")
        self.preview_view = view
        self.reason_input = discord.ui.TextInput(
            label="הסבר בקצרה על החוויה שלך, השירות",
            style=discord.TextStyle.paragraph,
            max_length=500,
            default=view.reason,
        )
        self.rating_input = discord.ui.TextInput(
            label="כמה אתה מדרג אותנו (1-5)",
            style=discord.TextStyle.short,
            max_length=1,
            default=str(view.rating),
        )
        self.add_item(self.reason_input)
        self.add_item(self.rating_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        rating = parse_vouch_rating(str(self.rating_input))
        self.preview_view.reason = str(self.reason_input)
        self.preview_view.rating = rating
        await interaction.response.defer()
        await self.preview_view.refresh_message()


class VouchPreviewView(RestrictedView):
    def __init__(
        self,
        bot: discord.Client,
        *,
        actor_id: int,
        admin_user: discord.abc.User,
        reason: str,
        rating: int,
    ) -> None:
        super().__init__(actor_id=actor_id, timeout=300)
        self.bot = bot
        self.admin_user = admin_user
        self.reason = reason
        self.rating = rating
        self.message: discord.InteractionMessage | None = None

    def build_preview_embed(self) -> discord.Embed:
        stars = "⭐" * self.rating
        embed = discord.Embed(title="תצוגת הוכחה", color=discord.Color.gold())
        embed.add_field(name="הוכחה על", value=self.admin_user.mention, inline=True)
        embed.add_field(name="הסבר בקצרה על החוויה שלך, השירות", value=self.reason, inline=False)
        embed.add_field(name="דירוג", value=f"{stars} ({self.rating}/5)", inline=True)
        embed.set_footer(text="במידה ואחד הפרטים לא נכונים אנא תקן אותם באמצעות כפתור העריכה לפני שתאשר את ההוכחה")
        return embed

    async def refresh_message(self) -> None:
        if self.message is not None:
            await self.message.edit(embed=self.build_preview_embed(), view=self)

    @discord.ui.button(label="אישור", style=discord.ButtonStyle.success)
    async def confirm_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[Any],
    ) -> None:
        await defer_interaction_response(interaction)

        if not await self.bot.services.admins.is_admin(self.admin_user.id):
            raise PermissionDeniedError("המשתמש שבחרת כבר לא במערכת יותר, אנא בחר משתמש אחר")

        channel = self.bot.get_channel(self.bot.settings.vouch_channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(self.bot.settings.vouch_channel_id)

        if not isinstance(channel, discord.abc.Messageable):
            raise ExternalServiceError("ערוץ ההוכחות שהוגדר בבוט לא תומך בשליחת הודעות.")

        publish_embed = discord.Embed(title="הוכחה חדשה", color=discord.Color.gold())
        publish_embed.add_field(name="הוכחה על", value=self.admin_user.mention, inline=True)
        publish_embed.add_field(name="הסבר בקצרה על החוויה שלך, השירות", value=self.reason, inline=False)
        publish_embed.add_field(name="דירוג", value=f"{'⭐' * self.rating} ({self.rating}/5)", inline=True)
        publish_embed.set_footer(text=f"הוכחה מאת: {interaction.user}")

        posted_message = await channel.send(embed=publish_embed)
        await self.bot.services.vouches.create_vouch(
            admin_user_id=self.admin_user.id,
            author_user_id=interaction.user.id,
            reason=self.reason,
            rating=self.rating,
            posted_message_id=posted_message.id,
        )

        self.disable_all_items()
        await edit_interaction_response(
            interaction,
            content=f"הוכחה פורסמה ב <#{self.bot.settings.vouch_channel_id}>.",
            embed=self.build_preview_embed(),
            view=self,
        )
        self.stop()

    @discord.ui.button(label="עריכה", style=discord.ButtonStyle.primary)
    async def edit_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[Any],
    ) -> None:
        await interaction.response.send_modal(VouchEditModal(self))

    @discord.ui.button(label="ביטול", style=discord.ButtonStyle.secondary)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[Any],
    ) -> None:
        self.disable_all_items()
        await interaction.response.edit_message(content="יצירת ההוכחה בוטלה.", embed=self.build_preview_embed(), view=self)
        self.stop()
