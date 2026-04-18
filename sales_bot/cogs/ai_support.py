from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from sales_bot.bot import SalesBot
from sales_bot.checks import admin_only
from sales_bot.exceptions import ExternalServiceError


LOGGER = logging.getLogger(__name__)


class AISupportCog(commands.Cog):
    def __init__(self, bot: SalesBot) -> None:
        self.bot = bot

    def _matches_channel(self, message: discord.Message, channel_id: int) -> bool:
        if message.channel.id == channel_id:
            return True

        channel = message.channel
        if isinstance(channel, discord.Thread):
            return channel.parent_id == channel_id
        return False

    def _is_ai_support_message(self, message: discord.Message) -> bool:
        return self._matches_channel(message, self.bot.settings.ai_support_channel_id)

    def _is_ai_training_message(self, message: discord.Message) -> bool:
        return self._matches_channel(message, self.bot.settings.ai_training_channel_id)

    @app_commands.command(name="trainbot", description="Enable AI training mode in the configured AI training channel.")
    @admin_only()
    async def trainbot(self, interaction: discord.Interaction) -> None:
        await self.bot.services.ai_assistant.start_training(interaction.user.id)
        if self.bot.settings.ai_training_channel_id == self.bot.settings.ai_support_channel_id:
            message = (
                f"Training mode is now active. Send knowledge messages in <#{self.bot.settings.ai_training_channel_id}>. "
                "While training mode is active, the assistant will not answer normal questions there, but it will confirm saved training entries."
            )
        else:
            message = (
                f"Training mode is now active. Send knowledge messages in <#{self.bot.settings.ai_training_channel_id}>. "
                f"The assistant will keep answering in <#{self.bot.settings.ai_support_channel_id}> while it confirms saved training entries in the training channel."
            )
        await interaction.response.send_message(
            message,
            ephemeral=True,
        )

    @app_commands.command(name="endtraining", description="Disable AI training mode and resume AI replies.")
    @admin_only()
    async def endtraining(self, interaction: discord.Interaction) -> None:
        await self.bot.services.ai_assistant.end_training()
        if self.bot.settings.ai_training_channel_id == self.bot.settings.ai_support_channel_id:
            message = f"Training mode is off. The assistant will answer again in <#{self.bot.settings.ai_support_channel_id}>."
        else:
            message = (
                f"Training mode is off. New knowledge messages in <#{self.bot.settings.ai_training_channel_id}> will no longer be stored "
                "until you run /trainbot again."
            )
        await interaction.response.send_message(
            message,
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return

        is_support_message = self._is_ai_support_message(message)
        is_training_message = self._is_ai_training_message(message)
        if not is_support_message and not is_training_message:
            return

        try:
            author_is_admin = await self.bot.services.admins.is_admin(message.author.id)
            shared_channel = self.bot.settings.ai_support_channel_id == self.bot.settings.ai_training_channel_id
            training_state = None
            if is_training_message or (shared_channel and is_support_message):
                training_state = await self.bot.services.ai_assistant.get_training_state()

            if is_training_message and training_state is not None and training_state.is_active:
                if author_is_admin:
                    try:
                        record = await self.bot.services.ai_assistant.add_training_message(message, self.bot.http_session)
                        if record is None:
                            LOGGER.info(
                                "AI training message %s in channel %s produced no storable record",
                                message.id,
                                message.channel.id,
                            )
                            return
                        training_reply = self.bot.services.ai_assistant.build_training_acknowledgement(record)
                    except ExternalServiceError as exc:
                        LOGGER.warning(
                            "Failed to store AI training message %s in channel %s: %s",
                            message.id,
                            message.channel.id,
                            exc,
                        )
                        try:
                            await message.reply(
                                f"I couldn't save that training entry right now: {exc}",
                                mention_author=False,
                            )
                        except discord.HTTPException:
                            pass
                        return
                    except Exception:
                        LOGGER.exception(
                            "Unexpected failure while storing AI training message %s in channel %s",
                            message.id,
                            message.channel.id,
                        )
                        try:
                            await message.reply(
                                "I couldn't save that training entry because of an internal error.",
                                mention_author=False,
                            )
                        except discord.HTTPException:
                            pass
                        return

                    try:
                        await message.add_reaction("💾")
                    except discord.HTTPException:
                        pass

                    try:
                        await message.reply(training_reply, mention_author=False)
                    except discord.HTTPException:
                        try:
                            await message.channel.send(training_reply)
                        except discord.HTTPException:
                            LOGGER.warning(
                                "Failed to send AI training acknowledgement for message %s in channel %s",
                                message.id,
                                message.channel.id,
                            )
                else:
                    try:
                        await message.reply(
                            "Training mode is active here, but only admins can add knowledge entries until an admin ends training.",
                            mention_author=False,
                        )
                    except discord.HTTPException:
                        pass
                return

            if is_training_message and not is_support_message:
                if author_is_admin:
                    try:
                        await message.reply(
                            "Training mode is off in this channel. Run /trainbot before sending new knowledge here.",
                            mention_author=False,
                        )
                    except discord.HTTPException:
                        pass
                return

            if not is_support_message:
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
                    answer = await self.bot.services.ai_assistant.answer_message(
                        self.bot.http_session,
                        message,
                        author_is_admin=author_is_admin,
                    )
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
        except Exception:
            LOGGER.exception(
                "Unexpected AI support listener failure for message %s in channel %s",
                message.id,
                message.channel.id,
            )


async def setup(bot: SalesBot) -> None:
    await bot.add_cog(AISupportCog(bot))