from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import aiohttp

from sales_bot.config import Settings
from sales_bot.db import Database
from sales_bot.exceptions import ConfigurationError, ExternalServiceError, NotFoundError
from sales_bot.models import RobloxLinkRecord


class RobloxOAuthService:
    AUTHORIZATION_ENDPOINT = "https://apis.roblox.com/oauth/v1/authorize"
    TOKEN_ENDPOINT = "https://apis.roblox.com/oauth/v1/token"
    USERINFO_ENDPOINT = "https://apis.roblox.com/oauth/v1/userinfo"
    INVENTORY_OWNERSHIP_ENDPOINT = "https://inventory.roblox.com/v1/users/{user_id}/items/GamePass/{gamepass_id}/is-owned"

    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    def ensure_configured(self) -> None:
        if not self.settings.roblox_oauth_enabled:
            raise ConfigurationError(
                "Roblox OAuth is not configured. Set ROBLOX_CLIENT_ID, ROBLOX_CLIENT_SECRET, "
                "ROBLOX_REDIRECT_URI, ROBLOX_ENTRY_LINK, ROBLOX_PRIVACY_POLICY_URL, and ROBLOX_TERMS_URL."
            )

    async def create_state(self, user_id: int) -> str:
        self.ensure_configured()
        state = secrets.token_urlsafe(24)
        expires_at = datetime.now(UTC) + timedelta(minutes=15)
        await self.database.execute(
            "INSERT INTO oauth_states (state, user_id, expires_at) VALUES (?, ?, ?)",
            (state, user_id, expires_at.isoformat()),
        )
        return state

    def build_authorization_url(self, state: str) -> str:
        self.ensure_configured()
        params = {
            "client_id": self.settings.roblox_client_id,
            "response_type": "code",
            "scope": "openid profile",
            "redirect_uri": self.settings.roblox_redirect_uri,
            "state": state,
        }
        return f"{self.AUTHORIZATION_ENDPOINT}?{urlencode(params)}"

    async def consume_state(self, state: str) -> int:
        row = await self.database.fetchone(
            "SELECT * FROM oauth_states WHERE state = ?",
            (state,),
        )
        if row is None:
            raise NotFoundError("OAuth state is invalid or expired.")

        expires_at = datetime.fromisoformat(str(row["expires_at"]))
        await self.database.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
        if expires_at < datetime.now(UTC):
            raise NotFoundError("OAuth state is invalid or expired.")

        return int(row["user_id"])

    async def exchange_code(self, session: aiohttp.ClientSession, code: str) -> dict[str, Any]:
        self.ensure_configured()
        payload = {
            "grant_type": "authorization_code",
            "client_id": self.settings.roblox_client_id,
            "client_secret": self.settings.roblox_client_secret,
            "code": code,
            "redirect_uri": self.settings.roblox_redirect_uri,
        }
        async with session.post(self.TOKEN_ENDPOINT, data=payload) as response:
            data = await response.json(content_type=None)
            if response.status >= 400:
                raise ExternalServiceError(data.get("error_description") or "Roblox token exchange failed.")
            return data

    async def fetch_profile(self, session: aiohttp.ClientSession, access_token: str) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {access_token}"}
        async with session.get(self.USERINFO_ENDPOINT, headers=headers) as response:
            data = await response.json(content_type=None)
            if response.status >= 400:
                raise ExternalServiceError(data.get("error_description") or "Roblox profile fetch failed.")
            return data

    async def link_account(self, user_id: int, profile: dict[str, Any]) -> RobloxLinkRecord:
        roblox_sub = str(profile["sub"])
        username = profile.get("preferred_username") or profile.get("nickname")
        display_name = profile.get("name")
        profile_url = f"https://www.roblox.com/users/{roblox_sub}/profile" if roblox_sub.isdigit() else None

        await self.database.execute(
            """
            INSERT INTO roblox_links (user_id, roblox_sub, roblox_username, roblox_display_name, profile_url, raw_profile_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET
                roblox_sub = excluded.roblox_sub,
                roblox_username = excluded.roblox_username,
                roblox_display_name = excluded.roblox_display_name,
                profile_url = excluded.profile_url,
                raw_profile_json = excluded.raw_profile_json,
                linked_at = CURRENT_TIMESTAMP
            """,
            (
                user_id,
                roblox_sub,
                username,
                display_name,
                profile_url,
                json.dumps(profile),
            ),
        )
        return await self.get_link(user_id)

    async def get_link(self, user_id: int) -> RobloxLinkRecord:
        row = await self.database.fetchone(
            "SELECT * FROM roblox_links WHERE user_id = ?",
            (user_id,),
        )
        if row is None:
            raise NotFoundError("No linked Roblox account found for that user.")
        return RobloxLinkRecord(
            user_id=int(row["user_id"]),
            roblox_sub=str(row["roblox_sub"]),
            roblox_username=str(row["roblox_username"]) if row["roblox_username"] else None,
            roblox_display_name=str(row["roblox_display_name"]) if row["roblox_display_name"] else None,
            profile_url=str(row["profile_url"]) if row["profile_url"] else None,
            linked_at=str(row["linked_at"]),
        )

    async def linked_user_owns_gamepass(
        self,
        session: aiohttp.ClientSession,
        *,
        discord_user_id: int,
        gamepass_id: str,
    ) -> bool:
        link_record = await self.get_link(discord_user_id)
        url = self.INVENTORY_OWNERSHIP_ENDPOINT.format(
            user_id=link_record.roblox_sub,
            gamepass_id=gamepass_id,
        )
        async with session.get(url) as response:
            if response.status >= 400:
                raise ExternalServiceError("לא הצלחתי לבדוק אם המשתמש מחזיק בגיימפאס הזה ברובלוקס.")

            data = await response.json(content_type=None)
            return bool(data)