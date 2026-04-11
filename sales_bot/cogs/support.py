from __future__ import annotations

import discord
from discord.ext import commands

from sales_bot.bot import SalesBot


class SupportCog(commands.Cog):
    def __init__(self, bot: SalesBot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is not None:
            return

        if message.author.id == self.bot.settings.owner_user_id:
            return

        owner = await self.bot.fetch_user(self.bot.settings.owner_user_id)
        attachment_lines = "\n".join(attachment.url for attachment in message.attachments)
        embed = discord.Embed(title="Incoming User DM", color=discord.Color.teal())
        embed.add_field(name="From", value=f"{message.author} ({message.author.id})", inline=False)
        embed.add_field(name="Message", value=message.content or "*No text content*", inline=False)
        if attachment_lines:
            embed.add_field(name="Attachments", value=attachment_lines[:1024], inline=False)

        try:
            await owner.send(embed=embed)
        except discord.HTTPException:
            pass


async def setup(bot: SalesBot) -> None:
    await bot.add_cog(SupportCog(bot))