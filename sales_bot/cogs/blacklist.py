from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from sales_bot.bot import SalesBot
from sales_bot.checks import admin_only
from sales_bot.exceptions import ExternalServiceError
from sales_bot.ui.appeals import AppealDecisionView
from sales_bot.ui.common import ConfirmView, PaginatedSelectView, edit_interaction_response


class BlacklistAppealModal(discord.ui.Modal):
    def __init__(self, bot: SalesBot) -> None:
        super().__init__(title="בקשת הסרת בלאקליסט")
        self.bot = bot
        self.answer_one = discord.ui.TextInput(
            label="למה קיבלת בלאקליסט?",
            style=discord.TextStyle.paragraph,
            max_length=500,
        )
        self.answer_two = discord.ui.TextInput(
            label="למה שנסיר לך את הבלאקליסט?",
            style=discord.TextStyle.paragraph,
            max_length=500,
        )
        self.add_item(self.answer_one)
        self.add_item(self.answer_two)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.bot.services.blacklist.is_blacklisted(interaction.user.id):
            await interaction.response.send_message("אתה לא נמצא כרגע בבלאקליסט.", ephemeral=interaction.guild is not None)
            return

        appeal = await self.bot.services.blacklist.create_appeal(
            interaction.user.id,
            str(self.answer_one),
            str(self.answer_two),
        )
        owner = await self.bot.fetch_user(self.bot.settings.owner_user_id)
        owner_dm = owner.dm_channel or await owner.create_dm()
        embed = discord.Embed(title="בקשת הסרת בלאקליסט חדשה", color=discord.Color.orange())
        embed.add_field(name="משתמש", value=f"{interaction.user.mention} ({interaction.user.id})", inline=False)
        embed.add_field(name="למה קיבלת בלאקליסט?", value=str(self.answer_one), inline=False)
        embed.add_field(name="למה שנסיר לך את הבלאקליסט?", value=str(self.answer_two), inline=False)
        embed.set_footer(text=f"מספר בקשה: {appeal.id}")

        view = AppealDecisionView(self.bot, appeal.id, interaction.user.id)
        try:
            owner_message = await owner_dm.send(embed=embed, view=view)
        except discord.HTTPException as exc:
            raise ExternalServiceError("לא ניתן לשלוח את הבקשה לבעלים דרך ההודעות הישירות.") from exc

        await self.bot.services.blacklist.set_owner_message(appeal.id, owner_message.id)
        self.bot.add_view(view, message_id=owner_message.id)
        await interaction.response.send_message("בקשה נשלחה לבעלים לבדיקה.", ephemeral=interaction.guild is not None)


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
                f"המשתמש {entry.display_label} נוסף לבלאקליסט. "
                f"נמחקו {deleted_messages} הודעות מערכת שנמסרו קודם."
            ),
            ephemeral=True,
        )

    @app_commands.command(name="removeblacklist", description="Pick a blacklisted user from a dropdown and confirm removal.")
    @admin_only()
    async def removeblacklist(self, interaction: discord.Interaction) -> None:
        entries = await self.bot.services.blacklist.list_entries()
        if not entries:
            await interaction.response.send_message("הרשימה השחורה כרגע ריקה.", ephemeral=True)
            return

        async def on_selected(
            select_interaction: discord.Interaction,
            entry: object,
            parent_view: PaginatedSelectView,
        ) -> None:
            selected_entry = entry
            embed = discord.Embed(title="אישור הסרת בלאקליסט", color=discord.Color.orange())
            embed.add_field(name="משתמש", value=selected_entry.display_label, inline=False)
            embed.add_field(name="תאריך הוספה לבלאקליסט", value=selected_entry.blacklisted_at, inline=False)

            async def on_confirm(confirm_interaction: discord.Interaction, view: ConfirmView) -> None:
                await self.bot.services.blacklist.remove_entry(selected_entry.user_id)
                owner = await self.bot.fetch_user(self.bot.settings.owner_user_id)
                await owner.send(
                    f"הסרת הבלאקליסט הושלמה עבור {selected_entry.display_label} על ידי <@{confirm_interaction.user.id}>."
                )
                await edit_interaction_response(
                    confirm_interaction,
                    content=f"המשתמש {selected_entry.display_label} הוסר מהבלאקליסט.",
                    embed=None,
                    view=view,
                )

            confirm_view = ConfirmView(actor_id=interaction.user.id, on_confirm=on_confirm)
            await edit_interaction_response(
                select_interaction,
                content="סקור את פרטי המשתמש שנבחר להסרת בלאקליסט.",
                embed=embed,
                view=confirm_view,
            )

        view = PaginatedSelectView(
            actor_id=interaction.user.id,
            items=entries,
            placeholder="בחר משתמש מהרשימה השחורה",
            option_builder=lambda entry: discord.SelectOption(
                label=entry.display_label[:100],
                description=f"תאריך הוספה לבלאקליסט: {entry.blacklisted_at}"[:100],
                value=str(entry.user_id),
            ),
            value_getter=lambda entry: str(entry.user_id),
            on_selected=on_selected,
        )
        await interaction.response.send_message(
            "בחר פריט מהרשימה השחורה לסקירה.",
            view=view,
            ephemeral=True,
        )

    @app_commands.command(name="requestblacklistremove", description="בקשה להסרת בלאקליסט מהמייסד.")
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def requestblacklistremove(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(BlacklistAppealModal(self.bot))


async def setup(bot: SalesBot) -> None:
    await bot.add_cog(BlacklistCog(bot))
