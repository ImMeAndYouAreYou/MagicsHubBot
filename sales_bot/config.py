from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sales_bot.exceptions import ConfigurationError


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ConfigurationError(f"Missing required environment variable: {name}")
    return value


def _require_int_env(name: str) -> int:
    raw = _require_env(name).strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"Environment variable {name} must be a valid integer.") from exc


def _optional_env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _optional_int(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else None


def _int_with_default(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"Environment variable {name} must be a valid integer.") from exc


def _optional_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_runtime_data_dir(base_dir: Path) -> Path:
    candidates = (
        base_dir / "data",
        Path(tempfile.gettempdir()) / "magic-studios-bot-data",
    )
    last_error: OSError | None = None
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            (candidate / "systems").mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError as exc:
            last_error = exc

    raise ConfigurationError("Unable to initialize a writable runtime data directory.") from last_error


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    discord_client_id: int
    discord_client_secret: str
    owner_user_id: int
    primary_guild_id: int | None
    vouch_channel_id: int
    order_channel_id: int
    roblox_verified_role_id: int
    ai_support_channel_id: int
    roblox_client_id: str | None
    roblox_client_secret: str | None
    roblox_redirect_uri: str | None
    roblox_entry_link: str | None
    roblox_privacy_policy_url: str | None
    roblox_terms_url: str | None
    gemini_api_key: str | None
    gemini_model: str
    public_base_url: str
    paypal_webhook_token: str
    web_host: str
    web_port: int
    sqlite_path: Path
    database_url: str | None
    data_dir: Path
    log_level: str
    sync_commands_on_startup: bool
    dev_guild_id: int | None
    self_ping_enabled: bool
    self_ping_interval_seconds: int
    admin_panel_session_minutes: int

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

    @classmethod
    def from_env(cls) -> "Settings":
        base_dir = Path(__file__).resolve().parent.parent
        sqlite_path = Path(os.getenv("SQLITE_PATH", "data/bot.sqlite3"))
        if not sqlite_path.is_absolute():
            sqlite_path = base_dir / sqlite_path

        database_url = _optional_env("DATABASE_URL")
        data_dir = _resolve_runtime_data_dir(base_dir) if database_url else sqlite_path.parent
        public_base_url = os.getenv("PUBLIC_BASE_URL", "http://localhost:8080").rstrip("/")
        roblox_redirect_uri = _optional_env("ROBLOX_REDIRECT_URI") or f"{public_base_url}/oauth/roblox/callback"
        roblox_entry_link = _optional_env("ROBLOX_ENTRY_LINK") or f"{public_base_url}/link"
        roblox_privacy_policy_url = _optional_env("ROBLOX_PRIVACY_POLICY_URL") or f"{public_base_url}/privacy"
        roblox_terms_url = _optional_env("ROBLOX_TERMS_URL") or f"{public_base_url}/terms"

        settings = cls(
            discord_token=_require_env("DISCORD_TOKEN"),
            discord_client_id=_require_int_env("DISCORD_CLIENT_ID"),
            discord_client_secret=_require_env("DISCORD_CLIENT_SECRET"),
            owner_user_id=_int_with_default("OWNER_USER_ID", 1204103872348557372),
            primary_guild_id=_optional_int("PRIMARY_GUILD_ID") or _optional_int("DEV_GUILD_ID"),
            vouch_channel_id=_int_with_default("VOUCH_CHANNEL_ID", 1492468162372046908),
            order_channel_id=_int_with_default("ORDER_CHANNEL_ID", 1492472669059285012),
            roblox_verified_role_id=_int_with_default("ROBLOX_VERIFIED_ROLE_ID", 1494685982161768669),
            ai_support_channel_id=_int_with_default("AI_SUPPORT_CHANNEL_ID", 1494689678975172710),
            roblox_client_id=_optional_env("ROBLOX_CLIENT_ID"),
            roblox_client_secret=_optional_env("ROBLOX_CLIENT_SECRET"),
            roblox_redirect_uri=roblox_redirect_uri,
            roblox_entry_link=roblox_entry_link,
            roblox_privacy_policy_url=roblox_privacy_policy_url,
            roblox_terms_url=roblox_terms_url,
            gemini_api_key=_optional_env("GEMINI_API_KEY"),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            public_base_url=public_base_url,
            paypal_webhook_token=_require_env("PAYPAL_WEBHOOK_TOKEN"),
            web_host=os.getenv("WEB_HOST", "0.0.0.0"),
            web_port=_int_with_default("WEB_PORT", _int_with_default("PORT", 8080)),
            sqlite_path=sqlite_path,
            database_url=database_url,
            data_dir=data_dir,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            sync_commands_on_startup=_optional_bool("SYNC_COMMANDS_ON_STARTUP", True),
            dev_guild_id=_optional_int("DEV_GUILD_ID"),
            self_ping_enabled=_optional_bool("SELF_PING_ENABLED", True),
            self_ping_interval_seconds=_int_with_default("SELF_PING_INTERVAL_SECONDS", 180),
            admin_panel_session_minutes=_int_with_default("ADMIN_PANEL_SESSION_MINUTES", 120),
        )

        if not settings.database_url:
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            (settings.data_dir / "systems").mkdir(parents=True, exist_ok=True)
        return settings
