from __future__ import annotations

import re
from pathlib import Path

import aiosqlite
import discord

from sales_bot.db import Database
from sales_bot.exceptions import AlreadyExistsError, NotFoundError
from sales_bot.models import SystemRecord
from sales_bot.storage import remove_path, save_attachment, slugify


class SystemService:
    def __init__(self, database: Database, storage_root: Path) -> None:
        self.database = database
        self.storage_root = storage_root
        self.storage_root.mkdir(parents=True, exist_ok=True)

    async def create_system(
        self,
        *,
        name: str,
        description: str,
        file_attachment: discord.Attachment,
        image_attachment: discord.Attachment | None,
        created_by: int,
        paypal_link: str | None,
        roblox_gamepass_reference: str | None,
    ) -> SystemRecord:
        folder = self.storage_root / f"{slugify(name)}-{file_attachment.id}"
        file_path = await save_attachment(file_attachment, folder)
        image_path = await save_attachment(image_attachment, folder) if image_attachment else None
        roblox_gamepass_id = self.normalize_gamepass_reference(roblox_gamepass_reference)

        try:
            system_id = await self.database.insert(
                """
                INSERT INTO systems (name, description, image_path, file_path, paypal_link, roblox_gamepass_id, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name.strip(),
                    description.strip(),
                    str(image_path) if image_path else None,
                    str(file_path),
                    paypal_link.strip() if paypal_link else None,
                    roblox_gamepass_id,
                    created_by,
                ),
            )
        except aiosqlite.IntegrityError as exc:
            remove_path(file_path)
            remove_path(image_path)
            raise AlreadyExistsError("A system with that name already exists.") from exc

        return await self.get_system(system_id)

    async def get_system(self, system_id: int) -> SystemRecord:
        row = await self.database.fetchone("SELECT * FROM systems WHERE id = ?", (system_id,))
        if row is None:
            raise NotFoundError("System not found.")
        return self._map_system(row)

    async def get_system_by_name(self, name: str) -> SystemRecord:
        row = await self.database.fetchone(
            "SELECT * FROM systems WHERE LOWER(name) = LOWER(?)",
            (name.strip(),),
        )
        if row is None:
            raise NotFoundError("System not found.")
        return self._map_system(row)

    async def list_systems(self) -> list[SystemRecord]:
        rows = await self.database.fetchall("SELECT * FROM systems ORDER BY LOWER(name) ASC")
        return [self._map_system(row) for row in rows]

    async def list_paypal_enabled_systems(self) -> list[SystemRecord]:
        rows = await self.database.fetchall(
            "SELECT * FROM systems WHERE paypal_link IS NOT NULL AND paypal_link != '' ORDER BY LOWER(name) ASC"
        )
        return [self._map_system(row) for row in rows]

    async def list_robux_enabled_systems(self) -> list[SystemRecord]:
        rows = await self.database.fetchall(
            "SELECT * FROM systems WHERE roblox_gamepass_id IS NOT NULL AND roblox_gamepass_id != '' ORDER BY LOWER(name) ASC"
        )
        return [self._map_system(row) for row in rows]

    async def search_systems(
        self,
        current: str,
        *,
        paypal_only: bool = False,
        robux_only: bool = False,
    ) -> list[SystemRecord]:
        like_value = f"%{current.strip()}%"
        query = "SELECT * FROM systems WHERE LOWER(name) LIKE LOWER(?)"
        if paypal_only:
            query += " AND paypal_link IS NOT NULL AND paypal_link != ''"
        if robux_only:
            query += " AND roblox_gamepass_id IS NOT NULL AND roblox_gamepass_id != ''"
        query += " ORDER BY LOWER(name) ASC LIMIT 25"
        rows = await self.database.fetchall(query, (like_value,))
        return [self._map_system(row) for row in rows]

    async def delete_system(self, system_id: int) -> SystemRecord:
        system = await self.get_system(system_id)
        await self.database.execute("DELETE FROM systems WHERE id = ?", (system_id,))
        remove_path(system.file_path)
        remove_path(system.image_path)
        return system

    def build_embed(self, system: SystemRecord) -> discord.Embed:
        embed = discord.Embed(
            title=system.name,
            description=system.description,
            color=discord.Color.blue(),
        )
        embed.add_field(name="איידי של המערכת", value=str(system.id), inline=True)
        embed.add_field(name="פייפאל", value=system.paypal_link or "לא מוגדר", inline=False)
        embed.add_field(name="גיימפאס רובוקס", value=self.gamepass_url_for_id(system.roblox_gamepass_id) or "לא מוגדר", inline=False)
        embed.set_footer(text="Magic System's")
        return embed

    @staticmethod
    def normalize_gamepass_reference(reference: str | None) -> str | None:
        if not reference:
            return None

        stripped = reference.strip()
        if not stripped:
            return None

        direct_match = re.fullmatch(r"\d+", stripped)
        if direct_match:
            return stripped

        url_match = re.search(r"(?:game-pass|gamepass)/(\d+)", stripped, flags=re.IGNORECASE)
        if url_match:
            return url_match.group(1)

        id_match = re.search(r"\b(\d{5,})\b", stripped)
        if id_match:
            return id_match.group(1)

        raise NotFoundError("Invalid Roblox gamepass link or ID.")

    @staticmethod
    def gamepass_url_for_id(gamepass_id: str | None) -> str | None:
        if not gamepass_id:
            return None
        return f"https://www.roblox.com/game-pass/{gamepass_id}"

    @staticmethod
    def _map_system(row: aiosqlite.Row) -> SystemRecord:
        return SystemRecord(
            id=int(row["id"]),
            name=str(row["name"]),
            description=str(row["description"]),
            file_path=str(row["file_path"]),
            image_path=str(row["image_path"]) if row["image_path"] else None,
            paypal_link=str(row["paypal_link"]) if row["paypal_link"] else None,
            roblox_gamepass_id=str(row["roblox_gamepass_id"]) if row["roblox_gamepass_id"] else None,
            created_by=int(row["created_by"]) if row["created_by"] is not None else None,
            created_at=str(row["created_at"]),
        )
