from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from sales_bot.bot import SalesBot
from sales_bot.checks import admin_only
from sales_bot.exceptions import ConfigurationError, NotFoundError


class OAuthCog(commands.Cog):
    def __init__(self, bot: SalesBot) -> None:
        self.bot = bot

    @app_commands.command(name="link", description="קבלת קישור לקישור חשבון הרובלוקס שלך.")
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def link(self, interaction: discord.Interaction) -> None:
        if not self.bot.settings.roblox_oauth_enabled:
            raise ConfigurationError(
                "מערכת קישור הרובלוקס עדיין לא מוגדרת. יש להגדיר קודם את משתני הסביבה של Roblox OAuth."
            )

        ephemeral = interaction.guild is not None
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=ephemeral)
            except discord.HTTPException as exc:
                if exc.code != 40060:
                    raise

        state = await self.bot.services.oauth.create_state(interaction.user.id)
        authorization_url = self.bot.services.oauth.build_authorization_url(state)

        embed = discord.Embed(title="קישור חשבון רובלוקס", color=discord.Color.blurple())
        embed.description = "לחץ על הכפתור למטה כדי לקשר את חשבון הרובלוקס שלך. אחרי האישור, הבוט ישמור את החשבון המקושר שלך. (שים לב שלא יהיה ניתן להוריד את החשבון אחר כך)"

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="קשר חשבון", style=discord.ButtonStyle.link, url=authorization_url))
        await interaction.followup.send(embed=embed, view=view, ephemeral=ephemeral)

    @app_commands.command(name="linkedaccount", description="הצגת חשבון הרובלוקס המקושר שלך.")
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def linkedaccount(self, interaction: discord.Interaction) -> None:
        try:
            record = await self.bot.services.oauth.get_link(interaction.user.id)
        except NotFoundError:
            await interaction.response.send_message(
                "אין כרגע חשבון רובלוקס מקושר למשתמש הזה. השתמש ב-`/link` כדי לקשר חשבון.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(title="החשבון המקושר שלך", color=discord.Color.blurple())
        embed.add_field(name="Roblox User ID", value=record.roblox_sub, inline=False)
        embed.add_field(
            name="Username",
            value=record.roblox_username or "לא זמין",
            inline=True,
        )
        embed.add_field(
            name="Display Name",
            value=record.roblox_display_name or "לא זמין",
            inline=True,
        )
        embed.add_field(name="Linked At", value=record.linked_at, inline=False)
        if record.profile_url:
            embed.add_field(name="Profile", value=record.profile_url, inline=False)

        view = None
        if record.profile_url:
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="פתח פרופיל Roblox", style=discord.ButtonStyle.link, url=record.profile_url))

        await interaction.response.send_message(embed=embed, view=view, ephemeral=interaction.guild is not None)

    @app_commands.command(name="checkroblox", description="Admin lookup for a user's linked Roblox account and owned systems.")
    @app_commands.describe(user="The Discord user whose linked Roblox account should be inspected.")
    @admin_only()
    async def checkroblox(self, interaction: discord.Interaction, user: discord.User) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except discord.HTTPException as exc:
                if exc.code != 40060:
                    raise

        if self.bot.http_session is None:
            await interaction.followup.send("The bot HTTP session is not ready yet. Try again in a moment.", ephemeral=True)
            return

        try:
            record = await self.bot.services.oauth.get_link(user.id)
        except NotFoundError:
            await interaction.followup.send("That user does not have a linked Roblox account.", ephemeral=True)
            return

        await self.bot.services.ownership.sync_linked_gamepass_ownerships(self.bot, user.id)
        await self.bot.services.ownership.refresh_claim_role_membership(
            self.bot,
            user.id,
            guild=interaction.guild,
            sync_ownerships=False,
        )

        profile = await self.bot.services.oauth.fetch_public_profile(self.bot.http_session, record.roblox_sub)
        owned_systems = await self.bot.services.ownership.list_user_systems(user.id)

        embed = discord.Embed(title=f"Roblox Profile for {user}", color=discord.Color.blurple())
        embed.add_field(name="Roblox User ID", value=str(profile.user_id), inline=True)
        embed.add_field(name="Username", value=profile.username, inline=True)
        embed.add_field(name="Display Name", value=profile.display_name, inline=True)
        embed.add_field(name="Account Age", value=f"{profile.age_days} days" if profile.age_days is not None else "Unknown", inline=True)
        embed.add_field(name="Linked At", value=record.linked_at, inline=True)
        embed.add_field(name="Profile", value=profile.profile_url, inline=False)
        embed.add_field(name="Description", value=profile.description or "No description.", inline=False)
        embed.add_field(
            name="Owned Systems",
            value="\n".join(f"• {system.name}" for system in owned_systems) or "No owned systems.",
            inline=False,
        )
        if profile.headshot_url:
            embed.set_thumbnail(url=profile.headshot_url)

        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: SalesBot) -> None:
    await bot.add_cog(OAuthCog(bot))
