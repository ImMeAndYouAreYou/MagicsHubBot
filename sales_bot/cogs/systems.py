from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from sales_bot.bot import SalesBot
from sales_bot.checks import admin_only, linked_roblox_required
from sales_bot.ui.common import ConfirmView, PaginatedSelectView, edit_interaction_response


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

    @app_commands.command(name="systemslist", description="הצגת כל המערכות שנוספו לבוט.")
    @linked_roblox_required()
    async def systemslist(self, interaction: discord.Interaction) -> None:
        systems = await self.bot.services.systems.list_systems()
        if not systems:
            await interaction.response.send_message("כרגע אין מערכות שמורות בבוט.", ephemeral=True)
            return

        embed = discord.Embed(title="רשימת המערכות", color=discord.Color.blue())
        embed.description = "\n".join(
            f"• **{system.name}**" for system in systems
        )
        embed.set_footer(text=f"סה\"כ מערכות: {len(systems)}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="addsystem", description="Create a new system entry and upload its deliverable files.")
    @app_commands.describe(
        name="Display name for the system.",
        description="Description shown when the system is delivered.",
        file="Primary file to store and deliver.",
        image="Optional preview image attachment.",
        paypal_link="Optional PayPal payment URL for this system.",
        roblox_gamepass="Optional Roblox gamepass ID or link for Robux purchases.",
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
        roblox_gamepass: str | None = None,
    ) -> None:
        if image and image.content_type and not image.content_type.startswith("image/"):
            await interaction.response.send_message("The optional image attachment must be an image file.", ephemeral=True)
            return

        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except discord.HTTPException as exc:
                if exc.code != 40060:
                    raise

        system = await self.bot.services.systems.create_system(
            name=name,
            description=description,
            file_attachment=file,
            image_attachment=image,
            created_by=interaction.user.id,
            paypal_link=paypal_link,
            roblox_gamepass_reference=roblox_gamepass,
        )

        responder = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await responder(
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
                await edit_interaction_response(
                    confirm_interaction,
                    content=f"Deleted system **{deleted.name}**.",
                    embed=None,
                    view=view,
                )

            confirm_view = ConfirmView(actor_id=interaction.user.id, on_confirm=on_confirm)
            await edit_interaction_response(
                select_interaction,
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

    @app_commands.command(name="editsystem", description="Choose a stored system and open its edit panel.")
    @admin_only()
    async def editsystem(self, interaction: discord.Interaction) -> None:
        systems = await self.bot.services.systems.list_systems()
        if not systems:
            await interaction.response.send_message("There are no systems to edit.", ephemeral=True)
            return

        async def on_selected(
            select_interaction: discord.Interaction,
            system: object,
            parent_view: PaginatedSelectView,
        ) -> None:
            selected_system = system
            session = await self.bot.services.panels.create_session(
                admin_user_id=interaction.user.id,
                panel_type="system-edit",
                target_id=selected_system.id,
            )
            panel_url = (
                f"{self.bot.settings.public_base_url}/admin/systems/{selected_system.id}/edit?token={session.token}"
            )

            embed = self.bot.services.systems.build_embed(selected_system)
            embed.title = f"Edit {selected_system.name}"
            embed.add_field(name="Edit Panel", value="Use the button below to change the name, description, file, image, PayPal link, or Roblox gamepass.", inline=False)

            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Open System Edit Panel", style=discord.ButtonStyle.link, url=panel_url))
            await edit_interaction_response(select_interaction, content=None, embed=embed, view=view)

        view = PaginatedSelectView(
            actor_id=interaction.user.id,
            items=systems,
            placeholder="Select a system to edit",
            option_builder=lambda system: discord.SelectOption(
                label=system.name[:100],
                description=system.description[:100],
                value=str(system.id),
            ),
            value_getter=lambda system: str(system.id),
            on_selected=on_selected,
        )
        await interaction.response.send_message(
            "Select the system you want to edit.",
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
