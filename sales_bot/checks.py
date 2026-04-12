from __future__ import annotations

from typing import TYPE_CHECKING, cast

from discord import app_commands

if TYPE_CHECKING:
    import discord

    from sales_bot.bot import SalesBot


def admin_only() -> app_commands.Check:
    async def predicate(interaction: discord.Interaction) -> bool:
        bot = interaction.client
        if not hasattr(bot, "services"):
            raise app_commands.CheckFailure("שירותי הבוט עדיין נטענים. נסה שוב בעוד רגע.")

        sales_bot = cast("SalesBot", bot)

        if await sales_bot.services.admins.is_admin(interaction.user.id):
            return True

        raise app_commands.CheckFailure("רק אדמינים של הבוט יכולים להשתמש בפקודה הזאת.")

    return app_commands.check(predicate)


def linked_roblox_required() -> app_commands.Check:
    async def predicate(interaction: discord.Interaction) -> bool:
        bot = interaction.client
        if not hasattr(bot, "services"):
            raise app_commands.CheckFailure("הבוט עדיין נטען. נסה שוב בעוד רגע.")

        sales_bot = cast("SalesBot", bot)

        try:
            await sales_bot.services.oauth.get_link(interaction.user.id)
        except Exception:
            raise app_commands.CheckFailure("כדי להשתמש בפקודה הזאת צריך קודם לקשר חשבון רובלוקס עם `/link`.")

        return True

    return app_commands.check(predicate)
