from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from urllib.parse import quote

import discord
from discord import app_commands
from discord.ext import commands

from sales_bot.bot import SalesBot
from sales_bot.checks import admin_only
from sales_bot.models import SystemDiscountRecord, SystemRecord


def _round_robux(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _roblox_net_amount(amount: int) -> int:
    return int((Decimal(amount) * Decimal("0.7")).quantize(Decimal("1"), rounding=ROUND_FLOOR))


async def admin_system_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    bot = interaction.client
    if not isinstance(bot, SalesBot):
        return []

    systems = await bot.services.systems.search_systems(current)
    return [app_commands.Choice(name=system.name[:100], value=str(system.id)) for system in systems[:25]]


async def discounted_system_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    bot = interaction.client
    if not isinstance(bot, SalesBot):
        return []

    selected_user = getattr(interaction.namespace, "user", None)
    user_id = getattr(selected_user, "id", None)
    if user_id is None:
        return []

    discounts = await bot.services.discounts.search_user_discounted_systems(user_id=user_id, current=current)
    return [
        app_commands.Choice(
            name=f"{discount.system.name} ({discount.discount_percent}%)"[:100],
            value=str(discount.system.id),
        )
        for discount in discounts[:25]
    ]


class AdminCog(commands.Cog):
    def __init__(self, bot: SalesBot) -> None:
        self.bot = bot

    async def _resolve_system_value(self, system_value: str) -> SystemRecord:
        value = system_value.strip()
        if not value:
            raise app_commands.AppCommandError("חובה לבחור מערכת.")
        if value.isdigit():
            return await self.bot.services.systems.get_system(int(value))
        return await self.bot.services.systems.get_system_by_name(value)

    async def _resolve_discount_value(self, user_id: int, system_value: str) -> SystemDiscountRecord:
        system = await self._resolve_system_value(system_value)
        return await self.bot.services.discounts.get_discount(user_id, system.id)

    @app_commands.command(name="adminsite", description="פתיחת אתר הניהול של הבוט.")
    @admin_only()
    async def adminsite(self, interaction: discord.Interaction) -> None:
        view = discord.ui.View()
        view.add_item(
            discord.ui.Button(
                label="פתח את אתר הניהול",
                style=discord.ButtonStyle.link,
                url=f"{self.bot.settings.public_base_url}/admin",
            )
        )
        await interaction.response.send_message(
            "האתר פתוח רק לאדמינים של הבוט. אם עדיין לא התחברת, האתר יבקש ממך להתחבר עם Discord.",
            view=view,
            ephemeral=True,
        )

    @app_commands.command(name="addadmin", description="Add a Discord user to the bot admin list.")
    @app_commands.describe(user="User to grant bot admin access to.")
    @admin_only()
    async def addadmin(self, interaction: discord.Interaction, user: discord.User) -> None:
        await self.bot.services.admins.add_admin(user.id, interaction.user.id)
        await interaction.response.send_message(
            f"Added {user.mention} to the admin list.",
            ephemeral=True,
        )

    @app_commands.command(name="removeadmin", description="Remove a Discord user from the bot admin list.")
    @app_commands.describe(user="User to remove from bot admin access.")
    @admin_only()
    async def removeadmin(self, interaction: discord.Interaction, user: discord.User) -> None:
        await self.bot.services.admins.remove_admin(user.id)
        await interaction.response.send_message(
            f"Removed {user.mention} from the admin list.",
            ephemeral=True,
        )

    @app_commands.command(name="sendspecialsystem", description="פתיחת עמוד יצירת מערכת מיוחדת באתר.")
    @app_commands.describe(system="השם שיופיע מראש בכותרת של המערכת המיוחדת.")
    @admin_only()
    async def sendspecialsystem(self, interaction: discord.Interaction, system: str) -> None:
        compose_url = f"{self.bot.settings.public_base_url}/admin/special-systems?title={quote(system.strip())}"
        view = discord.ui.View()
        view.add_item(
            discord.ui.Button(
                label="פתח את עמוד המערכת המיוחדת",
                style=discord.ButtonStyle.link,
                url=compose_url,
            )
        )
        await interaction.response.send_message(
            "העמוד ייפתח עם שם המערכת שמולא מראש, ומשם אפשר להגדיר תיאור, שיטות תשלום, מחירים, תמונות וערוץ שליחה.",
            view=view,
            ephemeral=True,
        )

    @app_commands.command(name="discount", description="שמירת הנחה למשתמש על מערכת קיימת.")
    @app_commands.describe(
        user="המשתמש שיקבל את ההנחה.",
        system="המערכת שעליה תישמר ההנחה.",
        discount_amount="אחוז ההנחה.",
    )
    @app_commands.autocomplete(system=admin_system_autocomplete)
    @admin_only()
    async def discount(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        system: str,
        discount_amount: app_commands.Range[int, 1, 99],
    ) -> None:
        system_record = await self._resolve_system_value(system)
        saved_discount = await self.bot.services.discounts.add_discount(
            user_id=user.id,
            system=system_record,
            discount_percent=int(discount_amount),
            actor_id=interaction.user.id,
        )
        await interaction.response.send_message(
            f"נשמרה הנחה של {saved_discount.discount_percent}% עבור {user.mention} על המערכת {system_record.name}.",
            ephemeral=True,
        )

    @app_commands.command(name="removediscount", description="הסרת הנחה שמורה ממשתמש.")
    @app_commands.describe(
        user="המשתמש שממנו תוסר ההנחה.",
        system="המערכת שכבר יש עליה הנחה אצל המשתמש.",
    )
    @app_commands.autocomplete(system=discounted_system_autocomplete)
    @admin_only()
    async def removediscount(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        system: str,
    ) -> None:
        saved_discount = await self._resolve_discount_value(user.id, system)
        await self.bot.services.discounts.remove_discount(user_id=user.id, system_id=saved_discount.system.id)
        await interaction.response.send_message(
            f"ההנחה על {saved_discount.system.name} הוסרה עבור {user.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="editdiscount", description="עדכון אחוז ההנחה של משתמש על מערכת.")
    @app_commands.describe(
        user="המשתמש שעבורו תעודכן ההנחה.",
        system="המערכת שכבר יש עליה הנחה.",
        new_discount_amount="אחוז ההנחה החדש.",
    )
    @app_commands.autocomplete(system=discounted_system_autocomplete)
    @admin_only()
    async def editdiscount(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        system: str,
        new_discount_amount: app_commands.Range[int, 1, 99],
    ) -> None:
        saved_discount = await self._resolve_discount_value(user.id, system)
        updated_discount = await self.bot.services.discounts.set_discount(
            user_id=user.id,
            system=saved_discount.system,
            discount_percent=int(new_discount_amount),
            actor_id=interaction.user.id,
        )
        await interaction.response.send_message(
            f"ההנחה על {updated_discount.system.name} עודכנה ל-{updated_discount.discount_percent}% עבור {user.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="discountcalculator", description="חישוב מחיר אחרי הנחה כולל חישוב המס של Roblox.")
    @app_commands.describe(price="המחיר הנוכחי ב-Robux.", discount_amount="אחוז ההנחה.")
    async def discountcalculator(
        self,
        interaction: discord.Interaction,
        price: app_commands.Range[int, 1, None],
        discount_amount: app_commands.Range[int, 1, 99],
    ) -> None:
        original_price = int(price)
        discount_percent = int(discount_amount)
        discount_value = _round_robux((Decimal(original_price) * Decimal(discount_percent)) / Decimal(100))
        discounted_price = max(1, original_price - discount_value)
        original_net = _roblox_net_amount(original_price)
        discounted_net = _roblox_net_amount(discounted_price)
        discounted_tax = discounted_price - discounted_net

        embed = discord.Embed(title="מחשבון הנחה", color=discord.Color.gold())
        embed.add_field(name="מחיר מקורי", value=f"{original_price} Robux", inline=True)
        embed.add_field(name="אחוז הנחה", value=f"{discount_percent}%", inline=True)
        embed.add_field(name="שווי ההנחה", value=f"{discount_value} Robux", inline=True)
        embed.add_field(name="מחיר אחרי הנחה", value=f"{discounted_price} Robux", inline=True)
        embed.add_field(name="תקבל אחרי מס", value=f"{discounted_net} Robux", inline=True)
        embed.add_field(name="מס Roblox", value=f"{discounted_tax} Robux", inline=True)
        embed.set_footer(text=f"לפני ההנחה היית מקבל {original_net} Robux אחרי המס.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="calculatetax", description="חישוב כמה Roblox לוקחת וכמה נשאר אחרי מס.")
    @app_commands.describe(amount="המחיר ב-Robux לפני המס.")
    async def calculatetax(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, None],
    ) -> None:
        gross_amount = int(amount)
        net_amount = _roblox_net_amount(gross_amount)
        tax_amount = gross_amount - net_amount

        embed = discord.Embed(title="חישוב מס Roblox", color=discord.Color.blurple())
        embed.add_field(name="מחיר לפני מס", value=f"{gross_amount} Robux", inline=True)
        embed.add_field(name="Roblox לוקחת", value=f"{tax_amount} Robux", inline=True)
        embed.add_field(name="מה שנשאר לך", value=f"{net_amount} Robux", inline=True)
        await interaction.response.send_message(embed=embed)


async def setup(bot: SalesBot) -> None:
    await bot.add_cog(AdminCog(bot))
