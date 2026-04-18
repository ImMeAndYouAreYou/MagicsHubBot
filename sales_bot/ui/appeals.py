from __future__ import annotations

import discord

from sales_bot.ui.common import RestrictedView, defer_interaction_response, edit_interaction_response


class AppealActionButton(discord.ui.Button["AppealDecisionView"]):
    def __init__(self, action: str, appeal_id: int) -> None:
        super().__init__(
            label="Accept" if action == "accept" else "Reject",
            style=discord.ButtonStyle.success if action == "accept" else discord.ButtonStyle.danger,
            custom_id=f"appeal:{action}:{appeal_id}",
        )
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is None:
            return
        await self.view.handle_action(interaction, self.action)


class AppealDecisionView(RestrictedView):
    def __init__(self, bot: discord.Client, appeal_id: int, requester_id: int) -> None:
        super().__init__(actor_id=bot.settings.owner_user_id, timeout=None)
        self.bot = bot
        self.appeal_id = appeal_id
        self.requester_id = requester_id
        self.add_item(AppealActionButton("accept", appeal_id))
        self.add_item(AppealActionButton("reject", appeal_id))

    async def handle_action(self, interaction: discord.Interaction, action: str) -> None:
        await defer_interaction_response(interaction)

        if action == "accept" and await self.bot.services.blacklist.is_blacklisted(self.requester_id):
            await self.bot.services.blacklist.remove_entry(self.requester_id)

        appeal = await self.bot.services.blacklist.resolve_appeal(
            self.appeal_id,
            reviewer_id=interaction.user.id,
            status="accepted" if action == "accept" else "rejected",
        )

        decision_text = (
            "Your blacklist appeal was accepted and your blacklist entry has been removed."
            if action == "accept"
            else "Your blacklist appeal was rejected."
        )

        try:
            requester = await self.bot.fetch_user(self.requester_id)
            await requester.send(decision_text)
        except discord.HTTPException:
            pass

        embed = interaction.message.embeds[0].copy() if interaction.message and interaction.message.embeds else discord.Embed()
        embed.color = discord.Color.green() if action == "accept" else discord.Color.red()
        embed.add_field(
            name="Decision",
            value=f"{appeal.status.title()} by <@{interaction.user.id}>",
            inline=False,
        )
        self.disable_all_items()
        await edit_interaction_response(interaction, embed=embed, view=self)
        self.stop()
