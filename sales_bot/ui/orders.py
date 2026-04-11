from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import discord

from sales_bot.exceptions import ExternalServiceError, PermissionDeniedError
from sales_bot.ui.common import RestrictedView


@dataclass(slots=True)
class OrderDraft:
    requested_item: str
    required_timeframe: str
    payment_method: str
    offered_price: str


def build_order_embed(title: str, draft: OrderDraft, *, user: discord.abc.User | None = None) -> discord.Embed:
    embed = discord.Embed(title=title, color=discord.Color.gold())
    if user is not None:
        embed.add_field(name="מזמין", value=f"{user.mention} ({user.id})", inline=False)
    embed.add_field(name="מה אתה רוצה להזמין", value=draft.requested_item, inline=False)
    embed.add_field(name="תוך כמה זמן אתה צריך את זה", value=draft.required_timeframe, inline=False)
    embed.add_field(name="איך אתה משלם", value=draft.payment_method, inline=False)
    embed.add_field(name="כמה אתה מוכן לשלם", value=draft.offered_price, inline=False)
    return embed


class OrderModal(discord.ui.Modal):
    def __init__(self, bot: discord.Client, *, draft: OrderDraft | None = None) -> None:
        super().__init__(title="טופס הזמנה אישית")
        self.bot = bot
        self.requested_item_input = discord.ui.TextInput(
            label="מה אתה רוצה להזמין",
            style=discord.TextStyle.paragraph,
            max_length=500,
            default=draft.requested_item if draft else None,
        )
        self.required_timeframe_input = discord.ui.TextInput(
            label="תוך כמה זמן אתה צריך את זה",
            style=discord.TextStyle.short,
            max_length=200,
            default=draft.required_timeframe if draft else None,
        )
        self.payment_method_input = discord.ui.TextInput(
            label="איך אתה משלם (כסף אמיתי / רובקס)",
            style=discord.TextStyle.short,
            max_length=100,
            default=draft.payment_method if draft else None,
        )
        self.offered_price_input = discord.ui.TextInput(
            label="כמה אתה מוכן לשלם",
            style=discord.TextStyle.short,
            max_length=100,
            default=draft.offered_price if draft else None,
        )
        self.add_item(self.requested_item_input)
        self.add_item(self.required_timeframe_input)
        self.add_item(self.payment_method_input)
        self.add_item(self.offered_price_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        draft = OrderDraft(
            requested_item=str(self.requested_item_input),
            required_timeframe=str(self.required_timeframe_input),
            payment_method=str(self.payment_method_input),
            offered_price=str(self.offered_price_input),
        )
        view = OrderPreviewView(self.bot, actor_id=interaction.user.id, draft=draft)
        embed = build_order_embed("תצוגה מקדימה של ההזמנה", draft, user=interaction.user)
        await interaction.response.send_message(
            content="בדוק את ההזמנה שלך לפני שליחה.",
            embed=embed,
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()


class OrderPanelView(discord.ui.View):
    def __init__(self, bot: discord.Client) -> None:
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="הזמן", style=discord.ButtonStyle.primary, custom_id="orders:create")
    async def create_order_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[Any],
    ) -> None:
        try:
            await self.bot.services.oauth.get_link(interaction.user.id)
        except Exception:
            await interaction.response.send_message(
                "כדי לפתוח הזמנה אישית צריך קודם לקשר את חשבון הרובלוקס שלך עם `/link`.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(OrderModal(self.bot))


class OrderPreviewView(RestrictedView):
    def __init__(self, bot: discord.Client, *, actor_id: int, draft: OrderDraft) -> None:
        super().__init__(actor_id=actor_id, timeout=300)
        self.bot = bot
        self.draft = draft
        self.message: discord.InteractionMessage | None = None

    @discord.ui.button(label="לערוך", style=discord.ButtonStyle.primary)
    async def edit_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[Any],
    ) -> None:
        await interaction.response.send_modal(OrderModal(self.bot, draft=self.draft))

    @discord.ui.button(label="לשלוח הזמנה", style=discord.ButtonStyle.success)
    async def submit_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[Any],
    ) -> None:
        order = await self.bot.services.orders.create_request(
            user_id=interaction.user.id,
            requested_item=self.draft.requested_item,
            required_timeframe=self.draft.required_timeframe,
            payment_method=self.draft.payment_method,
            offered_price=self.draft.offered_price,
        )

        owner = await self.bot.fetch_user(self.bot.settings.owner_user_id)
        owner_dm = owner.dm_channel or await owner.create_dm()
        owner_embed = build_order_embed("הזמנה חדשה בהכנה אישית", self.draft, user=interaction.user)
        owner_embed.set_footer(text=f"מספר הזמנה: {order.id}")
        decision_view = OrderDecisionView(self.bot, order.id, interaction.user.id)

        try:
            owner_message = await owner_dm.send(embed=owner_embed, view=decision_view)
        except discord.HTTPException as exc:
            raise ExternalServiceError("לא הצלחתי לשלוח את ההזמנה לבעלים ב-DM.") from exc

        await self.bot.services.orders.set_owner_message(order.id, owner_message.id)
        self.bot.add_view(decision_view, message_id=owner_message.id)
        self.disable_all_items()
        await interaction.response.edit_message(
            content="ההזמנה נשלחה בהצלחה לבעלים.",
            embed=build_order_embed("ההזמנה שלך נשלחה", self.draft, user=interaction.user),
            view=self,
        )
        self.stop()

    @discord.ui.button(label="לבטל הזמנה", style=discord.ButtonStyle.secondary)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[Any],
    ) -> None:
        self.disable_all_items()
        await interaction.response.edit_message(content="ההזמנה בוטלה.", embed=None, view=self)
        self.stop()


class OrderDecisionButton(discord.ui.Button["OrderDecisionView"]):
    def __init__(self, action: str, order_id: int) -> None:
        super().__init__(
            label="Accept Order" if action == "accept" else "Reject Order",
            style=discord.ButtonStyle.success if action == "accept" else discord.ButtonStyle.danger,
            custom_id=f"order:{action}:{order_id}",
        )
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is None:
            return
        await self.view.handle_action(interaction, self.action)


class OrderDecisionView(RestrictedView):
    def __init__(self, bot: discord.Client, order_id: int, requester_id: int) -> None:
        super().__init__(actor_id=bot.settings.owner_user_id, timeout=None)
        self.bot = bot
        self.order_id = order_id
        self.requester_id = requester_id
        self.add_item(OrderDecisionButton("accept", order_id))
        self.add_item(OrderDecisionButton("reject", order_id))

    async def handle_action(self, interaction: discord.Interaction, action: str) -> None:
        order = await self.bot.services.orders.resolve_request(
            self.order_id,
            reviewer_id=interaction.user.id,
            status="accepted" if action == "accept" else "rejected",
        )

        decision_text = (
            "ההזמנה האישית שלך התקבלה. הבעלים יחזור אליך בהמשך."
            if action == "accept"
            else "ההזמנה האישית שלך נדחתה."
        )
        try:
            requester = await self.bot.fetch_user(self.requester_id)
            await requester.send(decision_text)
        except discord.HTTPException:
            pass

        embed = interaction.message.embeds[0].copy() if interaction.message and interaction.message.embeds else discord.Embed()
        embed.color = discord.Color.green() if action == "accept" else discord.Color.red()
        embed.add_field(name="סטטוס", value="התקבל" if action == "accept" else "נדחה", inline=False)
        self.disable_all_items()
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()