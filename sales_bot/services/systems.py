from __future__ import annotations

import re
from pathlib import Path

import aiosqlite
import asyncpg
import discord

from sales_bot.db import Database
from sales_bot.exceptions import AlreadyExistsError, NotFoundError
from sales_bot.models import SystemRecord, system_select_list
from sales_bot.storage import remove_path, save_bytes, slugify


class SystemService:
    SELECT_COLUMNS = system_select_list()

    def __init__(self, database: Database, storage_root: Path) -> None:
        self.database = database
        self.storage_root = storage_root
        try:
            self.storage_root.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

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
        file_data = await file_attachment.read()
        image_data = await image_attachment.read() if image_attachment else None

        file_path = folder / Path(file_attachment.filename).name
        try:
            file_path = save_bytes(folder, file_attachment.filename, file_data)
        except OSError:
            pass

        image_path = folder / Path(image_attachment.filename).name if image_attachment else None
        if image_attachment and image_data is not None:
            try:
                image_path = save_bytes(folder, image_attachment.filename, image_data)
            except OSError:
                pass

        roblox_gamepass_id = self.normalize_gamepass_reference(roblox_gamepass_reference)

        try:
            system_id = await self.database.insert(
                """
                INSERT INTO systems (
                    name,
                    description,
                    image_path,
                    file_path,
                    file_name,
                    file_data,
                    image_name,
                    image_data,
                    paypal_link,
                    roblox_gamepass_id,
                    created_by
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name.strip(),
                    description.strip(),
                    str(image_path) if image_path else None,
                    str(file_path),
                    file_attachment.filename,
                    file_data,
                    image_attachment.filename if image_attachment else None,
                    image_data,
                    paypal_link.strip() if paypal_link else None,
                    roblox_gamepass_id,
                    created_by,
                ),
            )
        except (aiosqlite.IntegrityError, asyncpg.exceptions.UniqueViolationError) as exc:
            remove_path(file_path)
            remove_path(image_path)
            raise AlreadyExistsError("A system with that name already exists.") from exc

        return await self.get_system(system_id)

    async def get_system(self, system_id: int) -> SystemRecord:
        row = await self.database.fetchone(f"SELECT {self.SELECT_COLUMNS} FROM systems WHERE id = ?", (system_id,))
        if row is None:
            raise NotFoundError("System not found.")
        return self._map_system(row)

    async def get_system_by_name(self, name: str) -> SystemRecord:
        row = await self.database.fetchone(
            f"SELECT {self.SELECT_COLUMNS} FROM systems WHERE LOWER(name) = LOWER(?)",
            (name.strip(),),
        )
        if row is None:
            raise NotFoundError("System not found.")
        return self._map_system(row)

    async def list_systems(self) -> list[SystemRecord]:
        rows = await self.database.fetchall(f"SELECT {self.SELECT_COLUMNS} FROM systems ORDER BY LOWER(name) ASC")
        return [self._map_system(row) for row in rows]

    async def list_paypal_enabled_systems(self) -> list[SystemRecord]:
        rows = await self.database.fetchall(
            f"SELECT {self.SELECT_COLUMNS} FROM systems WHERE paypal_link IS NOT NULL AND paypal_link != '' ORDER BY LOWER(name) ASC"
        )
        return [self._map_system(row) for row in rows]

    async def list_robux_enabled_systems(self) -> list[SystemRecord]:
        rows = await self.database.fetchall(
            f"SELECT {self.SELECT_COLUMNS} FROM systems WHERE roblox_gamepass_id IS NOT NULL AND roblox_gamepass_id != '' ORDER BY LOWER(name) ASC"
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
        query = f"SELECT {self.SELECT_COLUMNS} FROM systems WHERE LOWER(name) LIKE LOWER(?)"
        if paypal_only:
            query += " AND paypal_link IS NOT NULL AND paypal_link != ''"
        if robux_only:
            query += " AND roblox_gamepass_id IS NOT NULL AND roblox_gamepass_id != ''"
        query += " ORDER BY LOWER(name) ASC LIMIT 25"
        rows = await self.database.fetchall(query, (like_value,))
        return [self._map_system(row) for row in rows]

    async def get_stored_file(self, system_id: int) -> tuple[str, bytes]:
        row = await self.database.fetchone(
            "SELECT id, file_path, file_name, file_data FROM systems WHERE id = ?",
            (system_id,),
        )
        if row is None:
            raise NotFoundError("System not found.")

        file_path = Path(str(row["file_path"]))
        file_name = str(row["file_name"]) if row["file_name"] else file_path.name
        file_data = row["file_data"]
        if file_data is not None:
            return file_name, bytes(file_data)

        if file_path.is_file():
            data = file_path.read_bytes()
            await self.database.execute(
                "UPDATE systems SET file_name = COALESCE(file_name, ?), file_data = ? WHERE id = ?",
                (file_name, data, system_id),
            )
            return file_name, data

        raise NotFoundError(
            "קובץ המערכת לא נמצא בנתונים השמורים. יש להעלות מחדש את המערכת כדי למנוע אובדן נתונים."
        )

    async def backfill_binary_assets(self) -> int:
        rows = await self.database.fetchall(
            "SELECT id, file_path, file_name, file_data, image_path, image_name, image_data FROM systems"
        )
        backfilled = 0
        for row in rows:
            file_name = str(row["file_name"]) if row["file_name"] else None
            file_data = bytes(row["file_data"]) if row["file_data"] is not None else None
            image_name = str(row["image_name"]) if row["image_name"] else None
            image_data = bytes(row["image_data"]) if row["image_data"] is not None else None
            changed = False

            file_path = Path(str(row["file_path"])) if row["file_path"] else None
            if file_data is None and file_path is not None and file_path.is_file():
                file_data = file_path.read_bytes()
                file_name = file_name or file_path.name
                changed = True

            image_path = Path(str(row["image_path"])) if row["image_path"] else None
            if image_data is None and image_path is not None and image_path.is_file():
                image_data = image_path.read_bytes()
                image_name = image_name or image_path.name
                changed = True

            if not changed:
                continue

            await self.database.execute(
                """
                UPDATE systems
                SET file_name = COALESCE(file_name, ?),
                    file_data = COALESCE(file_data, ?),
                    image_name = COALESCE(image_name, ?),
                    image_data = COALESCE(image_data, ?)
                WHERE id = ?
                """,
                (file_name, file_data, image_name, image_data, int(row["id"])),
            )
            backfilled += 1

        return backfilled

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
        embed.add_field(name="גיימפאס רובקס", value=self.gamepass_url_for_id(system.roblox_gamepass_id) or "לא מוגדר", inline=False)
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
        file_path = str(row["file_path"])
        image_path = str(row["image_path"]) if row["image_path"] else None
        return SystemRecord(
            id=int(row["id"]),
            name=str(row["name"]),
            description=str(row["description"]),
            file_path=file_path,
            image_path=image_path,
            paypal_link=str(row["paypal_link"]) if row["paypal_link"] else None,
            roblox_gamepass_id=str(row["roblox_gamepass_id"]) if row["roblox_gamepass_id"] else None,
            created_by=int(row["created_by"]) if row["created_by"] is not None else None,
            created_at=str(row["created_at"]),
            file_name=str(row["file_name"]) if row["file_name"] else file_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1],
            image_name=(
                str(row["image_name"])
                if row["image_name"]
                else (image_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] if image_path else None)
            ),
        )
