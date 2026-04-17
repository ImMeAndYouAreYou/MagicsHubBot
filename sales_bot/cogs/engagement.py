from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from sales_bot.bot import SalesBot
from sales_bot.checks import admin_only


class EngagementCog(commands.Cog):
    def __init__(self, bot: SalesBot) -> None:
        self.bot = bot

    @app_commands.command(name="poll", description="פתיחת פאנל הניהול ליצירת סקר.")
    @admin_only()
    async def poll(self, interaction: discord.Interaction) -> None:
        session = await self.bot.services.panels.create_session(
            admin_user_id=interaction.user.id,
            panel_type="poll-create",
        )
        panel_url = f"{self.bot.settings.public_base_url}/admin/polls/new?token={session.token}"
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="פתח את פאנל הסקרים", style=discord.ButtonStyle.link, url=panel_url))

        embed = discord.Embed(title="פאנל סקרים", color=discord.Color.blurple())
        embed.description = "לחצו על הכפתור למטה כדי לפתוח את פאנל הניהול, ליצור סקר ולפרסם אותו."
        embed.add_field(name="תוקף הקישור", value=f"{self.bot.settings.admin_panel_session_minutes} דקות", inline=False)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="editpoll", description="פתיחת פאנל הניהול לעריכת סקר קיים.")
    @app_commands.describe(poll_id="מזהה הסקר כפי שמופיע בהודעת הסקר.")
    @admin_only()
    async def editpoll(self, interaction: discord.Interaction, poll_id: int) -> None:
        poll = await self.bot.services.polls.get_editable_poll(poll_id)
        session = await self.bot.services.panels.create_session(
            admin_user_id=interaction.user.id,
            panel_type="poll-edit",
            target_id=poll.id,
        )
        panel_url = f"{self.bot.settings.public_base_url}/admin/polls/{poll.id}/edit?token={session.token}"
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="ערוך את הסקר", style=discord.ButtonStyle.link, url=panel_url))

        embed = discord.Embed(title=f"עריכת סקר #{poll.id}", color=discord.Color.blurple())
        embed.description = poll.question
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="giveaway", description="פתיחת פאנל הניהול ליצירת הגרלה.")
    @admin_only()
    async def giveaway(self, interaction: discord.Interaction) -> None:
        session = await self.bot.services.panels.create_session(
            admin_user_id=interaction.user.id,
            panel_type="giveaway-create",
        )
        panel_url = f"{self.bot.settings.public_base_url}/admin/giveaways/new?token={session.token}"
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="פתח את פאנל ההגרלות", style=discord.ButtonStyle.link, url=panel_url))

        embed = discord.Embed(title="פאנל הגרלות", color=discord.Color.green())
        embed.description = "לחצו על הכפתור למטה כדי לפתוח את פאנל הניהול, ליצור הגרלה ולפרסם אותה."
        embed.add_field(name="תוקף הקישור", value=f"{self.bot.settings.admin_panel_session_minutes} דקות", inline=False)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="editgiveaway", description="פתיחת פאנל הניהול לעריכת הגרלה קיימת.")
    @app_commands.describe(giveaway_id="מזהה ההגרלה כפי שמופיע בהודעת ההגרלה.")
    @admin_only()
    async def editgiveaway(self, interaction: discord.Interaction, giveaway_id: int) -> None:
        giveaway = await self.bot.services.giveaways.get_editable_giveaway(giveaway_id)
        session = await self.bot.services.panels.create_session(
            admin_user_id=interaction.user.id,
            panel_type="giveaway-edit",
            target_id=giveaway.id,
        )
        panel_url = f"{self.bot.settings.public_base_url}/admin/giveaways/{giveaway.id}/edit?token={session.token}"
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="ערוך את ההגרלה", style=discord.ButtonStyle.link, url=panel_url))

        embed = discord.Embed(title=f"עריכת הגרלה #{giveaway.id}", color=discord.Color.green())
        embed.description = giveaway.title
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: SalesBot) -> None:
    await bot.add_cog(EngagementCog(bot))