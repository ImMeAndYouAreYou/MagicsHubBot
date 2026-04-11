from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from sales_bot.bot import SalesBot
from sales_bot.checks import admin_only
from sales_bot.exceptions import ExternalServiceError
from sales_bot.ui.appeals import AppealDecisionView
from sales_bot.ui.common import ConfirmView, PaginatedSelectView


class BlacklistAppealModal(discord.ui.Modal):
    def __init__(self, bot: SalesBot) -> None:
        super().__init__(title="Blacklist Removal Request")
        self.bot = bot
        self.answer_one = discord.ui.TextInput(
            label="Why are you blacklisted?",
            style=discord.TextStyle.paragraph,
            max_length=500,
        )
        self.answer_two = discord.ui.TextInput(
            label="Why should we remove it?",
            style=discord.TextStyle.paragraph,
            max_length=500,
        )
        self.add_item(self.answer_one)
        self.add_item(self.answer_two)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.bot.services.blacklist.is_blacklisted(interaction.user.id):
            await interaction.response.send_message("You are not currently blacklisted.", ephemeral=interaction.guild is not None)
            return

        appeal = await self.bot.services.blacklist.create_appeal(
            interaction.user.id,
            str(self.answer_one),
            str(self.answer_two),
        )
        owner = await self.bot.fetch_user(self.bot.settings.owner_user_id)
        owner_dm = owner.dm_channel or await owner.create_dm()
        embed = discord.Embed(title="New Blacklist Appeal", color=discord.Color.orange())
        embed.add_field(name="User", value=f"{interaction.user.mention} ({interaction.user.id})", inline=False)
        embed.add_field(name="Why blacklisted?", value=str(self.answer_one), inline=False)
        embed.add_field(name="Why remove it?", value=str(self.answer_two), inline=False)
        embed.set_footer(text=f"Appeal ID: {appeal.id}")

        view = AppealDecisionView(self.bot, appeal.id, interaction.user.id)
        try:
            owner_message = await owner_dm.send(embed=embed, view=view)
        except discord.HTTPException as exc:
            raise ExternalServiceError("Unable to deliver the appeal to the configured owner DM.") from exc

        await self.bot.services.blacklist.set_owner_message(appeal.id, owner_message.id)
        self.bot.add_view(view, message_id=owner_message.id)
        await interaction.response.send_message("Request sent to the owner for review.", ephemeral=interaction.guild is not None)


class BlacklistCog(commands.Cog):
    def __init__(self, bot: SalesBot) -> None:
        self.bot = bot

    @app_commands.command(name="blacklist", description="Blacklist a user and remove prior delivered system messages.")
    @app_commands.describe(user="User to blacklist.")
    @admin_only()
    async def blacklist(self, interaction: discord.Interaction, user: discord.User) -> None:
        entry = await self.bot.services.blacklist.add_entry(
            user.id,
            self.bot.services.blacklist.build_display_label(user.id),
            interaction.user.id,
        )
        deleted_messages = await self.bot.services.delivery.purge_deliveries(self.bot, user_id=user.id)
        await interaction.response.send_message(
            (
                f"Blacklisted {entry.display_label}. "
                f"Deleted {deleted_messages} previously delivered system messages."
            ),
            ephemeral=True,
        )

    @app_commands.command(name="removeblacklist", description="Pick a blacklisted user from a dropdown and confirm removal.")
    @admin_only()
    async def removeblacklist(self, interaction: discord.Interaction) -> None:
        entries = await self.bot.services.blacklist.list_entries()
        if not entries:
            await interaction.response.send_message("The blacklist is currently empty.", ephemeral=True)
            return

        async def on_selected(
            select_interaction: discord.Interaction,
            entry: object,
            parent_view: PaginatedSelectView,
        ) -> None:
            selected_entry = entry
            embed = discord.Embed(title="Confirm blacklist removal", color=discord.Color.orange())
            embed.add_field(name="User", value=selected_entry.display_label, inline=False)
            embed.add_field(name="Blacklisted At", value=selected_entry.blacklisted_at, inline=False)

            async def on_confirm(confirm_interaction: discord.Interaction, view: ConfirmView) -> None:
                await self.bot.services.blacklist.remove_entry(selected_entry.user_id)
                owner = await self.bot.fetch_user(self.bot.settings.owner_user_id)
                await owner.send(
                    f"Blacklist removal completed for {selected_entry.display_label} by <@{confirm_interaction.user.id}>."
                )
                await confirm_interaction.response.edit_message(
                    content=f"Removed {selected_entry.display_label} from the blacklist.",
                    embed=None,
                    view=view,
                )

            confirm_view = ConfirmView(actor_id=interaction.user.id, on_confirm=on_confirm)
            await select_interaction.response.edit_message(
                content="Review the selected blacklist entry.",
                embed=embed,
                view=confirm_view,
            )

        view = PaginatedSelectView(
            actor_id=interaction.user.id,
            items=entries,
            placeholder="Select a blacklisted user",
            option_builder=lambda entry: discord.SelectOption(
                label=entry.display_label[:100],
                description=f"Blacklisted at {entry.blacklisted_at}"[:100],
                value=str(entry.user_id),
            ),
            value_getter=lambda entry: str(entry.user_id),
            on_selected=on_selected,
        )
        await interaction.response.send_message(
            "Select a blacklist entry to review.",
            view=view,
            ephemeral=True,
        )

    @app_commands.command(name="requestblacklistremove", description="Submit a blacklist appeal form to the owner.")
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def requestblacklistremove(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(BlacklistAppealModal(self.bot))


async def setup(bot: SalesBot) -> None:
    await bot.add_cog(BlacklistCog(bot))
