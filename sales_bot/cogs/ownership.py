from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from sales_bot.bot import SalesBot
from sales_bot.checks import admin_only
from sales_bot.exceptions import ExternalServiceError, NotFoundError, PermissionDeniedError
from sales_bot.models import SystemRecord
from sales_bot.services.ownership import CLAIMABLE_ROLE_ID
from sales_bot.ui.common import ConfirmView, PaginatedSelectView, edit_interaction_response
from sales_bot.ui.ownership import ClaimRolePanelView, build_system_names


async def system_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    bot = interaction.client
    if not isinstance(bot, SalesBot):
        return []

    systems = await bot.services.systems.search_systems(current)
    return [app_commands.Choice(name=system.name, value=system.name) for system in systems]


def build_systems_embed(
    title: str,
    systems: list[SystemRecord],
    *,
    color: discord.Color,
    empty_text: str,
) -> discord.Embed:
    embed = discord.Embed(title=title, color=color)
    embed.description = build_system_names(systems) if systems else empty_text
    embed.set_footer(text=f"סה\"כ מערכות: {len(systems)}")
    return embed


class OwnershipCog(commands.Cog):
    def __init__(self, bot: SalesBot) -> None:
        self.bot = bot

    @app_commands.command(name="checksystems", description="הצגת המערכות שנמצאות כרגע בבעלות של משתמש.")
    @app_commands.describe(user="המשתמש שעבורו תוצג רשימת המערכות.")
    @admin_only()
    async def checksystems(self, interaction: discord.Interaction, user: discord.User) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except discord.HTTPException as exc:
                if exc.code != 40060:
                    raise

        await self.bot.services.ownership.sync_linked_gamepass_ownerships(self.bot, user.id)
        await self.bot.services.ownership.refresh_claim_role_membership(
            self.bot,
            user.id,
            guild=interaction.guild,
            sync_ownerships=False,
        )
        systems = await self.bot.services.ownership.list_user_systems(user.id)
        embed = build_systems_embed(
            f"המערכות של {user}",
            systems,
            color=discord.Color.blue(),
            empty_text="למשתמש הזה אין כרגע מערכות בבעלות.",
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="getsystem", description="קבלת מערכת אם היא כבר בבעלותך או אם החשבון המקושר שלך מחזיק בגיימפאס המתאים.")
    async def getsystem(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except discord.HTTPException as exc:
                if exc.code != 40060:
                    raise

        systems = await self.bot.services.ownership.list_getsystem_available_systems(self.bot, interaction.user.id)
        if not systems:
            await interaction.followup.send("כרגע אין מערכות זמינות בבוט.", ephemeral=True)
            return

        async def on_selected(
            select_interaction: discord.Interaction,
            system: object,
            parent_view: PaginatedSelectView,
        ) -> None:
            selected_system = system

            synced_systems = await self.bot.services.ownership.sync_linked_gamepass_ownerships(
                self.bot,
                interaction.user.id,
                system_ids={selected_system.id},
            )
            synced_now = any(synced_system.id == selected_system.id for synced_system in synced_systems)

            already_owned = await self.bot.services.ownership.user_owns_system(interaction.user.id, selected_system.id)
            is_transfer_locked = await self.bot.services.ownership.is_transfer_locked(interaction.user.id, selected_system.id)

            if already_owned:
                await self.bot.services.delivery.deliver_system(
                    self.bot,
                    interaction.user,
                    selected_system,
                    source="owned-system-redownload",
                    granted_by=None,
                    record_ownership=False,
                )
                await self.bot.services.ownership.refresh_claim_role_membership(
                    self.bot,
                    interaction.user.id,
                    guild=select_interaction.guild,
                    sync_ownerships=False,
                )
                success_message = (
                    f"המערכת **{selected_system.name}** נשלחה אליך ב-DM כי הגיימפאס אומת ונשמר בבעלות שלך."
                    if synced_now
                    else f"המערכת **{selected_system.name}** נשלחה אליך שוב ב-DM כי היא כבר רשומה בבעלותך."
                )
                await edit_interaction_response(
                    select_interaction,
                    content=success_message,
                    embed=None,
                    view=None,
                )
                return

            if is_transfer_locked:
                raise PermissionDeniedError("המערכת הזאת הועברה מחשבון זה ולכן אי אפשר לקבל אותה שוב דרך הפקודה הזאת.")

            if not selected_system.roblox_gamepass_id:
                raise PermissionDeniedError("למערכת הזאת עדיין לא הוגדר גיימפאס Roblox, לכן אי אפשר לקבל אותה דרך הפקודה הזאת.")

            if self.bot.http_session is None:
                raise ExternalServiceError("חיבור הרשת של הבוט לא זמין כרגע. נסה שוב בעוד רגע.")

            try:
                await self.bot.services.oauth.get_link(interaction.user.id)
            except NotFoundError as exc:
                raise PermissionDeniedError(
                    "כדי לקבל מערכת חדשה דרך הפקודה הזאת צריך קודם לקשר חשבון רובלוקס עם `/link`. "
                    "אם המערכת כבר בבעלותך, אפשר להוריד אותה מחדש גם בלי גיימפאס."
                ) from exc

            owns_gamepass = await self.bot.services.oauth.linked_user_owns_gamepass(
                self.bot.http_session,
                discord_user_id=interaction.user.id,
                gamepass_id=selected_system.roblox_gamepass_id,
            )
            if not owns_gamepass:
                raise PermissionDeniedError("לפי בדיקת Roblox, החשבון המקושר שלך לא מחזיק בגיימפאס של המערכת הזאת.")

            await self.bot.services.delivery.deliver_system(
                self.bot,
                interaction.user,
                selected_system,
                source=self.bot.services.ownership.ROBLOX_CLAIM_SOURCE,
                granted_by=None,
            )
            await edit_interaction_response(
                select_interaction,
                content=f"המערכת **{selected_system.name}** נשלחה אליך ב-DM כי הגיימפאס אומת בהצלחה.",
                embed=None,
                view=None,
            )

        view = PaginatedSelectView(
            actor_id=interaction.user.id,
            items=systems,
            placeholder="בחר מערכת לבדיקה וקבלה",
            option_builder=lambda system: discord.SelectOption(
                label=system.name[:100],
                description=system.description[:100],
                value=str(system.id),
            ),
            value_getter=lambda system: str(system.id),
            on_selected=on_selected,
        )
        await interaction.followup.send(
            "בחר את המערכת שתרצה לבדוק מולה את הגיימפאס של החשבון המקושר שלך.",
            view=view,
            ephemeral=True,
        )

    @app_commands.command(name="givesystem", description="תצוגה מקדימה ואישור שליחת מערכת למשתמש.")
    @app_commands.describe(user="המשתמש שיקבל את המערכת.", system="המערכת שתרצה לתת.")
    @app_commands.autocomplete(system=system_autocomplete)
    @admin_only()
    async def givesystem(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        system: str,
    ) -> None:
        selected_system = await self.bot.services.systems.get_system_by_name(system)
        embed = self.bot.services.systems.build_embed(selected_system)
        embed.title = f"לשלוח את {selected_system.name} אל {user}?"
        embed.add_field(name="נמען", value=user.mention, inline=False)

        async def on_confirm(confirm_interaction: discord.Interaction, view: ConfirmView) -> None:
            await self.bot.services.delivery.deliver_system(
                self.bot,
                user,
                selected_system,
                source="grant",
                granted_by=interaction.user.id,
            )
            await edit_interaction_response(
                confirm_interaction,
                content=f"המערכת **{selected_system.name}** נשלחה אל {user.mention} ונרשמה בבעלות שלו.",
                embed=embed,
                view=view,
            )

        view = ConfirmView(actor_id=interaction.user.id, on_confirm=on_confirm)
        await interaction.response.send_message(
            "בדוק את התצוגה המקדימה לפני שליחת המערכת.",
            embed=embed,
            view=view,
            ephemeral=True,
        )

    @app_commands.command(name="revokesystem", description="אישור והסרת מערכת מבעלות של משתמש.")
    @app_commands.describe(user="המשתמש שממנו תוסר הבעלות.", system="המערכת להסרה.")
    @app_commands.autocomplete(system=system_autocomplete)
    @admin_only()
    async def revokesystem(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        system: str,
    ) -> None:
        selected_system = await self.bot.services.systems.get_system_by_name(system)
        embed = discord.Embed(
            title="אישור הסרת מערכת",
            description=f"להסיר את **{selected_system.name}** מהבעלות של {user.mention}?",
            color=discord.Color.orange(),
        )

        async def on_confirm(confirm_interaction: discord.Interaction, view: ConfirmView) -> None:
            await self.bot.services.ownership.revoke_system(user.id, selected_system.id)
            deleted_messages = await self.bot.services.delivery.purge_deliveries(
                self.bot,
                user_id=user.id,
                system_id=selected_system.id,
            )
            await self.bot.services.ownership.refresh_claim_role_membership(
                self.bot,
                user.id,
                guild=confirm_interaction.guild,
                sync_ownerships=False,
            )
            await edit_interaction_response(
                confirm_interaction,
                content=(
                    f"המערכת **{selected_system.name}** הוסרה מהבעלות של {user.mention}. "
                    f"נמחקו {deleted_messages} הודעות מסירה ישנות ב-DM."
                ),
                embed=None,
                view=view,
            )

        view = ConfirmView(actor_id=interaction.user.id, on_confirm=on_confirm)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="tempsave", description="שמירה זמנית של המערכות שמגיעות למשתמש מאדמין או דרך Roblox.")
    @app_commands.describe(user="המשתמש שעבורו תישמר רשימת המערכות.")
    @admin_only()
    async def tempsave(self, interaction: discord.Interaction, user: discord.User) -> None:
        saved_systems = await self.bot.services.ownership.save_transferable_systems(user.id, interaction.user.id)
        systems = [saved_system.system for saved_system in saved_systems]

        if not systems:
            await interaction.response.send_message(
                "לא נמצאו אצל המשתמש מערכות שמקורן באדמין או ב-Roblox, ולכן לא נשמר דבר.",
                ephemeral=True,
            )
            return

        embed = build_systems_embed(
            f"שמירה זמנית עבור {user}",
            systems,
            color=discord.Color.gold(),
            empty_text="לא נשמרו מערכות.",
        )
        embed.add_field(name="משתמש", value=user.mention, inline=False)
        embed.add_field(name="נשמר על ידי", value=interaction.user.mention, inline=False)
        await interaction.response.send_message(
            "הרשימה נשמרה זמנית ותשמש להעברה הבאה של המשתמש.",
            embed=embed,
            ephemeral=True,
        )

    @app_commands.command(name="transfer", description="העברת כל המערכות השמורות של משתמש אחד למשתמש אחר בלי לשכפל בעלות.")
    @app_commands.describe(from_user="המשתמש שממנו מעבירים.", to_user="המשתמש שאליו מעבירים.")
    @admin_only()
    async def transfer(
        self,
        interaction: discord.Interaction,
        from_user: discord.User,
        to_user: discord.User,
    ) -> None:
        if await self.bot.services.blacklist.is_blacklisted(to_user.id):
            raise PermissionDeniedError("אי אפשר להעביר מערכות למשתמש שנמצא בבלקליסט.")

        preview_saved_systems = await self.bot.services.ownership.save_transferable_systems(from_user.id, interaction.user.id)
        preview_systems = [saved_system.system for saved_system in preview_saved_systems]
        if not preview_systems:
            raise NotFoundError("לא נמצאו אצל המשתמש מערכות מתאימות להעברה.")

        embed = build_systems_embed(
            "אישור העברת מערכות",
            preview_systems,
            color=discord.Color.gold(),
            empty_text="לא נמצאו מערכות להעברה.",
        )
        embed.add_field(name="העברה", value=f"{from_user.mention} -> {to_user.mention}", inline=False)
        embed.add_field(
            name="הערה",
            value="ההעברה תסיר את המערכות מהמשתמש הישן, תנעל אותן עבורו לקבלה מחדש, ותמנע שכפול אצל המשתמש החדש.",
            inline=False,
        )

        async def on_confirm(confirm_interaction: discord.Interaction, view: ConfirmView) -> None:
            transferred_systems = await self.bot.services.ownership.transfer_all_systems(
                from_user_id=from_user.id,
                to_user_id=to_user.id,
                transferred_by=interaction.user.id,
            )

            deleted_messages = 0
            for transferred_system in transferred_systems:
                deleted_messages += await self.bot.services.delivery.purge_deliveries(
                    self.bot,
                    user_id=from_user.id,
                    system_id=transferred_system.id,
                )

            await self.bot.services.ownership.refresh_claim_role_membership(
                self.bot,
                from_user.id,
                guild=confirm_interaction.guild,
                sync_ownerships=False,
            )
            await self.bot.services.ownership.refresh_claim_role_membership(
                self.bot,
                to_user.id,
                guild=confirm_interaction.guild,
                sync_ownerships=False,
            )

            sender_embed = discord.Embed(title="המערכות שלך הועברו", color=discord.Color.orange())
            sender_embed.description = build_system_names(transferred_systems)
            sender_embed.add_field(name="הועבר אל", value=to_user.mention, inline=False)

            receiver_embed = discord.Embed(title=f"קיבלת מערכות חדשות מאת: {from_user}", color=discord.Color.green())
            receiver_embed.description = build_system_names(transferred_systems)
            receiver_embed.add_field(name="הועבר מאת", value=from_user.mention, inline=False)

            dm_failures: list[str] = []
            try:
                await from_user.send("המערכות שלך הועברו.", embed=sender_embed)
            except discord.HTTPException:
                dm_failures.append(f"{from_user.mention} (המשתמש המעביר)")

            try:
                await to_user.send("קיבלת מערכות חדשות.", embed=receiver_embed)
            except discord.HTTPException:
                dm_failures.append(f"{to_user.mention} (המשתמש המקבל)")

            summary_embed = build_systems_embed(
                "העברת המערכות הושלמה",
                transferred_systems,
                color=discord.Color.green(),
                empty_text="לא הועברו מערכות.",
            )
            summary_embed.add_field(name="העברה", value=f"{from_user.mention} -> {to_user.mention}", inline=False)
            summary_embed.add_field(name="הודעות DM שנמחקו", value=str(deleted_messages), inline=False)

            content = "ההעברה הושלמה בהצלחה. המשתמש הישן לא יוכל לקבל שוב את המערכות שהועברו דרך `/getsystem`."
            if dm_failures:
                content += f" לא הצלחתי לשלוח הודעת DM אל: {', '.join(dm_failures)}."

            await edit_interaction_response(
                confirm_interaction,
                content=content,
                embed=summary_embed,
                view=view,
            )

        view = ConfirmView(actor_id=interaction.user.id, on_confirm=on_confirm)
        await interaction.response.send_message(
            "בדוק את רשימת המערכות לפני אישור ההעברה.",
            embed=embed,
            view=view,
            ephemeral=True,
        )

    @app_commands.command(name="claimrolepanel", description="שליחת פאנל שמאפשר למשתמשים לקבל את רול המערכות לבד.")
    @admin_only()
    async def claimrolepanel(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.channel is None:
            raise PermissionDeniedError("את הפאנל הזה אפשר לשלוח רק בערוץ בתוך השרת.")

        embed = discord.Embed(title="קבלת רול מערכות", color=discord.Color.gold())
        embed.description = (
            f"אם יש לך מערכות שקיבלת מאדמין או גיימפאסים מתאימים ברובלוקס, "
            f"לחץ על הכפתור למטה כדי לקבל את הרול <@&{CLAIMABLE_ROLE_ID}>.\n"
            "מערכות שהגיעו מהעברה לא מזכות בקבלת הרול."
        )

        await interaction.channel.send(embed=embed, view=ClaimRolePanelView(self.bot))
        await interaction.response.send_message("פאנל קבלת הרול נשלח לערוץ הזה.", ephemeral=True)


async def setup(bot: SalesBot) -> None:
    await bot.add_cog(OwnershipCog(bot))
