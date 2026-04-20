from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys

import aiohttp

from dotenv import load_dotenv

from sales_bot.bot import SalesBot
from sales_bot.config import Settings
from sales_bot.logging_config import configure_logging


LOGGER = logging.getLogger(__name__)


def _resolve_build_label() -> str:
    for env_key in ("RENDER_GIT_COMMIT", "RENDER_GIT_BRANCH"):
        value = os.getenv(env_key, "").strip()
        if value:
            return f"{env_key}={value}"

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "commit=unknown"

    commit = result.stdout.strip()
    return f"commit={commit}" if commit else "commit=unknown"


async def self_ping_loop(settings: Settings) -> None:
    if not settings.self_ping_enabled:
        return

    target_url = f"{settings.public_base_url}/health"
    timeout = aiohttp.ClientTimeout(total=15)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        while True:
            await asyncio.sleep(settings.self_ping_interval_seconds)
            try:
                async with session.get(target_url) as response:
                    if response.status >= 400:
                        LOGGER.warning("Self-ping returned HTTP %s from %s", response.status, target_url)
                    else:
                        LOGGER.debug("Self-ping succeeded for %s", target_url)
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("Self-ping failed for %s", target_url)


async def main() -> None:
    load_dotenv()
    configure_logging(os.getenv("LOG_LEVEL", "INFO"))
    LOGGER.info("Booting SalesBot with %s on Python %s", _resolve_build_label(), sys.version.split()[0])

    try:
        settings = Settings.from_env()
        ping_task = asyncio.create_task(self_ping_loop(settings), name="self-ping-loop")
        try:
            async with SalesBot(settings) as bot:
                await bot.start(settings.discord_token)
        finally:
            ping_task.cancel()
            await asyncio.gather(ping_task, return_exceptions=True)
    except Exception:
        LOGGER.exception("Startup failed")
        raise


if __name__ == "__main__":
    asyncio.run(main())
