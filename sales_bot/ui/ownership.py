from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord

from sales_bot.exceptions import ExternalServiceError, PermissionDeniedError
from sales_bot.exceptions import NotFoundError
from sales_bot.models import SystemRecord

if TYPE_CHECKING:
    from sales_bot.bot import SalesBot


CLAIMABLE_ROLE_ID = 1492480556385177650


def build_system_names(systems: list[SystemRecord]) -> str:
    return "\n".join(f"• **{system.name}**" for system in systems)


class ClaimRolePanelView(discord.ui.View):
    def __init__(self, bot: "SalesBot") -> None:
        super().__init__(timeout=None)
        self.bot = bot

    async def _resolve_eligible_systems(self, user_id: int) -> list[SystemRecord]:
        eligible: dict[int, SystemRecord] = {
            system.id: system for system in await self.bot.services.ownership.list_claim_role_owned_systems(user_id)
        }
        transfer_locked = await self.bot.services.ownership.list_transfer_locked_system_ids(user_id)

        if self.bot.http_session is None:
            return sorted(eligible.values(), key=lambda system: system.name.lower())

        try:
            await self.bot.services.oauth.get_link(user_id)
        except NotFoundError:
            return sorted(eligible.values(), key=lambda system: system.name.lower())

        for system in await self.bot.services.systems.list_robux_enabled_systems():
            if system.id in eligible or system.id in transfer_locked or not system.roblox_gamepass_id:
                continue

            owns_gamepass = await self.bot.services.oauth.linked_user_owns_gamepass(
                self.bot.http_session,
                discord_user_id=user_id,
                gamepass_id=system.roblox_gamepass_id,
            )
            if owns_gamepass:
                eligible[system.id] = system

        return sorted(eligible.values(), key=lambda system: system.name.lower())

    @discord.ui.button(label="קבלת רול", style=discord.ButtonStyle.success, custom_id="ownership:claim-role")
    async def claim_role_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[Any],
    ) -> None:
        if interaction.guild is None:
            raise PermissionDeniedError("את הפאנל הזה אפשר להפעיל רק מתוך השרת.")

        member = interaction.user if isinstance(interaction.user, discord.Member) else await interaction.guild.fetch_member(interaction.user.id)
        role = interaction.guild.get_role(CLAIMABLE_ROLE_ID)
        if role is None:
            raise ExternalServiceError("לא מצאתי את הרול שהוגדר לפאנל הקבלה.")

        eligible_systems = await self._resolve_eligible_systems(interaction.user.id)
        if not eligible_systems:
            raise PermissionDeniedError("לא נמצאו אצלך מערכות מתאימות לקבלת הרול הזה.")

        embed = discord.Embed(title="רשימת המערכות שמזכות אותך ברול", color=discord.Color.gold())
        embed.description = build_system_names(eligible_systems)

        if role in member.roles:
            await interaction.response.send_message("הרול הזה כבר נמצא אצלך.", embed=embed, ephemeral=True)
            return

        await member.add_roles(role, reason=f"Role claim panel used by {interaction.user.id}")
        await interaction.response.send_message("הרול נוסף אליך בהצלחה.", embed=embed, ephemeral=True)