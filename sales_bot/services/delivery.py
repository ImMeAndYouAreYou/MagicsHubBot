from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import discord

from sales_bot.exceptions import ExternalServiceError, NotFoundError, PermissionDeniedError
from sales_bot.models import SystemRecord

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
            raise PermissionDeniedError("המשתמש הזה נמצא בבלאקליסט ולכן אי אפשר לשלוח לו מערכות.")

        resolved_system_file = bot.services.systems.resolve_asset_path(system.file_path)
        system_file_path = resolved_system_file or Path(system.file_path)
        if not system_file_path.is_file():
            raise NotFoundError(
                "קובץ המערכת לא נמצא על השרת. אם זה קרה אחרי דיפלוי, צריך להשתמש באחסון קבוע או להעלות מחדש את המערכת."
            )

        try:
            dm_channel = user.dm_channel or await user.create_dm()
            system_file = discord.File(system_file_path, filename=system_file_path.name)
            message = await dm_channel.send(
                content=f"הנה המערכת שרצית להוריד {system.name}",
                file=system_file,
            )
        except discord.Forbidden as exc:
            raise ExternalServiceError("לא הצלחתי לשלוח למשתמש הודעה פרטית. בקש ממנו לפתוח DM ונסה שוב.") from exc
        except discord.HTTPException as exc:
            raise ExternalServiceError("אירעה שגיאה בזמן שליחת המערכת ב-DM. נסה שוב בעוד רגע.") from exc

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
