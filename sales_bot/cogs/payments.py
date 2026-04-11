from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from sales_bot.bot import SalesBot
from sales_bot.exceptions import AlreadyExistsError, PermissionDeniedError
from sales_bot.ui.common import PaginatedSelectView


class PaymentsCog(commands.Cog):
    def __init__(self, bot: SalesBot) -> None:
        self.bot = bot

    @app_commands.command(name="buywithpaypal", description="Choose a system with a PayPal link and receive the payment link.")
    async def buywithpaypal(self, interaction: discord.Interaction) -> None:
        if await self.bot.services.blacklist.is_blacklisted(interaction.user.id):
            raise PermissionDeniedError("Blacklisted users cannot purchase or receive systems.")

        systems = await self.bot.services.systems.list_paypal_enabled_systems()
        if not systems:
            await interaction.response.send_message("No systems currently have PayPal purchase links configured.", ephemeral=True)
            return

        async def on_selected(
            select_interaction: discord.Interaction,
            system: object,
            parent_view: PaginatedSelectView,
        ) -> None:
            selected_system = system
            if await self.bot.services.ownership.user_owns_system(interaction.user.id, selected_system.id):
                raise AlreadyExistsError("You already own that system.")

            purchase = await self.bot.services.payments.create_purchase(
                interaction.user.id,
                selected_system.id,
                selected_system.paypal_link,
            )

            embed = discord.Embed(title=f"Pay for {selected_system.name}", color=discord.Color.green())
            embed.description = "Use the PayPal button below. Once the webhook reports the payment as completed, the bot will DM your system automatically."
            embed.add_field(name="Purchase ID", value=str(purchase.id), inline=False)
            embed.add_field(name="Webhook Endpoint", value=f"{self.bot.settings.public_base_url}/webhooks/paypal/simulate", inline=False)
            link_view = discord.ui.View()
            link_view.add_item(
                discord.ui.Button(
                    label="Open PayPal",
                    style=discord.ButtonStyle.link,
                    url=selected_system.paypal_link,
                )
            )
            await select_interaction.response.edit_message(embed=embed, view=link_view)

        view = PaginatedSelectView(
            actor_id=interaction.user.id,
            items=systems,
            placeholder="Select a system to buy",
            option_builder=lambda system: discord.SelectOption(
                label=system.name[:100],
                description=(system.description or "Configured PayPal checkout")[:100],
                value=str(system.id),
            ),
            value_getter=lambda system: str(system.id),
            on_selected=on_selected,
        )
        await interaction.response.send_message(
            "Pick a system to purchase via PayPal.",
            view=view,
            ephemeral=True,
        )


async def setup(bot: SalesBot) -> None:
    await bot.add_cog(PaymentsCog(bot))
