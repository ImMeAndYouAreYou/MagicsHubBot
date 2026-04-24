from __future__ import annotations

from dataclasses import replace
from io import BytesIO
import re
from pathlib import Path
from uuid import uuid4

import aiosqlite
import discord

from sales_bot.db import Database
from sales_bot.exceptions import AlreadyExistsError, NotFoundError
from sales_bot.models import SystemAssetRecord, SystemRecord
from sales_bot.storage import remove_path, save_named_bytes, slugify


class SystemService:
    FILE_ASSET_TYPE = "file"
    IMAGE_ASSET_TYPE = "image"

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
        file_bytes = await file_attachment.read()
        image_upload: tuple[str, bytes] | None = None
        if image_attachment is not None:
            image_upload = (image_attachment.filename, await image_attachment.read())
        return await self.create_system_from_uploads(
            name=name,
            description=description,
            file_upload=(file_attachment.filename, file_bytes),
            image_upload=image_upload,
            created_by=created_by,
            paypal_link=paypal_link,
            roblox_gamepass_reference=roblox_gamepass_reference,
        )

    async def create_system_from_uploads(
        self,
        *,
        name: str,
        description: str,
        file_upload: tuple[str, bytes],
        image_upload: tuple[str, bytes] | None,
        created_by: int,
        paypal_link: str | None,
        roblox_gamepass_reference: str | None,
    ) -> SystemRecord:
        folder = self.storage_root / f"{slugify(name)}-{uuid4().hex[:12]}"
        file_name, file_bytes = file_upload
        file_path = save_named_bytes(file_name, file_bytes, folder)
        safe_file_name = Path(file_name).name or file_path.name
        image_bytes: bytes | None = None
        image_path: Path | None = None
        safe_image_name: str | None = None
        if image_upload is not None:
            image_name, image_bytes = image_upload
            image_path = save_named_bytes(image_name, image_bytes, folder)
            safe_image_name = Path(image_name).name or image_path.name

        roblox_gamepass_id = self.normalize_gamepass_reference(roblox_gamepass_reference)
        await self._ensure_gamepass_not_in_use(roblox_gamepass_id)
        system_id: int | None = None

        try:
            system_id = await self.database.insert(
                """
                INSERT INTO systems (name, description, image_path, file_path, paypal_link, roblox_gamepass_id, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name.strip(),
                    description.strip(),
                    self._serialize_storage_path(image_path),
                    self._serialize_storage_path(file_path),
                    paypal_link.strip() if paypal_link else None,
                    roblox_gamepass_id,
                    created_by,
                ),
            )
        except aiosqlite.IntegrityError as exc:
            remove_path(file_path)
            remove_path(image_path)
            raise AlreadyExistsError("A system with that name already exists.") from exc

        try:
            assert system_id is not None
            await self._upsert_system_asset(
                system_id,
                asset_type=self.FILE_ASSET_TYPE,
                asset_name=safe_file_name,
                asset_bytes=file_bytes,
            )
            if image_bytes is not None and safe_image_name is not None:
                await self._upsert_system_asset(
                    system_id,
                    asset_type=self.IMAGE_ASSET_TYPE,
                    asset_name=safe_image_name,
                    asset_bytes=image_bytes,
                )
        except Exception:
            if system_id is not None:
                await self.database.execute("DELETE FROM systems WHERE id = ?", (system_id,))
            remove_path(file_path)
            remove_path(image_path)
            raise

        return await self.get_system(system_id)

    async def get_system(self, system_id: int) -> SystemRecord:
        row = await self.database.fetchone("SELECT * FROM systems WHERE id = ?", (system_id,))
        if row is None:
            raise NotFoundError("System not found.")
        return await self._repair_system_paths(self._map_system(row))

    async def get_system_by_name(self, name: str) -> SystemRecord:
        row = await self.database.fetchone(
            "SELECT * FROM systems WHERE LOWER(name) = LOWER(?)",
            (name.strip(),),
        )
        if row is None:
            raise NotFoundError("System not found.")
        return await self._repair_system_paths(self._map_system(row))

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
        self._remove_stored_path(system.file_path)
        self._remove_stored_path(system.image_path)
        return system

    async def update_system(
        self,
        system_id: int,
        *,
        name: str,
        description: str,
        paypal_link: str | None,
        roblox_gamepass_reference: str | None,
        file_upload: tuple[str, bytes] | None = None,
        image_upload: tuple[str, bytes] | None = None,
        clear_image: bool = False,
    ) -> SystemRecord:
        current = await self.get_system(system_id)
        await self._backfill_assets_from_disk(current)

        folder = self._storage_folder_for_system(current, fallback_name=name)
        next_file_path = self._serialize_storage_path(current.file_path) or current.file_path
        next_image_path = self._serialize_storage_path(current.image_path) if current.image_path else None
        new_file_path: Path | None = None
        new_image_path: Path | None = None

        if file_upload is not None:
            filename, data = file_upload
            new_file_path = save_named_bytes(filename, data, folder)
            next_file_path = self._serialize_storage_path(new_file_path) or str(new_file_path)

        if clear_image:
            next_image_path = None

        if image_upload is not None:
            filename, data = image_upload
            new_image_path = save_named_bytes(filename, data, folder)
            next_image_path = self._serialize_storage_path(new_image_path) or str(new_image_path)

        roblox_gamepass_id = self.normalize_gamepass_reference(roblox_gamepass_reference)
        await self._ensure_gamepass_not_in_use(roblox_gamepass_id, exclude_system_id=system_id)
        cleaned_paypal_link = paypal_link.strip() if paypal_link else None

        try:
            await self.database.execute(
                """
                UPDATE systems
                SET name = ?,
                    description = ?,
                    file_path = ?,
                    image_path = ?,
                    paypal_link = ?,
                    roblox_gamepass_id = ?
                WHERE id = ?
                """,
                (
                    name.strip(),
                    description.strip(),
                    next_file_path,
                    next_image_path,
                    cleaned_paypal_link,
                    roblox_gamepass_id,
                    system_id,
                ),
            )
        except aiosqlite.IntegrityError as exc:
            remove_path(new_file_path)
            remove_path(new_image_path)
            raise AlreadyExistsError("A system with that name already exists.") from exc

        if file_upload is not None:
            file_name, file_bytes = file_upload
            await self._upsert_system_asset(
                system_id,
                asset_type=self.FILE_ASSET_TYPE,
                asset_name=Path(file_name).name or Path(next_file_path).name,
                asset_bytes=file_bytes,
            )
        if clear_image:
            await self._delete_system_asset(system_id, asset_type=self.IMAGE_ASSET_TYPE)
        if image_upload is not None:
            image_name, image_bytes = image_upload
            await self._upsert_system_asset(
                system_id,
                asset_type=self.IMAGE_ASSET_TYPE,
                asset_name=Path(image_name).name or Path(next_image_path or "image.bin").name,
                asset_bytes=image_bytes,
            )

        if new_file_path is not None and current.file_path != str(new_file_path):
            self._remove_stored_path(current.file_path)
        if clear_image and current.image_path:
            self._remove_stored_path(current.image_path)
        if new_image_path is not None and current.image_path != str(new_image_path):
            self._remove_stored_path(current.image_path)

        return await self.get_system(system_id)

    async def build_delivery_file(self, system: SystemRecord) -> discord.File:
        asset = await self.get_system_asset(system.id, asset_type=self.FILE_ASSET_TYPE)
        stored_path = self.resolve_storage_path(system.file_path)

        if stored_path is not None and stored_path.is_file():
            if asset is None:
                await self._upsert_system_asset(
                    system.id,
                    asset_type=self.FILE_ASSET_TYPE,
                    asset_name=stored_path.name,
                    asset_bytes=stored_path.read_bytes(),
                )
                asset_name = stored_path.name
            else:
                asset_name = asset.asset_name
            return discord.File(stored_path, filename=asset_name)

        if asset is not None:
            return discord.File(BytesIO(asset.asset_bytes), filename=asset.asset_name)

        raise NotFoundError(
            "קובץ המערכת לא נמצא על השרת. אם זה קרה אחרי דיפלוי, צריך להעלות מחדש את המערכת פעם אחת כדי לשחזר את הקובץ."
        )

    async def get_system_by_gamepass_id(self, gamepass_id: str) -> SystemRecord:
        normalized_gamepass_id = self.normalize_gamepass_reference(gamepass_id)
        if not normalized_gamepass_id:
            raise NotFoundError("Game pass not found.")

        row = await self.database.fetchone(
            "SELECT * FROM systems WHERE roblox_gamepass_id = ? ORDER BY id ASC",
            (normalized_gamepass_id,),
        )
        if row is None:
            raise NotFoundError("No system is linked to that Roblox game pass yet.")
        return await self._repair_system_paths(self._map_system(row))

    async def set_system_gamepass(self, system_id: int, gamepass_reference: str | None) -> SystemRecord:
        normalized_gamepass_id = self.normalize_gamepass_reference(gamepass_reference)
        await self._ensure_gamepass_not_in_use(normalized_gamepass_id, exclude_system_id=system_id)
        await self.database.execute(
            "UPDATE systems SET roblox_gamepass_id = ? WHERE id = ?",
            (normalized_gamepass_id, system_id),
        )
        return await self.get_system(system_id)

    async def get_gamepass_display_name(self, gamepass_reference: str | None) -> str | None:
        normalized_gamepass_id = self.normalize_gamepass_reference(gamepass_reference)
        if not normalized_gamepass_id:
            return None

        row = await self.database.fetchone(
            "SELECT display_name FROM roblox_gamepass_display_names WHERE gamepass_id = ?",
            (normalized_gamepass_id,),
        )
        if row is None:
            return None
        return str(row["display_name"])

    async def list_gamepass_display_names(self, gamepass_references: list[str]) -> dict[str, str]:
        normalized_gamepass_ids: list[str] = []
        for reference in gamepass_references:
            normalized_gamepass_id = self.normalize_gamepass_reference(reference)
            if normalized_gamepass_id and normalized_gamepass_id not in normalized_gamepass_ids:
                normalized_gamepass_ids.append(normalized_gamepass_id)

        if not normalized_gamepass_ids:
            return {}

        placeholders = ", ".join("?" for _ in normalized_gamepass_ids)
        rows = await self.database.fetchall(
            f"SELECT gamepass_id, display_name FROM roblox_gamepass_display_names WHERE gamepass_id IN ({placeholders})",
            tuple(normalized_gamepass_ids),
        )
        return {str(row["gamepass_id"]): str(row["display_name"]) for row in rows}

    async def set_gamepass_display_name(self, gamepass_reference: str, display_name: str | None) -> str | None:
        normalized_gamepass_id = self.normalize_gamepass_reference(gamepass_reference)
        if not normalized_gamepass_id:
            raise NotFoundError("Game pass not found.")

        cleaned_display_name = display_name.strip() if display_name else ""
        if not cleaned_display_name:
            await self.database.execute(
                "DELETE FROM roblox_gamepass_display_names WHERE gamepass_id = ?",
                (normalized_gamepass_id,),
            )
            return None

        await self.database.execute(
            """
            INSERT INTO roblox_gamepass_display_names (gamepass_id, display_name)
            VALUES (?, ?)
            ON CONFLICT(gamepass_id)
            DO UPDATE SET display_name = excluded.display_name, updated_at = CURRENT_TIMESTAMP
            """,
            (normalized_gamepass_id, cleaned_display_name),
        )
        return cleaned_display_name

    async def get_system_asset(self, system_id: int, *, asset_type: str) -> SystemAssetRecord | None:
        row = await self.database.fetchone(
            "SELECT * FROM system_assets WHERE system_id = ? AND asset_type = ?",
            (system_id, asset_type),
        )
        if row is None:
            return None
        return SystemAssetRecord(
            system_id=int(row["system_id"]),
            asset_type=str(row["asset_type"]),
            asset_name=str(row["asset_name"]),
            asset_bytes=bytes(row["asset_bytes"]),
            updated_at=str(row["updated_at"]),
        )

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

    async def _repair_system_paths(self, system: SystemRecord) -> SystemRecord:
        normalized_file_path = self._serialize_storage_path(system.file_path) or system.file_path
        normalized_image_path = self._serialize_storage_path(system.image_path) if system.image_path else None

        if normalized_file_path == system.file_path and normalized_image_path == system.image_path:
            return system

        await self.database.execute(
            "UPDATE systems SET file_path = ?, image_path = ? WHERE id = ?",
            (normalized_file_path, normalized_image_path, system.id),
        )
        return replace(
            system,
            file_path=normalized_file_path,
            image_path=normalized_image_path,
        )

    async def _backfill_assets_from_disk(self, system: SystemRecord) -> None:
        file_asset = await self.get_system_asset(system.id, asset_type=self.FILE_ASSET_TYPE)
        if file_asset is None:
            file_path = self.resolve_storage_path(system.file_path)
            if file_path is not None and file_path.is_file():
                await self._upsert_system_asset(
                    system.id,
                    asset_type=self.FILE_ASSET_TYPE,
                    asset_name=file_path.name,
                    asset_bytes=file_path.read_bytes(),
                )

        if not system.image_path:
            return

        image_asset = await self.get_system_asset(system.id, asset_type=self.IMAGE_ASSET_TYPE)
        if image_asset is not None:
            return

        image_path = self.resolve_storage_path(system.image_path)
        if image_path is not None and image_path.is_file():
            await self._upsert_system_asset(
                system.id,
                asset_type=self.IMAGE_ASSET_TYPE,
                asset_name=image_path.name,
                asset_bytes=image_path.read_bytes(),
            )

    async def _upsert_system_asset(
        self,
        system_id: int,
        *,
        asset_type: str,
        asset_name: str,
        asset_bytes: bytes,
    ) -> None:
        await self.database.execute(
            """
            INSERT INTO system_assets (system_id, asset_type, asset_name, asset_bytes)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(system_id, asset_type) DO UPDATE SET
                asset_name = excluded.asset_name,
                asset_bytes = excluded.asset_bytes,
                updated_at = CURRENT_TIMESTAMP
            """,
            (system_id, asset_type, asset_name, asset_bytes),
        )

    async def _delete_system_asset(self, system_id: int, *, asset_type: str) -> None:
        await self.database.execute(
            "DELETE FROM system_assets WHERE system_id = ? AND asset_type = ?",
            (system_id, asset_type),
        )

    async def _ensure_gamepass_not_in_use(
        self,
        gamepass_id: str | None,
        *,
        exclude_system_id: int | None = None,
    ) -> None:
        if not gamepass_id:
            return

        query = "SELECT id, name FROM systems WHERE roblox_gamepass_id = ?"
        parameters: list[object] = [gamepass_id]
        if exclude_system_id is not None:
            query += " AND id != ?"
            parameters.append(exclude_system_id)

        row = await self.database.fetchone(query, tuple(parameters))
        if row is None:
            return

        raise AlreadyExistsError(
            f"That Roblox game pass is already linked to the system '{row['name']}'."
        )

    def _storage_folder_for_system(self, system: SystemRecord, *, fallback_name: str) -> Path:
        resolved_path = self.resolve_storage_path(system.file_path)
        if resolved_path is not None:
            return resolved_path.parent

        normalized_path = self._serialize_storage_path(system.file_path)
        if normalized_path:
            relative_parent = Path(normalized_path).parent
            if str(relative_parent) != ".":
                return self.storage_root / relative_parent

        return self.storage_root / f"{slugify(fallback_name)}-{system.id}"

    def resolve_storage_path(self, stored_path: str | None) -> Path | None:
        if not stored_path:
            return None

        candidates: list[Path] = []
        relative_path = self._extract_storage_relative_path(stored_path)
        if relative_path:
            candidates.append(self.storage_root / Path(relative_path))

        normalized_path = self._normalize_path_separators(stored_path)
        if self._looks_absolute(normalized_path):
            candidates.append(Path(normalized_path))
        elif normalized_path:
            candidates.append(self.storage_root / Path(normalized_path))

        seen: set[str] = set()
        unique_candidates: list[Path] = []
        for candidate in candidates:
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            unique_candidates.append(candidate)

        for candidate in unique_candidates:
            if candidate.is_file():
                return candidate

        return unique_candidates[0] if unique_candidates else None

    def _remove_stored_path(self, stored_path: str | None) -> None:
        resolved_path = self.resolve_storage_path(stored_path)
        if resolved_path is None:
            return
        remove_path(resolved_path)

    def _serialize_storage_path(self, path_value: str | Path | None) -> str | None:
        if path_value is None:
            return None

        relative_path = self._extract_storage_relative_path(path_value)
        if relative_path:
            return relative_path

        normalized = self._normalize_path_separators(str(path_value))
        return normalized or None

    def _extract_storage_relative_path(self, path_value: str | Path) -> str | None:
        normalized = self._normalize_path_separators(str(path_value))
        if not normalized:
            return None

        storage_root = self.storage_root.as_posix().rstrip("/").lower()
        lowered = normalized.lower()
        if lowered.startswith(f"{storage_root}/"):
            relative = normalized[len(storage_root) + 1 :].strip("/")
            return relative or None

        if not self._looks_absolute(normalized):
            relative = normalized.lstrip("/")
            systems_prefix = f"{self.storage_root.name.lower()}/"
            if relative.lower().startswith(systems_prefix):
                relative = relative[len(systems_prefix) :]
            return relative or None

        marker = f"/{self.storage_root.name.lower()}/"
        marker_index = lowered.rfind(marker)
        if marker_index == -1:
            return None

        relative = normalized[marker_index + len(marker) :].strip("/")
        return relative or None

    @staticmethod
    def _normalize_path_separators(path_value: str) -> str:
        return path_value.strip().replace("\\", "/")

    @staticmethod
    def _looks_absolute(path_value: str) -> bool:
        return path_value.startswith("/") or bool(re.match(r"^[A-Za-z]:/", path_value))

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
