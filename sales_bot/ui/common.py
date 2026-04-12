from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from math import ceil
from typing import Any

import discord

from sales_bot.exceptions import SalesBotError


LOGGER = logging.getLogger(__name__)

ConfirmHandler = Callable[[discord.Interaction, "ConfirmView"], Awaitable[None]]
SelectHandler = Callable[[discord.Interaction, Any, "PaginatedSelectView"], Awaitable[None]]
OptionBuilder = Callable[[Any], discord.SelectOption]
ValueGetter = Callable[[Any], str]


class RestrictedView(discord.ui.View):
    def __init__(self, actor_id: int, *, timeout: float | None = 180) -> None:
        super().__init__(timeout=timeout)
        self.actor_id = actor_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.actor_id:
            responder = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
            await responder("אין לך הרשאה להשתמש בפאנל הזה.", ephemeral=True)
            return False
        return True

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item[Any],
    ) -> None:
        LOGGER.exception("View interaction error in %s", type(self).__name__, exc_info=error)
        message = str(error) if isinstance(error, SalesBotError) else "אירעה שגיאה לא צפויה בפאנל."
        responder = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await responder(message, ephemeral=True)

    def disable_all_items(self) -> None:
        for item in self.children:
            item.disabled = True


class ConfirmView(RestrictedView):
    def __init__(
        self,
        *,
        actor_id: int,
        on_confirm: ConfirmHandler,
        on_cancel: ConfirmHandler | None = None,
        timeout: float | None = 180,
    ) -> None:
        super().__init__(actor_id, timeout=timeout)
        self._on_confirm = on_confirm
        self._on_cancel = on_cancel

    @discord.ui.button(label="אישור", style=discord.ButtonStyle.success)
    async def confirm_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[Any],
    ) -> None:
        self.disable_all_items()
        await self._on_confirm(interaction, self)
        self.stop()

    @discord.ui.button(label="ביטול", style=discord.ButtonStyle.secondary)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[Any],
    ) -> None:
        self.disable_all_items()
        if self._on_cancel is not None:
            await self._on_cancel(interaction, self)
        else:
            await interaction.response.edit_message(content="הפעולה בוטלה.", view=self)
        self.stop()


class _PaginatedSelect(discord.ui.Select["PaginatedSelectView"]):
    def __init__(self, parent_view: "PaginatedSelectView") -> None:
        self.parent_view = parent_view
        super().__init__(placeholder=parent_view.placeholder, options=[])

    async def callback(self, interaction: discord.Interaction) -> None:
        selected = self.parent_view.get_selected_item(self.values[0])
        await self.parent_view.on_selected(interaction, selected, self.parent_view)


class PaginatedSelectView(RestrictedView):
    def __init__(
        self,
        *,
        actor_id: int,
        items: Sequence[Any],
        placeholder: str,
        option_builder: OptionBuilder,
        value_getter: ValueGetter,
        on_selected: SelectHandler,
        timeout: float | None = 180,
    ) -> None:
        super().__init__(actor_id, timeout=timeout)
        self.items = list(items)
        self.placeholder = placeholder
        self.option_builder = option_builder
        self.value_getter = value_getter
        self.on_selected = on_selected
        self.page_index = 0
        self._value_map: dict[str, Any] = {}
        self.select_menu = _PaginatedSelect(self)
        self.add_item(self.select_menu)
        self._refresh_components()

    def page_count(self) -> int:
        return max(1, ceil(len(self.items) / 25))

    def current_items(self) -> list[Any]:
        start = self.page_index * 25
        end = start + 25
        return self.items[start:end]

    def get_selected_item(self, value: str) -> Any:
        return self._value_map[value]

    def _refresh_components(self) -> None:
        current = self.current_items()
        self._value_map = {self.value_getter(item): item for item in current}
        options = [self.option_builder(item) for item in current]
        if not options:
            options = [discord.SelectOption(label="אין פריטים זמינים", value="empty", default=True)]

        self.select_menu.options = options
        self.select_menu.disabled = len(current) == 0
        self.select_menu.placeholder = f"{self.placeholder} ({self.page_index + 1}/{self.page_count()})"
        self.previous_button.disabled = self.page_index <= 0 or len(self.items) <= 25
        self.next_button.disabled = self.page_index >= self.page_count() - 1 or len(self.items) <= 25

    @discord.ui.button(label="הקודם", style=discord.ButtonStyle.secondary, row=1)
    async def previous_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[Any],
    ) -> None:
        self.page_index -= 1
        self._refresh_components()
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="הבא", style=discord.ButtonStyle.secondary, row=1)
    async def next_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[Any],
    ) -> None:
        self.page_index += 1
        self._refresh_components()
        await interaction.response.edit_message(view=self)
