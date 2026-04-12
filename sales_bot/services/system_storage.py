from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

import aiohttp

from sales_bot.exceptions import ExternalServiceError, NotFoundError

if TYPE_CHECKING:
    import discord

    from sales_bot.config import Settings


class SupabaseStorageService:
    PREFIX = "supabase:"

    def __init__(self, session: aiohttp.ClientSession, settings: "Settings") -> None:
        self.session = session
        self.settings = settings

    @property
    def is_configured(self) -> bool:
        return self.settings.supabase_storage_enabled

    def is_supabase_path(self, path: str | None) -> bool:
        return bool(path and path.startswith(self.PREFIX))

    def to_db_path(self, object_key: str) -> str:
        return f"{self.PREFIX}{object_key}"

    def from_db_path(self, stored_path: str) -> str:
        if not self.is_supabase_path(stored_path):
            raise NotFoundError("נתיב הקובץ לא שייך ל-Supabase Storage.")
        return stored_path[len(self.PREFIX):]

    def _object_url(self, object_key: str) -> str:
        bucket = self.settings.supabase_storage_bucket
        assert bucket is not None
        base_url = self.settings.supabase_url
        assert base_url is not None
        quoted_key = quote(object_key, safe="/")
        return f"{base_url.rstrip('/')}/storage/v1/object/{bucket}/{quoted_key}"

    def _headers(self, *, content_type: str | None = None) -> dict[str, str]:
        service_key = self.settings.supabase_service_role_key
        assert service_key is not None
        headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "x-upsert": "true",
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    async def upload_attachment(self, attachment: "discord.Attachment", object_key: str) -> str:
        payload = await attachment.read()
        await self.upload_bytes(payload, object_key, attachment.content_type or "application/octet-stream")
        return self.to_db_path(object_key)

    async def upload_bytes(self, payload: bytes, object_key: str, content_type: str) -> None:
        if not self.is_configured:
            raise ExternalServiceError("Supabase Storage is not configured.")

        async with self.session.post(
            self._object_url(object_key),
            data=payload,
            headers=self._headers(content_type=content_type),
        ) as response:
            if response.status >= 400:
                response_text = await response.text()
                raise ExternalServiceError(f"Supabase Storage upload failed: {response.status} {response_text}")

    async def download_bytes(self, stored_path: str) -> tuple[bytes, str]:
        if not self.is_configured:
            raise ExternalServiceError("Supabase Storage is not configured.")

        object_key = self.from_db_path(stored_path)
        async with self.session.get(self._object_url(object_key), headers=self._headers()) as response:
            if response.status == 404:
                raise NotFoundError("קובץ המערכת לא נמצא ב-Supabase Storage.")
            if response.status >= 400:
                response_text = await response.text()
                raise ExternalServiceError(f"Supabase Storage download failed: {response.status} {response_text}")
            return await response.read(), Path(object_key).name