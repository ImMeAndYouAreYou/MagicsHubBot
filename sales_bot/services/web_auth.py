from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import aiosqlite
import aiohttp

from sales_bot.config import Settings
from sales_bot.db import Database
from sales_bot.exceptions import ConfigurationError, ExternalServiceError, NotFoundError
from sales_bot.models import WebsiteSessionRecord


class WebAuthService:
    AUTHORIZATION_ENDPOINT = "https://discord.com/oauth2/authorize"
    TOKEN_ENDPOINT = "https://discord.com/api/oauth2/token"
    USERINFO_ENDPOINT = "https://discord.com/api/users/@me"
    OAUTH_SCOPES = ("identify",)
    STATE_LIFETIME_MINUTES = 15
    SESSION_LIFETIME_HOURS = 24

    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    @property
    def redirect_uri(self) -> str:
        return f"{self.settings.public_base_url}/auth/discord/callback"

    @property
    def cookie_name(self) -> str:
        return "magic_admin_session"

    def ensure_configured(self) -> None:
        if not self.settings.discord_client_id or not self.settings.discord_client_secret:
            raise ConfigurationError("חסר חיבור Discord OAuth לאתר.")

    async def create_state(self, next_path: str | None = None) -> str:
        self.ensure_configured()
        await self.cleanup_expired()
        state = secrets.token_urlsafe(24)
        expires_at = datetime.now(UTC) + timedelta(minutes=self.STATE_LIFETIME_MINUTES)
        await self.database.execute(
            "INSERT INTO web_oauth_states (state, next_path, expires_at) VALUES (?, ?, ?)",
            (state, self._normalize_next_path(next_path), expires_at.isoformat()),
        )
        return state

    def build_authorization_url(self, state: str) -> str:
        self.ensure_configured()
        params = {
            "client_id": self.settings.discord_client_id,
            "response_type": "code",
            "scope": " ".join(self.OAUTH_SCOPES),
            "redirect_uri": self.redirect_uri,
            "state": state,
        }
        return f"{self.AUTHORIZATION_ENDPOINT}?{urlencode(params)}"

    async def consume_state(self, state: str) -> str:
        await self.cleanup_expired()
        row = await self.database.fetchone("SELECT * FROM web_oauth_states WHERE state = ?", (state,))
        if row is None:
            raise NotFoundError("חיבור האתר פג תוקף. נסה להתחבר שוב.")

        try:
            expires_at = datetime.fromisoformat(str(row["expires_at"]))
        except ValueError as exc:
            await self.database.execute("DELETE FROM web_oauth_states WHERE state = ?", (state,))
            raise NotFoundError("חיבור האתר פג תוקף. נסה להתחבר שוב.") from exc
        if expires_at < datetime.now(UTC):
            await self.database.execute("DELETE FROM web_oauth_states WHERE state = ?", (state,))
            raise NotFoundError("חיבור האתר פג תוקף. נסה להתחבר שוב.")

        await self.database.execute("DELETE FROM web_oauth_states WHERE state = ?", (state,))
        return self._normalize_next_path(str(row["next_path"]) if row["next_path"] else None)

    async def exchange_code(self, session: aiohttp.ClientSession | None, code: str) -> dict[str, Any]:
        self.ensure_configured()
        if session is None:
            raise ExternalServiceError("סשן ה-HTTP של הבוט עדיין לא מוכן.")

        payload = {
            "client_id": str(self.settings.discord_client_id),
            "client_secret": self.settings.discord_client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        async with session.post(self.TOKEN_ENDPOINT, data=payload, headers=headers) as response:
            data = await response.json(content_type=None)
            if response.status >= 400:
                raise ExternalServiceError(
                    str(data.get("error_description") or data.get("error") or "כניסת Discord נכשלה.")
                )
            if not isinstance(data, dict):
                raise ExternalServiceError("Discord החזיר תשובת התחברות לא תקינה.")
            return data

    async def fetch_identity(self, session: aiohttp.ClientSession | None, access_token: str) -> dict[str, Any]:
        if session is None:
            raise ExternalServiceError("סשן ה-HTTP של הבוט עדיין לא מוכן.")

        headers = {"Authorization": f"Bearer {access_token}"}
        async with session.get(self.USERINFO_ENDPOINT, headers=headers) as response:
            data = await response.json(content_type=None)
            if response.status >= 400:
                raise ExternalServiceError(
                    str(data.get("message") if isinstance(data, dict) else "לא הצלחתי לזהות את חשבון ה-Discord שלך.")
                )
            if not isinstance(data, dict):
                raise ExternalServiceError("Discord החזיר פרטי משתמש לא תקינים.")
            return data

    async def create_session(
        self,
        *,
        discord_user_id: int,
        username: str,
        global_name: str | None,
        avatar_hash: str | None,
    ) -> WebsiteSessionRecord:
        await self.cleanup_expired()
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(hours=self.SESSION_LIFETIME_HOURS)
        await self.database.execute(
            """
            INSERT INTO web_sessions (token, discord_user_id, username, global_name, avatar_hash, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (token, discord_user_id, username.strip(), global_name.strip() if global_name else None, avatar_hash, expires_at.isoformat()),
        )
        return await self.get_session(token)

    async def get_session(self, token: str) -> WebsiteSessionRecord:
        await self.cleanup_expired()
        row = await self.database.fetchone("SELECT * FROM web_sessions WHERE token = ?", (token,))
        if row is None:
            raise NotFoundError("סשן האתר לא נמצא או שפג תוקפו.")
        record = self._map_session(row)
        try:
            expires_at = datetime.fromisoformat(record.expires_at)
        except ValueError as exc:
            await self.database.execute("DELETE FROM web_sessions WHERE token = ?", (token,))
            raise NotFoundError("סשן האתר לא נמצא או שפג תוקפו.") from exc
        if expires_at < datetime.now(UTC):
            await self.database.execute("DELETE FROM web_sessions WHERE token = ?", (token,))
            raise NotFoundError("סשן האתר לא נמצא או שפג תוקפו.")

        refreshed_expires_at = datetime.now(UTC) + timedelta(hours=self.SESSION_LIFETIME_HOURS)
        await self.database.execute(
            "UPDATE web_sessions SET last_seen_at = CURRENT_TIMESTAMP, expires_at = ? WHERE token = ?",
            (refreshed_expires_at.isoformat(), token),
        )
        row = await self.database.fetchone("SELECT * FROM web_sessions WHERE token = ?", (token,))
        assert row is not None
        return self._map_session(row)

    async def delete_session(self, token: str) -> None:
        await self.database.execute("DELETE FROM web_sessions WHERE token = ?", (token,))

    async def cleanup_expired(self) -> None:
        now = datetime.now(UTC).isoformat()
        await self.database.execute("DELETE FROM web_oauth_states WHERE expires_at <= ?", (now,))
        await self.database.execute("DELETE FROM web_sessions WHERE expires_at <= ?", (now,))

    @staticmethod
    def display_name_for_session(record: WebsiteSessionRecord) -> str:
        global_name = (record.global_name or "").strip()
        username = record.username.strip()
        if global_name and global_name.casefold() != username.casefold():
            return f"{global_name} (@{username})"
        return global_name or f"@{username}"

    @staticmethod
    def avatar_url(record: WebsiteSessionRecord) -> str | None:
        if not record.avatar_hash:
            return None
        return f"https://cdn.discordapp.com/avatars/{record.discord_user_id}/{record.avatar_hash}.png?size=256"

    @staticmethod
    def _normalize_next_path(next_path: str | None) -> str:
        value = (next_path or "").strip() or "/admin"
        if not value.startswith("/"):
            value = f"/{value}"
        if value.startswith("//"):
            value = "/admin"
        return value

    @staticmethod
    def _map_session(row: aiosqlite.Row) -> WebsiteSessionRecord:
        return WebsiteSessionRecord(
            token=str(row["token"]),
            discord_user_id=int(row["discord_user_id"]),
            username=str(row["username"]),
            global_name=str(row["global_name"]) if row["global_name"] else None,
            avatar_hash=str(row["avatar_hash"]) if row["avatar_hash"] else None,
            expires_at=str(row["expires_at"]),
            created_at=str(row["created_at"]),
            last_seen_at=str(row["last_seen_at"]),
        )