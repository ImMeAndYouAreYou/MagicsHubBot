from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from sales_bot.bot import SalesBot
from sales_bot.checks import admin_only
from sales_bot.exceptions import ExternalServiceError


class AISupportCog(commands.Cog):
    def __init__(self, bot: SalesBot) -> None:
        self.bot = bot

    @app_commands.command(name="trainbot", description="Enable AI training mode in the configured AI support channel.")
    @admin_only()
    async def trainbot(self, interaction: discord.Interaction) -> None:
        await self.bot.services.ai_assistant.start_training(interaction.user.id)
        await interaction.response.send_message(
            (
                f"Training mode is now active. Send knowledge messages in <#{self.bot.settings.ai_support_channel_id}>. "
                "While training mode is active, the assistant will not answer questions there."
            ),
            ephemeral=True,
        )

    @app_commands.command(name="endtraining", description="Disable AI training mode and resume AI replies.")
    @admin_only()
    async def endtraining(self, interaction: discord.Interaction) -> None:
        await self.bot.services.ai_assistant.end_training()
        await interaction.response.send_message(
            f"Training mode is off. The assistant will answer again in <#{self.bot.settings.ai_support_channel_id}>.",
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        if message.channel.id != self.bot.settings.ai_support_channel_id:
            return

        training_state = await self.bot.services.ai_assistant.get_training_state()
        if training_state.is_active:
            if await self.bot.services.admins.is_admin(message.author.id):
                record = await self.bot.services.ai_assistant.add_training_message(message, self.bot.http_session)
                if record is not None:
                    try:
                        await message.add_reaction("💾")
                    except discord.HTTPException:
                        pass
            else:
                try:
                    await message.reply(
                        "Training mode is active right now, so replies are paused until an admin ends training.",
                        mention_author=False,
                    )
                except discord.HTTPException:
                    pass
            return

        if self.bot.http_session is None:
            return

        has_supported_attachments = any(
            (
                attachment.content_type and attachment.content_type.startswith("image/")
            ) or attachment.content_type and attachment.content_type.startswith("text/")
            for attachment in message.attachments
        )
        has_links = "http://" in message.content or "https://" in message.content
        if not message.content.strip() and not message.attachments and not has_links and not has_supported_attachments:
            return

        try:
            async with message.channel.typing():
                answer = await self.bot.services.ai_assistant.answer_message(self.bot.http_session, message)
        except ExternalServiceError as exc:
            try:
                await message.reply(str(exc), mention_author=False)
            except discord.HTTPException:
                pass
            return

        for index, chunk in enumerate(self.bot.services.ai_assistant.chunk_response(answer)):
            try:
                if index == 0:
                    await message.reply(chunk, mention_author=False)
                else:
                    await message.channel.send(chunk)
            except discord.HTTPException:
                return


async def setup(bot: SalesBot) -> None:
    await bot.add_cog(AISupportCog(bot))