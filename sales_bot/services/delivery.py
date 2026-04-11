from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from sales_bot.exceptions import ExternalServiceError, PermissionDeniedError
from sales_bot.models import SystemRecord
from sales_bot.storage import system_message_files

if TYPE_CHECKING:
    from sales_bot.bot import SalesBot


class DeliveryService:
    async def deliver_system(
        self,
        bot: "SalesBot",
        user: discord.abc.User,
        system: SystemRecord,
        *,
        source: str,
        granted_by: int | None,
        record_ownership: bool = True,
    ) -> discord.Message:
        if await bot.services.blacklist.is_blacklisted(user.id):
            raise PermissionDeniedError("That user is blacklisted and cannot receive systems.")

        try:
            dm_channel = user.dm_channel or await user.create_dm()
            embed = bot.services.systems.build_embed(system)
            files, image_name = system_message_files(system.file_path, system.image_path)
            if image_name:
                embed.set_image(url=f"attachment://{image_name}")

            message = await dm_channel.send(embed=embed, files=files)
        except discord.Forbidden as exc:
            raise ExternalServiceError("Unable to DM that user. Ask them to enable DMs and try again.") from exc

        if record_ownership:
            await bot.services.ownership.grant_system(user.id, system.id, granted_by, source)

        await bot.services.ownership.add_delivery_message(
            user_id=user.id,
            system_id=system.id,
            channel_id=message.channel.id,
            message_id=message.id,
            source=source,
        )
        return message

    async def purge_deliveries(
        self,
        bot: "SalesBot",
        *,
        user_id: int,
        system_id: int | None = None,
    ) -> int:
        deleted = 0
        records = await bot.services.ownership.list_delivery_messages(user_id, system_id)
        for record in records:
            try:
                channel = bot.get_channel(record.channel_id) or await bot.fetch_channel(record.channel_id)
                message = await channel.fetch_message(record.message_id)
                await message.delete()
                deleted += 1
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
            finally:
                await bot.services.ownership.delete_delivery_record(record.id)
        return deleted
