from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import discord

from sales_bot.exceptions import ExternalServiceError, PermissionDeniedError, SalesBotError
from sales_bot.models import SystemRecord
from sales_bot.services.ownership import CLAIMABLE_ROLE_ID

if TYPE_CHECKING:
    from sales_bot.bot import SalesBot


LOGGER = logging.getLogger(__name__)


def build_system_names(systems: list[SystemRecord]) -> str:
    return "\n".join(f"• **{system.name}**" for system in systems)


class ClaimRolePanelView(discord.ui.View):
    def __init__(self, bot: "SalesBot") -> None:
        super().__init__(timeout=None)
        self.bot = bot

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item[Any],
    ) -> None:
        LOGGER.exception("View interaction error in %s", type(self).__name__, exc_info=error)
        message = str(error) if isinstance(error, SalesBotError) else "אירעה שגיאה לא צפויה בפאנל."
        responder = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        try:
            await responder(message, ephemeral=True)
        except discord.HTTPException:
            pass

    async def _resolve_eligible_systems(self, user_id: int) -> list[SystemRecord]:
        await self.bot.services.ownership.sync_linked_gamepass_ownerships(self.bot, user_id)
        return await self.bot.services.ownership.list_claim_role_owned_systems(user_id)

    @discord.ui.button(label="קבלת רול", style=discord.ButtonStyle.success, custom_id="ownership:claim-role")
    async def claim_role_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[Any],
    ) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True, thinking=True)
            except discord.HTTPException as exc:
                if exc.code != 40060:
                    raise

        if interaction.guild is None:
            raise PermissionDeniedError("את הפאנל הזה אפשר להפעיל רק מתוך השרת.")

        responder = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        member = interaction.user if isinstance(interaction.user, discord.Member) else await interaction.guild.fetch_member(interaction.user.id)
        role = interaction.guild.get_role(CLAIMABLE_ROLE_ID)
        if role is None:
            raise ExternalServiceError("לא מצאתי את הרול שהוגדר לפאנל הקבלה.")

        if role in member.roles:
            await responder("הרול הזה כבר נמצא אצלך.", ephemeral=True)
            return

        eligible_systems = await self._resolve_eligible_systems(interaction.user.id)
        if not eligible_systems:
            raise PermissionDeniedError("לא נמצאו אצלך מערכות מתאימות לקבלת הרול הזה.")

        embed = discord.Embed(title="רשימת המערכות שמזכות אותך ברול", color=discord.Color.gold())
        embed.description = build_system_names(eligible_systems)

        try:
            await member.add_roles(role, reason=f"Role claim panel used by {interaction.user.id}")
        except discord.Forbidden as exc:
            raise ExternalServiceError("אין לי הרשאה להוסיף את הרול הזה.") from exc
        except discord.HTTPException as exc:
            raise ExternalServiceError("לא הצלחתי להוסיף את הרול כרגע. נסה שוב בעוד רגע.") from exc

        await responder("הרול נוסף אליך בהצלחה.", embed=embed, ephemeral=True)