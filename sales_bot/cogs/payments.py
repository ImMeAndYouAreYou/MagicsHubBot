from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from sales_bot.bot import SalesBot
from sales_bot.checks import linked_roblox_required
from sales_bot.exceptions import AlreadyExistsError, PermissionDeniedError
from sales_bot.ui.common import PaginatedSelectView


class PaymentsCog(commands.Cog):
    def __init__(self, bot: SalesBot) -> None:
        self.bot = bot

    async def _validate_buyer(self, user_id: int) -> None:
        if await self.bot.services.blacklist.is_blacklisted(user_id):
            raise PermissionDeniedError("Blacklisted users cannot purchase or receive systems.")

    @app_commands.command(name="buywithpaypal", description="בחירת מערכת עם קישור PayPal.")
    @linked_roblox_required()
    async def buywithpaypal(self, interaction: discord.Interaction) -> None:
        await self._validate_buyer(interaction.user.id)

        systems = await self.bot.services.systems.list_paypal_enabled_systems()
        if not systems:
            await interaction.response.send_message("כרגע אין מערכות עם קישור PayPal מוגדר.", ephemeral=True)
            return

        async def on_selected(
            select_interaction: discord.Interaction,
            system: object,
            parent_view: PaginatedSelectView,
        ) -> None:
            selected_system = system
            if await self.bot.services.ownership.user_owns_system(interaction.user.id, selected_system.id):
                raise AlreadyExistsError("המערכת הזאת כבר בבעלותך.")

            purchase = await self.bot.services.payments.create_purchase(
                interaction.user.id,
                selected_system.id,
                selected_system.paypal_link,
            )

            embed = discord.Embed(title=f"תשלום עבור {selected_system.name}", color=discord.Color.green())
            embed.description = "לחץ על כפתור PayPal למטה. אחרי שהתשלום יאושר דרך הוובהוק, המערכת תישלח אליך ב-DM אוטומטית."
            embed.add_field(name="מזהה רכישה", value=str(purchase.id), inline=False)
            embed.add_field(name="קישור Webhook", value=f"{self.bot.settings.public_base_url}/webhooks/paypal/simulate", inline=False)
            link_view = discord.ui.View()
            link_view.add_item(
                discord.ui.Button(
                    label="פתח PayPal",
                    style=discord.ButtonStyle.link,
                    url=selected_system.paypal_link,
                )
            )
            await select_interaction.response.edit_message(embed=embed, view=link_view)

        view = PaginatedSelectView(
            actor_id=interaction.user.id,
            items=systems,
            placeholder="בחר מערכת לרכישה ב-PayPal",
            option_builder=lambda system: discord.SelectOption(
                label=system.name[:100],
                description=(system.description or "מערכת עם תשלום PayPal")[:100],
                value=str(system.id),
            ),
            value_getter=lambda system: str(system.id),
            on_selected=on_selected,
        )
        await interaction.response.send_message(
            "בחר מערכת לרכישה דרך PayPal.",
            view=view,
            ephemeral=True,
        )

    @app_commands.command(name="buywithrobux", description="בחירת מערכת עם גיימפאס רובלוקס לקניית Robux.")
    @linked_roblox_required()
    async def buywithrobux(self, interaction: discord.Interaction) -> None:
        await self._validate_buyer(interaction.user.id)

        systems = await self.bot.services.systems.list_robux_enabled_systems()
        if not systems:
            await interaction.response.send_message("כרגע אין מערכות עם גיימפאס Roblox מוגדר.", ephemeral=True)
            return

        async def on_selected(
            select_interaction: discord.Interaction,
            system: object,
            parent_view: PaginatedSelectView,
        ) -> None:
            selected_system = system
            if await self.bot.services.ownership.user_owns_system(interaction.user.id, selected_system.id):
                raise AlreadyExistsError("המערכת הזאת כבר בבעלותך.")

            gamepass_url = self.bot.services.systems.gamepass_url_for_id(selected_system.roblox_gamepass_id)
            embed = discord.Embed(title=f"רכישת {selected_system.name} עם Robux", color=discord.Color.blurple())
            embed.description = "לחץ על כפתור הגיימפאס למטה כדי להשלים את הרכישה ב-Robux."
            embed.add_field(name="קישור גיימפאס", value=gamepass_url or "לא מוגדר", inline=False)

            link_view = discord.ui.View()
            link_view.add_item(
                discord.ui.Button(
                    label="פתח גיימפאס",
                    style=discord.ButtonStyle.link,
                    url=gamepass_url,
                )
            )
            await select_interaction.response.edit_message(embed=embed, view=link_view)

        view = PaginatedSelectView(
            actor_id=interaction.user.id,
            items=systems,
            placeholder="בחר מערכת לרכישה ב-Robux",
            option_builder=lambda system: discord.SelectOption(
                label=system.name[:100],
                description=(system.description or "מערכת עם גיימפאס Roblox")[:100],
                value=str(system.id),
            ),
            value_getter=lambda system: str(system.id),
            on_selected=on_selected,
        )
        await interaction.response.send_message(
            "בחר מערכת לרכישה דרך Robux.",
            view=view,
            ephemeral=True,
        )


async def setup(bot: SalesBot) -> None:
    await bot.add_cog(PaymentsCog(bot))
