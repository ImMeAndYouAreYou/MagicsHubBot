from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from sales_bot.bot import SalesBot
from sales_bot.checks import admin_only
from sales_bot.exceptions import NotFoundError
from sales_bot.models import VouchRecord
from sales_bot.ui.common import ConfirmView, PaginatedSelectView
from sales_bot.ui.vouches import VouchCreateModal


def build_vouch_embed(vouch: VouchRecord, *, admin_user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(title="פרטי הוכחה", color=discord.Color.gold())
    embed.add_field(name="הוכחה על", value=admin_user.mention, inline=False)
    embed.add_field(name="מאת", value=f"<@{vouch.author_user_id}>", inline=False)
    embed.add_field(name="הסבר", value=vouch.reason, inline=False)
    embed.add_field(name="דירוג", value=f"{'⭐' * vouch.rating} ({vouch.rating}/5)", inline=False)
    embed.set_footer(text=f"מזהה הוכחה: {vouch.id}")
    return embed


class VouchesCog(commands.Cog):
    def __init__(self, bot: SalesBot) -> None:
        self.bot = bot

    @app_commands.command(name="vouch", description="יצירת הוכחה למוכר שלנו.")
    @app_commands.describe(admin_user="מנהל שמקבל את ההוכחה.")
    async def vouch(
        self,
        interaction: discord.Interaction,
        admin_user: discord.User,
    ) -> None:
        if not await self.bot.services.admins.is_admin(admin_user.id):
            raise NotFoundError("המשתמש שבחרת לא נמצא ברשימת המוכרים.")

        await interaction.response.send_modal(
            VouchCreateModal(
                self.bot,
                actor_id=interaction.user.id,
                admin_user=admin_user,
            )
        )

    @app_commands.command(name="vouches", description="הצגת סך ההוכחות ודירוג ממוצע למנהל.")
    @app_commands.describe(user="מנהל שמידע על ההוכחות שלו יוצג.")
    async def vouches(self, interaction: discord.Interaction, user: discord.User) -> None:
        if not await self.bot.services.admins.is_admin(user.id):
            raise NotFoundError("המשתמש שבחרת לא נמצא ברשימת המוכרים.")

        stats = await self.bot.services.vouches.get_stats(user.id)
        embed = discord.Embed(title=f"הוכחות עבור {user}", color=discord.Color.gold())
        embed.add_field(name="סך ההוכחות", value=str(stats.total), inline=True)
        embed.add_field(name="דירוג ממוצע", value=f"{stats.average_rating:.2f} / 5", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="revokevouch", description="מחיקת הוכחה מסוימת ממוכר דרך בחירה מתפריט.")
    @app_commands.describe(admin_user="המנהל שעבורו תוצג רשימת ההוכחות.")
    @admin_only()
    async def revokevouch(self, interaction: discord.Interaction, admin_user: discord.User) -> None:
        if not await self.bot.services.admins.is_admin(admin_user.id):
            raise NotFoundError("המשתמש שבחרת לא נמצא ברשימת המוכרים.")

        vouches = await self.bot.services.vouches.list_vouches(admin_user.id)
        if not vouches:
            await interaction.response.send_message("לא נמצאו הוכחות למחיקה עבור המשתמש הזה.", ephemeral=True)
            return

        async def on_selected(
            select_interaction: discord.Interaction,
            vouch: object,
            parent_view: PaginatedSelectView,
        ) -> None:
            selected_vouch = vouch
            embed = build_vouch_embed(selected_vouch, admin_user=admin_user)
            embed.title = "אישור מחיקת הוכחה"

            async def on_confirm(confirm_interaction: discord.Interaction, view: ConfirmView) -> None:
                deleted_vouch = await self.bot.services.vouches.delete_vouch(selected_vouch.id)
                channel = self.bot.get_channel(self.bot.settings.vouch_channel_id)
                if channel is None:
                    try:
                        channel = await self.bot.fetch_channel(self.bot.settings.vouch_channel_id)
                    except discord.HTTPException:
                        channel = None

                if deleted_vouch.posted_message_id is not None and channel is not None and hasattr(channel, "fetch_message"):
                    try:
                        posted_message = await channel.fetch_message(deleted_vouch.posted_message_id)
                        await posted_message.delete()
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        pass

                await confirm_interaction.response.edit_message(
                    content="ההוכחה נמחקה בהצלחה.",
                    embed=None,
                    view=view,
                )

            confirm_view = ConfirmView(actor_id=interaction.user.id, on_confirm=on_confirm)
            await select_interaction.response.edit_message(
                content="בדוק את פרטי ההוכחה לפני המחיקה.",
                embed=embed,
                view=confirm_view,
            )

        view = PaginatedSelectView(
            actor_id=interaction.user.id,
            items=vouches,
            placeholder="בחר הוכחה למחיקה",
            option_builder=lambda vouch: discord.SelectOption(
                label=f"<@{vouch.author_user_id}> | {vouch.rating}/5"[:100],
                description=vouch.reason[:100],
                value=str(vouch.id),
            ),
            value_getter=lambda vouch: str(vouch.id),
            on_selected=on_selected,
        )
        await interaction.response.send_message(
            f"בחר הוכחה של {admin_user.mention} למחיקה.",
            view=view,
            ephemeral=True,
        )


async def setup(bot: SalesBot) -> None:
    await bot.add_cog(VouchesCog(bot))
