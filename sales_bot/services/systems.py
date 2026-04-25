from __future__ import annotations

import asyncio
from dataclasses import replace
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
import re
from pathlib import Path
from uuid import uuid4

import aiosqlite
import discord

from sales_bot.db import Database
from sales_bot.exceptions import AlreadyExistsError, NotFoundError, PermissionDeniedError
from sales_bot.models import SystemAssetRecord, SystemGalleryImageRecord, SystemRecord
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
        is_visible_on_website: bool = True,
        is_for_sale: bool = True,
        is_in_stock: bool = True,
        website_price: str | None = None,
        website_currency: str = "USD",
        is_special_system: bool = False,
    ) -> SystemRecord:
        file_bytes = await file_attachment.read()
        image_uploads: list[tuple[str, bytes, str | None]] = []
        if image_attachment is not None:
            image_uploads.append((image_attachment.filename, await image_attachment.read(), image_attachment.content_type))
        return await self.create_system_from_uploads(
            name=name,
            description=description,
            file_upload=(file_attachment.filename, file_bytes),
            image_uploads=image_uploads or None,
            created_by=created_by,
            paypal_link=paypal_link,
            roblox_gamepass_reference=roblox_gamepass_reference,
            is_visible_on_website=is_visible_on_website,
            is_for_sale=is_for_sale,
            is_in_stock=is_in_stock,
            website_price=website_price,
            website_currency=website_currency,
            is_special_system=is_special_system,
        )

    async def create_system_from_uploads(
        self,
        *,
        name: str,
        description: str,
        file_upload: tuple[str, bytes],
        image_upload: tuple[str, bytes] | None = None,
        image_uploads: list[tuple[str, bytes, str | None]] | None = None,
        created_by: int,
        paypal_link: str | None,
        roblox_gamepass_reference: str | None,
        is_visible_on_website: bool = True,
        is_for_sale: bool = True,
        is_in_stock: bool = True,
        website_price: str | None = None,
        website_currency: str = "USD",
        is_special_system: bool = False,
    ) -> SystemRecord:
        folder = self.storage_root / f"{slugify(name)}-{uuid4().hex[:12]}"
        file_name, file_bytes = file_upload
        file_path = save_named_bytes(file_name, file_bytes, folder)
        safe_file_name = Path(file_name).name or file_path.name
        normalized_image_uploads = list(image_uploads or [])
        if image_upload is not None and not normalized_image_uploads:
            normalized_image_uploads.append((image_upload[0], image_upload[1], None))
        image_bytes: bytes | None = None
        image_content_type: str | None = None
        image_path: Path | None = None
        safe_image_name: str | None = None
        if normalized_image_uploads:
            image_name, image_bytes, image_content_type = normalized_image_uploads[0]
            image_path = save_named_bytes(image_name, image_bytes, folder)
            safe_image_name = Path(image_name).name or image_path.name

        roblox_gamepass_id = self.normalize_gamepass_reference(roblox_gamepass_reference)
        normalized_website_price = self.normalize_website_price(website_price)
        normalized_website_currency = self.normalize_website_currency(website_currency)
        await self._ensure_gamepass_not_in_use(roblox_gamepass_id)
        system_id: int | None = None

        try:
            system_id = await self.database.insert(
                """
                INSERT INTO systems (
                    name,
                    description,
                    image_path,
                    file_path,
                    paypal_link,
                    roblox_gamepass_id,
                    is_visible_on_website,
                    is_for_sale,
                    is_in_stock,
                    website_price,
                    website_currency,
                    is_special_system,
                    created_by
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name.strip(),
                    description.strip(),
                    self._serialize_storage_path(image_path),
                    self._serialize_storage_path(file_path),
                    paypal_link.strip() if paypal_link else None,
                    roblox_gamepass_id,
                    is_visible_on_website,
                    is_for_sale,
                    is_in_stock,
                    normalized_website_price,
                    normalized_website_currency,
                    is_special_system,
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
            if normalized_image_uploads:
                await self._replace_system_gallery_images(system_id, normalized_image_uploads)
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

    async def list_public_systems(self) -> list[SystemRecord]:
        rows = await self.database.fetchall(
            """
            SELECT *
            FROM systems
            WHERE COALESCE(is_visible_on_website, TRUE)
              AND COALESCE(is_for_sale, TRUE)
              AND COALESCE(is_in_stock, TRUE)
                            AND NOT COALESCE(is_special_system, FALSE)
            ORDER BY LOWER(name) ASC
            """
        )
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
        is_visible_on_website: bool | None = None,
        is_for_sale: bool | None = None,
        is_in_stock: bool | None = None,
        website_price: str | None = None,
        website_currency: str | None = None,
        is_special_system: bool | None = None,
        file_upload: tuple[str, bytes] | None = None,
        image_upload: tuple[str, bytes] | None = None,
        image_uploads: list[tuple[str, bytes, str | None]] | None = None,
        replace_images: bool = False,
        clear_image: bool = False,
    ) -> SystemRecord:
        current = await self.get_system(system_id)
        await self._backfill_assets_from_disk(current)

        folder = self._storage_folder_for_system(current, fallback_name=name)
        next_file_path = self._serialize_storage_path(current.file_path) or current.file_path
        next_image_path = self._serialize_storage_path(current.image_path) if current.image_path else None
        new_file_path: Path | None = None
        new_image_path: Path | None = None
        normalized_image_uploads = list(image_uploads or [])
        if image_upload is not None and not normalized_image_uploads:
            normalized_image_uploads.append((image_upload[0], image_upload[1], None))
        primary_image_upload = normalized_image_uploads[0] if normalized_image_uploads else None

        if file_upload is not None:
            filename, data = file_upload
            new_file_path = save_named_bytes(filename, data, folder)
            next_file_path = self._serialize_storage_path(new_file_path) or str(new_file_path)

        if clear_image:
            next_image_path = None

        if primary_image_upload is not None and (replace_images or current.image_path is None):
            filename, data, _content_type = primary_image_upload
            new_image_path = save_named_bytes(filename, data, folder)
            next_image_path = self._serialize_storage_path(new_image_path) or str(new_image_path)

        roblox_gamepass_id = self.normalize_gamepass_reference(roblox_gamepass_reference)
        await self._ensure_gamepass_not_in_use(roblox_gamepass_id, exclude_system_id=system_id)
        cleaned_paypal_link = paypal_link.strip() if paypal_link else None
        next_is_visible_on_website = current.is_visible_on_website if is_visible_on_website is None else is_visible_on_website
        next_is_for_sale = current.is_for_sale if is_for_sale is None else is_for_sale
        next_is_in_stock = current.is_in_stock if is_in_stock is None else is_in_stock
        next_website_price = current.website_price if website_price is None else self.normalize_website_price(website_price)
        next_website_currency = (
            current.website_currency if website_currency is None else self.normalize_website_currency(website_currency)
        )
        next_is_special_system = current.is_special_system if is_special_system is None else is_special_system

        try:
            await self.database.execute(
                """
                UPDATE systems
                SET name = ?,
                    description = ?,
                    file_path = ?,
                    image_path = ?,
                    paypal_link = ?,
                    roblox_gamepass_id = ?,
                    is_visible_on_website = ?,
                    is_for_sale = ?,
                    is_in_stock = ?,
                    website_price = ?,
                    website_currency = ?,
                    is_special_system = ?
                WHERE id = ?
                """,
                (
                    name.strip(),
                    description.strip(),
                    next_file_path,
                    next_image_path,
                    cleaned_paypal_link,
                    roblox_gamepass_id,
                    next_is_visible_on_website,
                    next_is_for_sale,
                    next_is_in_stock,
                    next_website_price,
                    next_website_currency,
                    next_is_special_system,
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
            await self.database.execute("DELETE FROM system_gallery_images WHERE system_id = ?", (system_id,))
        if primary_image_upload is not None and (replace_images or current.image_path is None):
            image_name, image_bytes, _content_type = primary_image_upload
            await self._upsert_system_asset(
                system_id,
                asset_type=self.IMAGE_ASSET_TYPE,
                asset_name=Path(image_name).name or Path(next_image_path or "image.bin").name,
                asset_bytes=image_bytes,
            )
        if normalized_image_uploads:
            if replace_images:
                await self._replace_system_gallery_images(system_id, normalized_image_uploads)
            else:
                await self._append_system_gallery_images(system_id, normalized_image_uploads)

        if new_file_path is not None and current.file_path != str(new_file_path):
            self._remove_stored_path(current.file_path)
        if clear_image and current.image_path:
            self._remove_stored_path(current.image_path)
        if new_image_path is not None and current.image_path != str(new_image_path):
            self._remove_stored_path(current.image_path)

        return await self.get_system(system_id)

    async def list_system_images(self, system_id: int) -> list[SystemGalleryImageRecord]:
        system = await self.get_system(system_id)
        await self._ensure_system_gallery_backfilled(system)
        rows = await self.database.fetchall(
            "SELECT * FROM system_gallery_images WHERE system_id = ? ORDER BY sort_order ASC, id ASC",
            (system_id,),
        )
        return [self._map_gallery_image(row) for row in rows]

    async def list_system_images_for_systems(
        self,
        systems: list[SystemRecord],
    ) -> dict[int, list[SystemGalleryImageRecord]]:
        if not systems:
            return {}

        grouped_images: dict[int, list[SystemGalleryImageRecord]] = {system.id: [] for system in systems}
        system_ids = [system.id for system in systems]
        placeholders = ", ".join("?" for _ in system_ids)
        existing_rows = await self.database.fetchall(
            f"SELECT DISTINCT system_id FROM system_gallery_images WHERE system_id IN ({placeholders})",
            tuple(system_ids),
        )
        existing_system_ids = {int(row["system_id"]) for row in existing_rows}

        missing_gallery_systems = [
            system
            for system in systems
            if system.id not in existing_system_ids and system.image_path
        ]
        if missing_gallery_systems:
            await asyncio.gather(*(self._ensure_system_gallery_backfilled(system) for system in missing_gallery_systems))

        rows = await self.database.fetchall(
            f"SELECT * FROM system_gallery_images WHERE system_id IN ({placeholders}) ORDER BY system_id ASC, sort_order ASC, id ASC",
            tuple(system_ids),
        )
        for row in rows:
            image = self._map_gallery_image(row)
            grouped_images[image.system_id].append(image)
        return grouped_images

    async def get_system_gallery_image(self, image_id: int) -> SystemGalleryImageRecord:
        row = await self.database.fetchone("SELECT * FROM system_gallery_images WHERE id = ?", (image_id,))
        if row is None:
            raise NotFoundError("תמונת מערכת לא נמצאה.")
        return self._map_gallery_image(row)

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
        embed.add_field(
            name="מחיר באתר",
            value=(f"{system.website_price} {system.website_currency}" if system.website_price else "לא מוגדר"),
            inline=True,
        )
        embed.add_field(name="פייפאל", value=system.paypal_link or "לא מוגדר", inline=False)
        embed.add_field(name="גיימפאס רובקס", value=self.gamepass_url_for_id(system.roblox_gamepass_id) or "לא מוגדר", inline=False)
        embed.set_footer(text="Magic System's")
        return embed

    @staticmethod
    def normalize_website_price(price_value: str | None) -> str | None:
        if price_value is None:
            return None

        cleaned = str(price_value).strip().replace(",", "")
        if not cleaned:
            return None

        try:
            amount = Decimal(cleaned)
        except InvalidOperation as exc:
            raise PermissionDeniedError("מחיר האתר חייב להיות מספר תקין.") from exc

        if amount <= 0:
            raise PermissionDeniedError("מחיר האתר חייב להיות גדול מאפס.")

        return format(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")

    @staticmethod
    def normalize_website_currency(currency_value: str | None) -> str:
        cleaned = str(currency_value or "USD").strip().upper()
        if not cleaned:
            return "USD"
        if not re.fullmatch(r"[A-Z]{3}", cleaned):
            raise PermissionDeniedError("מטבע האתר חייב להיות קוד בן 3 אותיות כמו USD או ILS.")
        return cleaned

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

    async def _ensure_system_gallery_backfilled(self, system: SystemRecord) -> None:
        row = await self.database.fetchone(
            "SELECT id FROM system_gallery_images WHERE system_id = ? LIMIT 1",
            (system.id,),
        )
        if row is not None or not system.image_path:
            return

        asset = await self.get_system_asset(system.id, asset_type=self.IMAGE_ASSET_TYPE)
        asset_name: str | None = None
        asset_bytes: bytes | None = None
        content_type: str | None = None
        if asset is not None:
            asset_name = asset.asset_name
            asset_bytes = asset.asset_bytes
            content_type = mimetypes.guess_type(asset.asset_name)[0] or None
        else:
            stored_path = self.resolve_storage_path(system.image_path)
            if stored_path is not None and stored_path.is_file():
                asset_name = stored_path.name
                asset_bytes = stored_path.read_bytes()
                content_type = mimetypes.guess_type(stored_path.name)[0] or None

        if asset_name is None or asset_bytes is None:
            return

        await self.database.execute(
            """
            INSERT INTO system_gallery_images (system_id, asset_name, content_type, asset_bytes, sort_order)
            VALUES (?, ?, ?, ?, 0)
            """,
            (system.id, asset_name, content_type, asset_bytes),
        )

    async def _replace_system_gallery_images(
        self,
        system_id: int,
        images: list[tuple[str, bytes, str | None]],
    ) -> None:
        await self.database.execute("DELETE FROM system_gallery_images WHERE system_id = ?", (system_id,))
        await self.database.executemany(
            """
            INSERT INTO system_gallery_images (system_id, asset_name, content_type, asset_bytes, sort_order)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (system_id, Path(asset_name).name or f"image-{index + 1}", content_type, asset_bytes, index)
                for index, (asset_name, asset_bytes, content_type) in enumerate(images)
            ],
        )

    async def _append_system_gallery_images(
        self,
        system_id: int,
        images: list[tuple[str, bytes, str | None]],
    ) -> None:
        system = await self.get_system(system_id)
        await self._ensure_system_gallery_backfilled(system)
        existing_rows = await self.database.fetchall(
            "SELECT sort_order FROM system_gallery_images WHERE system_id = ? ORDER BY sort_order ASC, id ASC",
            (system_id,),
        )
        start_index = len(existing_rows)
        await self.database.executemany(
            """
            INSERT INTO system_gallery_images (system_id, asset_name, content_type, asset_bytes, sort_order)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (system_id, Path(asset_name).name or f"image-{start_index + index + 1}", content_type, asset_bytes, start_index + index)
                for index, (asset_name, asset_bytes, content_type) in enumerate(images)
            ],
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
    def _map_gallery_image(row: aiosqlite.Row) -> SystemGalleryImageRecord:
        return SystemGalleryImageRecord(
            id=int(row["id"]),
            system_id=int(row["system_id"]),
            asset_name=str(row["asset_name"]),
            content_type=str(row["content_type"]) if row["content_type"] else None,
            asset_bytes=bytes(row["asset_bytes"]),
            sort_order=int(row["sort_order"]),
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _map_system(row: aiosqlite.Row) -> SystemRecord:
        row_keys = set(row.keys())
        return SystemRecord(
            id=int(row["id"]),
            name=str(row["name"]),
            description=str(row["description"]),
            file_path=str(row["file_path"]),
            image_path=str(row["image_path"]) if row["image_path"] else None,
            paypal_link=str(row["paypal_link"]) if row["paypal_link"] else None,
            roblox_gamepass_id=str(row["roblox_gamepass_id"]) if row["roblox_gamepass_id"] else None,
            is_visible_on_website=bool(row["is_visible_on_website"]) if "is_visible_on_website" in row_keys else True,
            is_for_sale=bool(row["is_for_sale"]) if "is_for_sale" in row_keys else True,
            is_in_stock=bool(row["is_in_stock"]) if "is_in_stock" in row_keys else True,
            website_price=(str(row["website_price"]) if "website_price" in row_keys and row["website_price"] else None),
            website_currency=(str(row["website_currency"]).upper() if "website_currency" in row_keys and row["website_currency"] else "USD"),
            is_special_system=bool(row["is_special_system"]) if "is_special_system" in row_keys else False,
            created_by=int(row["created_by"]) if row["created_by"] is not None else None,
            created_at=str(row["created_at"]),
        )
