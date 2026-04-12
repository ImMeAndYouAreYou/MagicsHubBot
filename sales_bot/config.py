from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sales_bot.exceptions import ConfigurationError


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ConfigurationError(f"Missing required environment variable: {name}")
    return value


def _optional_env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _optional_int(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else None


def _optional_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    discord_client_id: int
    discord_client_secret: str
    owner_user_id: int
    vouch_channel_id: int
    order_channel_id: int
    roblox_client_id: str | None
    roblox_client_secret: str | None
    roblox_redirect_uri: str | None
    roblox_entry_link: str | None
    roblox_privacy_policy_url: str | None
    roblox_terms_url: str | None
    public_base_url: str
    paypal_webhook_token: str
    web_host: str
    web_port: int
    sqlite_path: Path
    database_url: str | None
    data_dir: Path
    supabase_url: str | None
    supabase_service_role_key: str | None
    supabase_storage_bucket: str | None
    log_level: str
    sync_commands_on_startup: bool
    dev_guild_id: int | None
    self_ping_enabled: bool
    self_ping_interval_seconds: int

    @property
    def roblox_oauth_enabled(self) -> bool:
        return all(
            (
                self.roblox_client_id,
                self.roblox_client_secret,
                self.roblox_redirect_uri,
                self.roblox_entry_link,
                self.roblox_privacy_policy_url,
                self.roblox_terms_url,
            )
        )

    @property
    def supabase_storage_enabled(self) -> bool:
        return all(
            (
                self.supabase_url,
                self.supabase_service_role_key,
                self.supabase_storage_bucket,
            )
        )

    @classmethod
    def from_env(cls) -> "Settings":
        base_dir = Path(__file__).resolve().parent.parent
        sqlite_path = Path(os.getenv("SQLITE_PATH", "data/bot.sqlite3"))
        if not sqlite_path.is_absolute():
            sqlite_path = base_dir / sqlite_path

        data_dir_raw = _optional_env("DATA_DIR")
        if data_dir_raw:
            data_dir = Path(data_dir_raw)
            if not data_dir.is_absolute():
                data_dir = base_dir / data_dir
        else:
            data_dir = sqlite_path.parent

        database_url = _optional_env("DATABASE_URL")
        supabase_url = _optional_env("SUPABASE_URL")
        supabase_service_role_key = _optional_env("SUPABASE_SERVICE_ROLE_KEY")
        supabase_storage_bucket = _optional_env("SUPABASE_STORAGE_BUCKET")
        supabase_storage_enabled = all((supabase_url, supabase_service_role_key, supabase_storage_bucket))

        if database_url and not data_dir_raw and not supabase_storage_enabled:
            raise ConfigurationError(
                "When DATABASE_URL is configured, you must configure either DATA_DIR for persistent disk storage "
                "or SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, and SUPABASE_STORAGE_BUCKET for Supabase Storage."
            )

        public_base_url = os.getenv("PUBLIC_BASE_URL", "http://localhost:8080").rstrip("/")
        roblox_redirect_uri = _optional_env("ROBLOX_REDIRECT_URI") or f"{public_base_url}/oauth/roblox/callback"
        roblox_entry_link = _optional_env("ROBLOX_ENTRY_LINK") or f"{public_base_url}/link"
        roblox_privacy_policy_url = _optional_env("ROBLOX_PRIVACY_POLICY_URL") or f"{public_base_url}/privacy"
        roblox_terms_url = _optional_env("ROBLOX_TERMS_URL") or f"{public_base_url}/terms"

        settings = cls(
            discord_token=_require_env("DISCORD_TOKEN"),
            discord_client_id=int(_require_env("DISCORD_CLIENT_ID")),
            discord_client_secret=_require_env("DISCORD_CLIENT_SECRET"),
            owner_user_id=int(os.getenv("OWNER_USER_ID", "1204103872348557372")),
            vouch_channel_id=int(os.getenv("VOUCH_CHANNEL_ID", "1492468162372046908")),
            order_channel_id=int(os.getenv("ORDER_CHANNEL_ID", "1492472669059285012")),
            roblox_client_id=_optional_env("ROBLOX_CLIENT_ID"),
            roblox_client_secret=_optional_env("ROBLOX_CLIENT_SECRET"),
            roblox_redirect_uri=roblox_redirect_uri,
            roblox_entry_link=roblox_entry_link,
            roblox_privacy_policy_url=roblox_privacy_policy_url,
            roblox_terms_url=roblox_terms_url,
            public_base_url=public_base_url,
            paypal_webhook_token=_require_env("PAYPAL_WEBHOOK_TOKEN"),
            web_host=os.getenv("WEB_HOST", "0.0.0.0"),
            web_port=int(os.getenv("WEB_PORT", os.getenv("PORT", "8080"))),
            sqlite_path=sqlite_path,
            database_url=database_url,
            data_dir=data_dir,
            supabase_url=supabase_url,
            supabase_service_role_key=supabase_service_role_key,
            supabase_storage_bucket=supabase_storage_bucket,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            sync_commands_on_startup=_optional_bool("SYNC_COMMANDS_ON_STARTUP", True),
            dev_guild_id=_optional_int("DEV_GUILD_ID"),
            self_ping_enabled=_optional_bool("SELF_PING_ENABLED", True),
            self_ping_interval_seconds=int(os.getenv("SELF_PING_INTERVAL_SECONDS", "180")),
        )

        if data_dir_raw or not settings.supabase_storage_enabled:
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            (settings.data_dir / "systems").mkdir(parents=True, exist_ok=True)
            (settings.data_dir / "archive").mkdir(parents=True, exist_ok=True)
        return settings
