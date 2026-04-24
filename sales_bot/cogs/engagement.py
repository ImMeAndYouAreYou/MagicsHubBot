from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from sales_bot.bot import SalesBot
from sales_bot.checks import admin_only
from sales_bot.models import EventRecord
from sales_bot.ui.common import PaginatedSelectView, edit_interaction_response


def _event_option(event: EventRecord) -> discord.SelectOption:
    label = f"#{event.id} {event.title}"[:100]
    status_label = "הסתיים" if event.status.strip().lower() == "ended" else "פתוח"
    description = f"{event.reward} | {status_label}"[:100]
    return discord.SelectOption(label=label, value=str(event.id), description=description)


def _event_value(event: EventRecord) -> str:
    return str(event.id)


class EngagementCog(commands.Cog):
    def __init__(self, bot: SalesBot) -> None:
        self.bot = bot

    async def _send_roll_selector(
        self,
        interaction: discord.Interaction,
        *,
        events: list[EventRecord],
        title: str,
        placeholder: str,
        reroll: bool,
    ) -> None:
        if not events:
            message = "אין כרגע אירועים זמינים לרול." if not reroll else "אין כרגע אירועים זמינים לרירול."
            await interaction.response.send_message(message, ephemeral=True)
            return

        async def on_selected(
            select_interaction: discord.Interaction,
            selected_event: EventRecord,
            view: PaginatedSelectView,
        ) -> None:
            if reroll:
                updated_event, winner, _message = await self.bot.services.events.reroll_winner(
                    self.bot,
                    event_id=selected_event.id,
                )
                feedback = f"בוצע רירול לאירוע #{updated_event.id}. הזוכה החדש הוא {winner.mention}."
            else:
                updated_event, winner, _message = await self.bot.services.events.roll_winner(
                    self.bot,
                    event_id=selected_event.id,
                )
                feedback = f"נבחר זוכה לאירוע #{updated_event.id}: {winner.mention}."
            view.disable_all_items()
            await edit_interaction_response(select_interaction, content=feedback, view=view)

        view = PaginatedSelectView(
            actor_id=interaction.user.id,
            items=events,
            placeholder=placeholder,
            option_builder=_event_option,
            value_getter=_event_value,
            on_selected=on_selected,
        )
        await interaction.response.send_message(title, view=view, ephemeral=True)

    @app_commands.command(name="poll", description="פתיחת פאנל הניהול ליצירת סקר.")
    @admin_only()
    async def poll(self, interaction: discord.Interaction) -> None:
        session = await self.bot.services.panels.create_session(
            admin_user_id=interaction.user.id,
            panel_type="poll-create",
        )
        panel_url = f"{self.bot.settings.public_base_url}/admin/polls/new?token={session.token}"
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="פתח את פאנל הסקרים", style=discord.ButtonStyle.link, url=panel_url))

        embed = discord.Embed(title="פאנל סקרים", color=discord.Color.blurple())
        embed.description = "לחצו על הכפתור למטה כדי לפתוח את פאנל הניהול, ליצור סקר ולפרסם אותו."
        embed.add_field(name="תוקף הקישור", value=f"{self.bot.settings.admin_panel_session_minutes} דקות", inline=False)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="editpoll", description="פתיחת פאנל הניהול לעריכת סקר קיים.")
    @app_commands.describe(poll_id="מזהה הסקר כפי שמופיע בהודעת הסקר.")
    @admin_only()
    async def editpoll(self, interaction: discord.Interaction, poll_id: int) -> None:
        poll = await self.bot.services.polls.get_editable_poll(poll_id)
        session = await self.bot.services.panels.create_session(
            admin_user_id=interaction.user.id,
            panel_type="poll-edit",
            target_id=poll.id,
        )
        panel_url = f"{self.bot.settings.public_base_url}/admin/polls/{poll.id}/edit?token={session.token}"
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="ערוך את הסקר", style=discord.ButtonStyle.link, url=panel_url))

        embed = discord.Embed(title=f"עריכת סקר #{poll.id}", color=discord.Color.blurple())
        embed.description = poll.question
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="giveaway", description="פתיחת פאנל הניהול ליצירת הגרלה.")
    @admin_only()
    async def giveaway(self, interaction: discord.Interaction) -> None:
        session = await self.bot.services.panels.create_session(
            admin_user_id=interaction.user.id,
            panel_type="giveaway-create",
        )
        panel_url = f"{self.bot.settings.public_base_url}/admin/giveaways/new?token={session.token}"
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="פתח את פאנל ההגרלות", style=discord.ButtonStyle.link, url=panel_url))

        embed = discord.Embed(title="פאנל הגרלות", color=discord.Color.green())
        embed.description = "לחצו על הכפתור למטה כדי לפתוח את פאנל הניהול, ליצור הגרלה ולפרסם אותה."
        embed.add_field(name="תוקף הקישור", value=f"{self.bot.settings.admin_panel_session_minutes} דקות", inline=False)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="editgiveaway", description="פתיחת פאנל הניהול לעריכת הגרלה קיימת.")
    @app_commands.describe(giveaway_id="מזהה ההגרלה כפי שמופיע בהודעת ההגרלה.")
    @admin_only()
    async def editgiveaway(self, interaction: discord.Interaction, giveaway_id: int) -> None:
        giveaway = await self.bot.services.giveaways.get_editable_giveaway(giveaway_id)
        session = await self.bot.services.panels.create_session(
            admin_user_id=interaction.user.id,
            panel_type="giveaway-edit",
            target_id=giveaway.id,
        )
        panel_url = f"{self.bot.settings.public_base_url}/admin/giveaways/{giveaway.id}/edit?token={session.token}"
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="ערוך את ההגרלה", style=discord.ButtonStyle.link, url=panel_url))

        embed = discord.Embed(title=f"עריכת הגרלה #{giveaway.id}", color=discord.Color.green())
        embed.description = giveaway.title
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="createevent", description="פתיחת פאנל הניהול ליצירת אירוע.")
    @admin_only()
    async def createevent(self, interaction: discord.Interaction) -> None:
        session = await self.bot.services.panels.create_session(
            admin_user_id=interaction.user.id,
            panel_type="event-create",
        )
        panel_url = f"{self.bot.settings.public_base_url}/admin/events/new?token={session.token}"
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="פתח את פאנל האירועים", style=discord.ButtonStyle.link, url=panel_url))

        embed = discord.Embed(title="פאנל אירועים", color=discord.Color.gold())
        embed.description = "לחצו על הכפתור למטה כדי לפתוח את פאנל הניהול, ליצור אירוע ולפרסם אותו עם ריאקשן כוכב."
        embed.add_field(name="תוקף הקישור", value=f"{self.bot.settings.admin_panel_session_minutes} דקות", inline=False)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="editevent", description="פתיחת פאנל הניהול לעריכת אירוע קיים.")
    @app_commands.describe(event_id="מזהה האירוע כפי שמופיע בהודעת האירוע.")
    @admin_only()
    async def editevent(self, interaction: discord.Interaction, event_id: int) -> None:
        event = await self.bot.services.events.get_editable_event(event_id)
        session = await self.bot.services.panels.create_session(
            admin_user_id=interaction.user.id,
            panel_type="event-edit",
            target_id=event.id,
        )
        panel_url = f"{self.bot.settings.public_base_url}/admin/events/{event.id}/edit?token={session.token}"
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="ערוך את האירוע", style=discord.ButtonStyle.link, url=panel_url))

        embed = discord.Embed(title=f"עריכת אירוע #{event.id}", color=discord.Color.gold())
        embed.description = event.title
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="rollrandomuser", description="בחירת זוכה אקראי מאחד האירועים.")
    @admin_only()
    async def rollrandomuser(self, interaction: discord.Interaction) -> None:
        events = await self.bot.services.events.list_rollable_events()
        await self._send_roll_selector(
            interaction,
            events=events,
            title="בחר אירוע כדי לגלגל ממנו זוכה.",
            placeholder="בחר אירוע לרול",
            reroll=False,
        )

    @app_commands.command(name="rerolluser", description="רירול לאירוע שכבר נבחר לו זוכה.")
    @admin_only()
    async def rerolluser(self, interaction: discord.Interaction) -> None:
        events = await self.bot.services.events.list_rerollable_events()
        await self._send_roll_selector(
            interaction,
            events=events,
            title="בחר אירוע כדי לבצע לו רירול.",
            placeholder="בחר אירוע לרירול",
            reroll=True,
        )


async def setup(bot: SalesBot) -> None:
    await bot.add_cog(EngagementCog(bot))