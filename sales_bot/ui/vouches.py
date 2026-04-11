from __future__ import annotations

import discord

from sales_bot.exceptions import ExternalServiceError, PermissionDeniedError
from sales_bot.ui.common import RestrictedView


class VouchEditModal(discord.ui.Modal):
    def __init__(self, view: "VouchPreviewView") -> None:
        super().__init__(title="Edit Vouch Preview")
        self.preview_view = view
        self.reason_input = discord.ui.TextInput(
            label="Reason",
            style=discord.TextStyle.paragraph,
            max_length=500,
            default=view.reason,
        )
        self.rating_input = discord.ui.TextInput(
            label="Rating (1-5)",
            style=discord.TextStyle.short,
            max_length=1,
            default=str(view.rating),
        )
        self.add_item(self.reason_input)
        self.add_item(self.rating_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            rating = int(str(self.rating_input))
        except ValueError as exc:
            raise PermissionDeniedError("Rating must be a whole number between 1 and 5.") from exc

        if rating not in {1, 2, 3, 4, 5}:
            raise PermissionDeniedError("Rating must be between 1 and 5.")

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
        embed = discord.Embed(title="Vouch Preview", color=discord.Color.gold())
        embed.add_field(name="Admin", value=self.admin_user.mention, inline=False)
        embed.add_field(name="Reason", value=self.reason, inline=False)
        embed.add_field(name="Rating", value=f"{stars} ({self.rating}/5)", inline=False)
        embed.set_footer(text="Use Edit to adjust the preview before posting.")
        return embed

    async def refresh_message(self) -> None:
        if self.message is not None:
            await self.message.edit(embed=self.build_preview_embed(), view=self)

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[Any],
    ) -> None:
        if not await self.bot.services.admins.is_admin(self.admin_user.id):
            raise PermissionDeniedError("The selected user is no longer on the admin list.")

        channel = self.bot.get_channel(self.bot.settings.vouch_channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(self.bot.settings.vouch_channel_id)

        if not isinstance(channel, discord.abc.Messageable):
            raise ExternalServiceError("Configured vouch channel is not messageable.")

        publish_embed = discord.Embed(title="New Vouch", color=discord.Color.gold())
        publish_embed.add_field(name="Admin", value=self.admin_user.mention, inline=False)
        publish_embed.add_field(name="Reason", value=self.reason, inline=False)
        publish_embed.add_field(name="Rating", value=f"{'⭐' * self.rating} ({self.rating}/5)", inline=False)
        publish_embed.set_footer(text=f"Submitted by {interaction.user}")

        posted_message = await channel.send(embed=publish_embed)
        await self.bot.services.vouches.create_vouch(
            admin_user_id=self.admin_user.id,
            author_user_id=interaction.user.id,
            reason=self.reason,
            rating=self.rating,
            posted_message_id=posted_message.id,
        )

        self.disable_all_items()
        await interaction.response.edit_message(
            content=f"Vouch posted to <#{self.bot.settings.vouch_channel_id}>.",
            embed=self.build_preview_embed(),
            view=self,
        )
        self.stop()

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.primary)
    async def edit_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[Any],
    ) -> None:
        await interaction.response.send_modal(VouchEditModal(self))

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[Any],
    ) -> None:
        self.disable_all_items()
        await interaction.response.edit_message(content="Vouch cancelled.", embed=self.build_preview_embed(), view=self)
        self.stop()
