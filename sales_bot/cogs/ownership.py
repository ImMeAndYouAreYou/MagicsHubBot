from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from sales_bot.bot import SalesBot
from sales_bot.checks import admin_only
from sales_bot.ui.common import ConfirmView


async def system_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    bot = interaction.client
    if not isinstance(bot, SalesBot):
        return []

    systems = await bot.services.systems.search_systems(current)
    return [app_commands.Choice(name=system.name, value=system.name) for system in systems]


class OwnershipCog(commands.Cog):
    def __init__(self, bot: SalesBot) -> None:
        self.bot = bot

    @app_commands.command(name="checksystems", description="Show the systems currently owned by a user.")
    @app_commands.describe(user="User whose owned systems should be listed.")
    @admin_only()
    async def checksystems(self, interaction: discord.Interaction, user: discord.User) -> None:
        systems = await self.bot.services.ownership.list_user_systems(user.id)
        embed = discord.Embed(title=f"Systems owned by {user}", color=discord.Color.blue())
        if systems:
            embed.description = "\n".join(f"• **{system.name}**" for system in systems)
        else:
            embed.description = "This user does not currently own any systems."
        embed.set_footer(text=f"Total owned: {len(systems)}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="givesystem", description="Preview and confirm a system delivery to a user.")
    @app_commands.describe(user="Recipient for the system.", system="System to grant.")
    @app_commands.autocomplete(system=system_autocomplete)
    @admin_only()
    async def givesystem(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        system: str,
    ) -> None:
        selected_system = await self.bot.services.systems.get_system_by_name(system)
        embed = self.bot.services.systems.build_embed(selected_system)
        embed.title = f"Send {selected_system.name} to {user}?"
        embed.add_field(name="Recipient", value=user.mention, inline=False)

        async def on_confirm(confirm_interaction: discord.Interaction, view: ConfirmView) -> None:
            await self.bot.services.delivery.deliver_system(
                self.bot,
                user,
                selected_system,
                source="grant",
                granted_by=interaction.user.id,
            )
            await confirm_interaction.response.edit_message(
                content=f"Granted **{selected_system.name}** to {user.mention}.",
                embed=embed,
                view=view,
            )

        view = ConfirmView(actor_id=interaction.user.id, on_confirm=on_confirm)
        await interaction.response.send_message(
            "Review the preview below before sending the system.",
            embed=embed,
            view=view,
            ephemeral=True,
        )

    @app_commands.command(name="revokesystem", description="Confirm and revoke a system from a user.")
    @app_commands.describe(user="User whose ownership should be revoked.", system="System to revoke.")
    @app_commands.autocomplete(system=system_autocomplete)
    @admin_only()
    async def revokesystem(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        system: str,
    ) -> None:
        selected_system = await self.bot.services.systems.get_system_by_name(system)
        embed = discord.Embed(
            title="Confirm system revocation",
            description=f"Remove **{selected_system.name}** from {user.mention}?",
            color=discord.Color.orange(),
        )

        async def on_confirm(confirm_interaction: discord.Interaction, view: ConfirmView) -> None:
            await self.bot.services.ownership.revoke_system(user.id, selected_system.id)
            deleted_messages = await self.bot.services.delivery.purge_deliveries(
                self.bot,
                user_id=user.id,
                system_id=selected_system.id,
            )
            await confirm_interaction.response.edit_message(
                content=(
                    f"Revoked **{selected_system.name}** from {user.mention}. "
                    f"Deleted {deleted_messages} DM delivery messages."
                ),
                embed=None,
                view=view,
            )

        view = ConfirmView(actor_id=interaction.user.id, on_confirm=on_confirm)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: SalesBot) -> None:
    await bot.add_cog(OwnershipCog(bot))
