from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from sales_bot.bot import SalesBot
from sales_bot.exceptions import ConfigurationError, NotFoundError


class OAuthCog(commands.Cog):
    def __init__(self, bot: SalesBot) -> None:
        self.bot = bot

    @app_commands.command(name="link", description="Get your Roblox OAuth link and connect your account.")
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def link(self, interaction: discord.Interaction) -> None:
        if not self.bot.settings.roblox_oauth_enabled:
            raise ConfigurationError(
                "Roblox OAuth is not configured for this deployment yet. Ask the owner to set the Roblox env vars first."
            )

        state = await self.bot.services.oauth.create_state(interaction.user.id)
        authorization_url = self.bot.services.oauth.build_authorization_url(state)

        embed = discord.Embed(title="Roblox Account Linking", color=discord.Color.blurple())
        embed.description = "Use the button below to complete Roblox OAuth. After the callback succeeds, the bot will store your linked Roblox profile."
        embed.add_field(name="Entry Link", value=self.bot.settings.roblox_entry_link or "Not configured", inline=False)
        embed.add_field(name="Privacy Policy", value=self.bot.settings.roblox_privacy_policy_url or "Not configured", inline=False)
        embed.add_field(name="Terms of Service", value=self.bot.settings.roblox_terms_url or "Not configured", inline=False)
        embed.add_field(name="Redirect URL", value=self.bot.settings.roblox_redirect_uri or "Not configured", inline=False)

        try:
            link_record = await self.bot.services.oauth.get_link(interaction.user.id)
        except NotFoundError:
            pass
        else:
            embed.add_field(
                name="Current Link",
                value=link_record.roblox_username or link_record.roblox_sub,
                inline=False,
            )

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Link Roblox", style=discord.ButtonStyle.link, url=authorization_url))
        view.add_item(discord.ui.Button(label="Privacy Policy", style=discord.ButtonStyle.link, url=self.bot.settings.roblox_privacy_policy_url))
        view.add_item(discord.ui.Button(label="Terms", style=discord.ButtonStyle.link, url=self.bot.settings.roblox_terms_url))
        await interaction.response.send_message(embed=embed, view=view, ephemeral=interaction.guild is not None)


async def setup(bot: SalesBot) -> None:
    await bot.add_cog(OAuthCog(bot))
