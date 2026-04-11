from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from sales_bot.bot import SalesBot
from sales_bot.checks import admin_only, linked_roblox_required
from sales_bot.exceptions import AlreadyExistsError, ExternalServiceError, PermissionDeniedError
from sales_bot.ui.common import ConfirmView
from sales_bot.ui.common import PaginatedSelectView


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

    @app_commands.command(name="getsystem", description="קבלת מערכת אם החשבון המקושר שלך מחזיק בגיימפאס המתאים.")
    @linked_roblox_required()
    async def getsystem(self, interaction: discord.Interaction) -> None:
        systems = await self.bot.services.systems.list_systems()
        if not systems:
            await interaction.response.send_message("כרגע אין מערכות זמינות בבוט.", ephemeral=True)
            return

        async def on_selected(
            select_interaction: discord.Interaction,
            system: object,
            parent_view: PaginatedSelectView,
        ) -> None:
            selected_system = system

            if not selected_system.roblox_gamepass_id:
                raise PermissionDeniedError("למערכת הזאת עדיין לא הוגדר גיימפאס Roblox, לכן אי אפשר לקבל אותה דרך הפקודה הזאת.")

            if await self.bot.services.ownership.user_owns_system(interaction.user.id, selected_system.id):
                raise AlreadyExistsError("המערכת הזאת כבר בבעלותך.")

            if self.bot.http_session is None:
                raise ExternalServiceError("חיבור הרשת של הבוט לא זמין כרגע. נסה שוב בעוד רגע.")

            owns_gamepass = await self.bot.services.oauth.linked_user_owns_gamepass(
                self.bot.http_session,
                discord_user_id=interaction.user.id,
                gamepass_id=selected_system.roblox_gamepass_id,
            )
            if not owns_gamepass:
                raise PermissionDeniedError("לפי בדיקת Roblox, החשבון המקושר שלך לא מחזיק בגיימפאס של המערכת הזאת.")

            await self.bot.services.delivery.deliver_system(
                self.bot,
                interaction.user,
                selected_system,
                source="roblox-gamepass-claim",
                granted_by=None,
            )
            await select_interaction.response.edit_message(
                content=f"המערכת **{selected_system.name}** נשלחה אליך ב-DM כי הגיימפאס אומת בהצלחה.",
                embed=None,
                view=None,
            )

        view = PaginatedSelectView(
            actor_id=interaction.user.id,
            items=systems,
            placeholder="בחר מערכת לבדיקה וקבלה",
            option_builder=lambda system: discord.SelectOption(
                label=system.name[:100],
                description=system.description[:100],
                value=str(system.id),
            ),
            value_getter=lambda system: str(system.id),
            on_selected=on_selected,
        )
        await interaction.response.send_message(
            "בחר את המערכת שתרצה לבדוק מולה את הגיימפאס של החשבון המקושר שלך.",
            view=view,
            ephemeral=True,
        )

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
