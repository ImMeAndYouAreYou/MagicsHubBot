from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from sales_bot.bot import SalesBot
from sales_bot.checks import admin_only


class AdminCog(commands.Cog):
    def __init__(self, bot: SalesBot) -> None:
        self.bot = bot

    @app_commands.command(name="addadmin", description="Add a Discord user to the bot admin list.")
    @app_commands.describe(user="User to grant bot admin access to.")
    @admin_only()
    async def addadmin(self, interaction: discord.Interaction, user: discord.User) -> None:
        await self.bot.services.admins.add_admin(user.id, interaction.user.id)
        await interaction.response.send_message(
            f"Added {user.mention} to the admin list.",
            ephemeral=True,
        )

    @app_commands.command(name="removeadmin", description="Remove a Discord user from the bot admin list.")
    @app_commands.describe(user="User to remove from bot admin access.")
    @admin_only()
    async def removeadmin(self, interaction: discord.Interaction, user: discord.User) -> None:
        await self.bot.services.admins.remove_admin(user.id)
        await interaction.response.send_message(
            f"Removed {user.mention} from the admin list.",
            ephemeral=True,
        )


async def setup(bot: SalesBot) -> None:
    await bot.add_cog(AdminCog(bot))
