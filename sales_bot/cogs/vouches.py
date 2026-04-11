from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from sales_bot.bot import SalesBot
from sales_bot.exceptions import NotFoundError
from sales_bot.ui.vouches import VouchPreviewView


class VouchesCog(commands.Cog):
    def __init__(self, bot: SalesBot) -> None:
        self.bot = bot

    @app_commands.command(name="vouch", description="Create and preview a vouch for a listed admin.")
    @app_commands.describe(admin_user="Admin user receiving the vouch.", reason="Reason for the vouch.", rating="Star rating from 1 to 5.")
    async def vouch(
        self,
        interaction: discord.Interaction,
        admin_user: discord.User,
        reason: str,
        rating: app_commands.Range[int, 1, 5],
    ) -> None:
        if not await self.bot.services.admins.is_admin(admin_user.id):
            raise NotFoundError("The selected user is not in the admin list.")

        view = VouchPreviewView(
            self.bot,
            actor_id=interaction.user.id,
            admin_user=admin_user,
            reason=reason,
            rating=int(rating),
        )
        await interaction.response.send_message(
            "Review your vouch before posting it.",
            embed=view.build_preview_embed(),
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()

    @app_commands.command(name="vouches", description="Show vouch totals and average rating for an admin.")
    @app_commands.describe(user="Admin user whose vouch stats should be shown.")
    async def vouches(self, interaction: discord.Interaction, user: discord.User) -> None:
        if not await self.bot.services.admins.is_admin(user.id):
            raise NotFoundError("The selected user is not in the admin list.")

        stats = await self.bot.services.vouches.get_stats(user.id)
        embed = discord.Embed(title=f"Vouches for {user}", color=discord.Color.gold())
        embed.add_field(name="Total Vouches", value=str(stats.total), inline=True)
        embed.add_field(name="Average Rating", value=f"{stats.average_rating:.2f} / 5", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: SalesBot) -> None:
    await bot.add_cog(VouchesCog(bot))
