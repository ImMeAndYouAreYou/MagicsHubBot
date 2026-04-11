from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from sales_bot.bot import SalesBot
from sales_bot.checks import admin_only
from sales_bot.ui.common import ConfirmView, PaginatedSelectView


async def system_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    bot = interaction.client
    if not isinstance(bot, SalesBot):
        return []

    systems = await bot.services.systems.search_systems(current)
    return [app_commands.Choice(name=system.name, value=system.name) for system in systems]


class SystemsCog(commands.Cog):
    def __init__(self, bot: SalesBot) -> None:
        self.bot = bot

    @app_commands.command(name="addsystem", description="Create a new system entry and upload its deliverable files.")
    @app_commands.describe(
        name="Display name for the system.",
        description="Description shown when the system is delivered.",
        file="Primary file to store and deliver.",
        image="Optional preview image attachment.",
        paypal_link="Optional PayPal payment URL for this system.",
    )
    @admin_only()
    async def addsystem(
        self,
        interaction: discord.Interaction,
        name: str,
        description: str,
        file: discord.Attachment,
        image: discord.Attachment | None = None,
        paypal_link: str | None = None,
    ) -> None:
        if image and image.content_type and not image.content_type.startswith("image/"):
            await interaction.response.send_message("The optional image attachment must be an image file.", ephemeral=True)
            return

        system = await self.bot.services.systems.create_system(
            name=name,
            description=description,
            file_attachment=file,
            image_attachment=image,
            created_by=interaction.user.id,
            paypal_link=paypal_link,
        )
        await interaction.response.send_message(
            "System stored successfully.",
            embed=self.bot.services.systems.build_embed(system),
            ephemeral=True,
        )

    @app_commands.command(name="removesystem", description="Choose a stored system from a dropdown and delete it.")
    @admin_only()
    async def removesystem(self, interaction: discord.Interaction) -> None:
        systems = await self.bot.services.systems.list_systems()
        if not systems:
            await interaction.response.send_message("There are no systems to remove.", ephemeral=True)
            return

        async def on_selected(
            select_interaction: discord.Interaction,
            system: object,
            parent_view: PaginatedSelectView,
        ) -> None:
            selected_system = system
            embed = self.bot.services.systems.build_embed(selected_system)
            embed.title = f"Delete {selected_system.name}?"
            embed.color = discord.Color.orange()

            async def on_confirm(confirm_interaction: discord.Interaction, view: ConfirmView) -> None:
                deleted = await self.bot.services.systems.delete_system(selected_system.id)
                await confirm_interaction.response.edit_message(
                    content=f"Deleted system **{deleted.name}**.",
                    embed=None,
                    view=view,
                )

            confirm_view = ConfirmView(actor_id=interaction.user.id, on_confirm=on_confirm)
            await select_interaction.response.edit_message(
                content="Confirm deletion for the selected system.",
                embed=embed,
                view=confirm_view,
            )

        view = PaginatedSelectView(
            actor_id=interaction.user.id,
            items=systems,
            placeholder="Select a system to remove",
            option_builder=lambda system: discord.SelectOption(
                label=system.name[:100],
                description=system.description[:100],
                value=str(system.id),
            ),
            value_getter=lambda system: str(system.id),
            on_selected=on_selected,
        )
        await interaction.response.send_message(
            "Select the system you want to delete.",
            view=view,
            ephemeral=True,
        )

    @app_commands.command(name="sendsystem", description="Send a stored system to a user via DM.")
    @app_commands.describe(user="Recipient for the system delivery.", system="System to deliver.")
    @app_commands.autocomplete(system=system_autocomplete)
    @admin_only()
    async def sendsystem(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        system: str,
    ) -> None:
        selected_system = await self.bot.services.systems.get_system_by_name(system)
        await self.bot.services.delivery.deliver_system(
            self.bot,
            user,
            selected_system,
            source="admin-send",
            granted_by=interaction.user.id,
        )
        await interaction.response.send_message(
            f"Sent **{selected_system.name}** to {user.mention} by DM and recorded ownership.",
            ephemeral=True,
        )


async def setup(bot: SalesBot) -> None:
    await bot.add_cog(SystemsCog(bot))
