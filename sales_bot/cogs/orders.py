from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from sales_bot.bot import SalesBot
from sales_bot.checks import admin_only
from sales_bot.ui.orders import OrderPanelView


class OrdersCog(commands.Cog):
    def __init__(self, bot: SalesBot) -> None:
        self.bot = bot

    @app_commands.command(name="sendorderpanel", description="שליחת פאנל ההזמנות לערוץ ההזמנות.")
    @admin_only()
    async def sendorderpanel(self, interaction: discord.Interaction) -> None:
        channel = self.bot.get_channel(self.bot.settings.order_channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(self.bot.settings.order_channel_id)

        if not isinstance(channel, discord.abc.Messageable):
            await interaction.response.send_message("ערוץ ההזמנות לא תומך בשליחת הודעות.", ephemeral=True)
            return

        embed = discord.Embed(
            title="הזמנות בהכנה אישית",
            description="לחצו על הכפתור כאן למטה בכדי להזמין מערכת / משהו אחר ממגיק (המייסד) בהכנה אישית.",
            color=discord.Color.gold(),
        )
        view = OrderPanelView(self.bot)
        await channel.send(embed=embed, view=view)
        await interaction.response.send_message(f"פאנל ההזמנות נשלח ל-<#{self.bot.settings.order_channel_id}>.", ephemeral=True)


async def setup(bot: SalesBot) -> None:
    await bot.add_cog(OrdersCog(bot))