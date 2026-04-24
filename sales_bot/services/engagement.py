from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Sequence

import aiosqlite
import discord

from sales_bot.db import Database
from sales_bot.exceptions import ExternalServiceError, NotFoundError, PermissionDeniedError
from sales_bot.models import EventRecord, GiveawayRecord, PollOption, PollRecord

if TYPE_CHECKING:
    from sales_bot.bot import SalesBot


DURATION_UNIT_ALIASES = {
    "minute": "minutes",
    "minutes": "minutes",
    "hour": "hours",
    "hours": "hours",
    "day": "days",
    "days": "days",
    "week": "weeks",
    "weeks": "weeks",
}

GIVEAWAY_ENTRY_EMOJI = "🎉"
EVENT_ENTRY_EMOJI = "⭐"
SYSTEM_RANDOM = random.SystemRandom()
ACTIVE_STATUS_VALUES = {"active", "פעיל"}
ENDED_STATUS_VALUES = {"ended", "הסתיים", "נסגר"}
ACTIVE_STATUS_NORMALIZED = frozenset(value.casefold() for value in ACTIVE_STATUS_VALUES)
ENDED_STATUS_NORMALIZED = frozenset(value.casefold() for value in ENDED_STATUS_VALUES)


def _serialize_poll_options(options: Sequence[PollOption]) -> str:
    return json.dumps(
        [{"emoji": option.emoji, "label": option.label} for option in options],
        ensure_ascii=False,
    )


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _is_active_status(status: str) -> bool:
    return status.strip().casefold() in ACTIVE_STATUS_NORMALIZED


def _display_status(status: str) -> str:
    normalized = status.strip().casefold()
    if normalized in ACTIVE_STATUS_NORMALIZED:
        return "פעיל"
    if normalized in ENDED_STATUS_NORMALIZED:
        return "הסתיים"
    return status


def _has_record_ended(*, status: str, ends_at: str | datetime, closed_at: str | None) -> bool:
    if closed_at:
        return True
    if status.strip().casefold() in ENDED_STATUS_NORMALIZED:
        return True
    return _parse_datetime(ends_at) <= datetime.now(UTC)


def _ensure_record_editable(*, message: str, status: str, ends_at: str | datetime, closed_at: str | None) -> None:
    if _has_record_ended(status=status, ends_at=ends_at, closed_at=closed_at):
        raise PermissionDeniedError(message)


def _normalize_duration(duration_value: int, duration_unit: str) -> tuple[int, str, datetime]:
    if duration_value <= 0:
        raise PermissionDeniedError("משך הזמן חייב להיות גדול מאפס.")

    normalized_unit = DURATION_UNIT_ALIASES.get(duration_unit.strip().lower())
    if normalized_unit is None:
        raise PermissionDeniedError("יחידת הזמן חייבת להיות דקות, שעות, ימים או שבועות.")

    delta = timedelta(**{normalized_unit: duration_value})
    return duration_value, normalized_unit, datetime.now(UTC) + delta


def _chunk_lines(lines: Sequence[str], *, max_size: int = 1000) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0

    for line in lines:
        additional_size = len(line) + (1 if current else 0)
        if current and current_size + additional_size > max_size:
            chunks.append("\n".join(current))
            current = [line]
            current_size = len(line)
            continue

        current.append(line)
        current_size += additional_size

    if current:
        chunks.append("\n".join(current))

    return chunks or ["אין נתונים זמינים."]


def _format_meta_line(parts: Sequence[tuple[str, Any]]) -> str:
    return " | ".join(f"**{label}:** {value}" for label, value in parts)


async def _resolve_text_channel(bot: "SalesBot", channel_id: int) -> discord.TextChannel:
    channel = bot.get_channel(channel_id)
    if channel is None:
        channel = await bot.fetch_channel(channel_id)

    if not isinstance(channel, discord.TextChannel):
        raise ExternalServiceError("הערוץ שנבחר חייב להיות ערוץ טקסט שהבוט יכול לפרסם בו.")
    return channel


class PollService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_poll(
        self,
        bot: "SalesBot",
        *,
        created_by: int,
        channel_id: int,
        question: str,
        options: Sequence[PollOption],
        duration_value: int,
        duration_unit: str,
    ) -> PollRecord:
        normalized_options = self._normalize_options(options)
        clean_question = self._normalize_question(question)
        duration_value, duration_unit, ends_at = _normalize_duration(duration_value, duration_unit)
        poll_id = await self.database.insert(
            """
            INSERT INTO polls (channel_id, question, options_json, duration_value, duration_unit, ends_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                channel_id,
                clean_question,
                _serialize_poll_options(normalized_options),
                duration_value,
                duration_unit,
                ends_at,
                created_by,
            ),
        )

        try:
            poll = await self.get_poll(poll_id)
            message = await self._publish_poll_message(bot, poll)
            await self.database.execute(
                "UPDATE polls SET message_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (message.id, poll_id),
            )
        except Exception:
            await self.database.execute("DELETE FROM polls WHERE id = ?", (poll_id,))
            raise

        return await self.get_poll(poll_id)

    async def update_poll(
        self,
        bot: "SalesBot",
        poll_id: int,
        *,
        channel_id: int,
        question: str,
        options: Sequence[PollOption],
        duration_value: int,
        duration_unit: str,
    ) -> PollRecord:
        current = await self.get_poll(poll_id)
        self._ensure_poll_editable(current)
        normalized_options = self._normalize_options(options)
        clean_question = self._normalize_question(question)
        duration_value, duration_unit, ends_at = _normalize_duration(duration_value, duration_unit)
        preview_record = PollRecord(
            id=current.id,
            channel_id=channel_id,
            message_id=current.message_id,
            question=clean_question,
            options=tuple(normalized_options),
            duration_value=duration_value,
            duration_unit=duration_unit,
            ends_at=ends_at.isoformat(),
            status="active",
            result_json=None,
            created_by=current.created_by,
            created_at=current.created_at,
            updated_at=current.updated_at,
            closed_at=None,
        )

        message_id = current.message_id
        if current.message_id is None or current.channel_id != channel_id:
            new_message = await self._publish_poll_message(bot, preview_record)
            message_id = new_message.id
            await self._safe_delete_message(bot, current.channel_id, current.message_id)
        else:
            try:
                existing_message = await self._fetch_message(bot, current.channel_id, current.message_id)
                await existing_message.edit(embed=self.build_embed(preview_record))
                await existing_message.clear_reactions()
                for option in preview_record.options:
                    await existing_message.add_reaction(option.emoji)
                message_id = existing_message.id
            except (discord.Forbidden, discord.HTTPException, NotFoundError):
                new_message = await self._publish_poll_message(bot, preview_record)
                message_id = new_message.id
                await self._safe_delete_message(bot, current.channel_id, current.message_id)

        await self.database.execute(
            """
            UPDATE polls
            SET channel_id = ?,
                message_id = ?,
                question = ?,
                options_json = ?,
                duration_value = ?,
                duration_unit = ?,
                ends_at = ?,
                status = 'active',
                result_json = NULL,
                updated_at = CURRENT_TIMESTAMP,
                closed_at = NULL
            WHERE id = ?
            """,
            (
                channel_id,
                message_id,
                clean_question,
                _serialize_poll_options(normalized_options),
                duration_value,
                duration_unit,
                ends_at,
                poll_id,
            ),
        )
        return await self.get_poll(poll_id)

    async def get_poll(self, poll_id: int) -> PollRecord:
        row = await self.database.fetchone("SELECT * FROM polls WHERE id = ?", (poll_id,))
        if row is None:
            raise NotFoundError("הסקר לא נמצא.")
        return self._map_poll(row)

    async def get_editable_poll(self, poll_id: int) -> PollRecord:
        poll = await self.get_poll(poll_id)
        self._ensure_poll_editable(poll)
        return poll

    async def close_due_polls(self, bot: "SalesBot") -> int:
        rows = await self.database.fetchall(
            "SELECT * FROM polls WHERE status IN ('active', 'פעיל') AND ends_at <= ? ORDER BY ends_at ASC",
            (datetime.now(UTC),),
        )
        finalized = 0
        for row in rows:
            poll = self._map_poll(row)
            result_payload = await self._build_result_payload(bot, poll)
            await self.database.execute(
                """
                UPDATE polls
                SET status = 'ended', result_json = ?, closed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (json.dumps(result_payload, ensure_ascii=False), poll.id),
            )
            finalized_poll = await self.get_poll(poll.id)
            try:
                message = await self._fetch_message(bot, finalized_poll.channel_id, finalized_poll.message_id)
                await message.edit(embed=self.build_embed(finalized_poll))
            except (ExternalServiceError, NotFoundError, discord.HTTPException):
                pass
            finalized += 1
        return finalized

    def build_embed(self, poll: PollRecord) -> discord.Embed:
        ends_at = _parse_datetime(poll.ends_at)
        description = "\n".join(
            [
                _format_meta_line(
                    [
                        ("מזהה", poll.id),
                        ("סטטוס", _display_status(poll.status)),
                    ]
                ),
                "",
                poll.question,
            ]
        )
        embed = discord.Embed(
            title=f"סקר מספר #{poll.id}",
            description=description,
            color=discord.Color.blurple() if _is_active_status(poll.status) else discord.Color.dark_grey(),
        )
        embed.add_field(name="מסתיים ב", value=f"<t:{int(ends_at.timestamp())}:F>\n<t:{int(ends_at.timestamp())}:R>", inline=False)

        option_lines = [f"{option.emoji} {option.label}" for option in poll.options]
        for index, chunk in enumerate(_chunk_lines(option_lines), start=1):
            field_name = "אפשרויות" if index == 1 else f"אפשרויות {index}"
            embed.add_field(name=field_name, value=chunk, inline=False)

        if poll.result_json:
            results = json.loads(poll.result_json)
            result_lines = [
                f"{item['emoji']} {item['label']} - {item['votes']} קולות"
                for item in results
            ]
            for index, chunk in enumerate(_chunk_lines(result_lines), start=1):
                field_name = "תוצאות" if index == 1 else f"תוצאות {index}"
                embed.add_field(name=field_name, value=chunk, inline=False)

        embed.set_footer(text="Magic Studio's")
        return embed

    async def _publish_poll_message(self, bot: "SalesBot", poll: PollRecord) -> discord.Message:
        channel = await _resolve_text_channel(bot, poll.channel_id)
        message = await channel.send(embed=self.build_embed(poll))
        try:
            for option in poll.options:
                await message.add_reaction(option.emoji)
        except (discord.Forbidden, discord.HTTPException) as exc:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            raise ExternalServiceError("לא הצלחתי להוסיף אחד או יותר מהאימוג'ים שנבחרו לסקר.") from exc
        return message

    async def _build_result_payload(self, bot: "SalesBot", poll: PollRecord) -> list[dict[str, Any]]:
        try:
            message = await self._fetch_message(bot, poll.channel_id, poll.message_id)
        except (ExternalServiceError, NotFoundError):
            return [
                {"emoji": option.emoji, "label": option.label, "votes": 0}
                for option in poll.options
            ]

        results: list[dict[str, Any]] = []
        for option in poll.options:
            matching_reaction = next(
                (reaction for reaction in message.reactions if str(reaction.emoji) == option.emoji),
                None,
            )
            vote_count = 0
            if matching_reaction is not None:
                vote_count = max(0, matching_reaction.count - (1 if matching_reaction.me else 0))
            results.append({"emoji": option.emoji, "label": option.label, "votes": vote_count})
        return results

    async def _fetch_message(self, bot: "SalesBot", channel_id: int, message_id: int | None) -> discord.Message:
        if message_id is None:
            raise NotFoundError("הודעת הסקר עדיין לא פורסמה.")
        channel = await _resolve_text_channel(bot, channel_id)
        try:
            return await channel.fetch_message(message_id)
        except discord.NotFound as exc:
            raise NotFoundError("הודעת הסקר לא נמצאה.") from exc
        except discord.HTTPException as exc:
            raise ExternalServiceError("לא הצלחתי להביא את הודעת הסקר מדיסקורד.") from exc

    async def _safe_delete_message(self, bot: "SalesBot", channel_id: int, message_id: int | None) -> None:
        if message_id is None:
            return
        try:
            message = await self._fetch_message(bot, channel_id, message_id)
            await message.delete()
        except (ExternalServiceError, NotFoundError, discord.HTTPException):
            return

    @staticmethod
    def _normalize_question(question: str) -> str:
        cleaned = question.strip()
        if not cleaned:
            raise PermissionDeniedError("שאלת הסקר לא יכולה להיות ריקה.")
        return cleaned

    @staticmethod
    def _normalize_options(options: Sequence[PollOption]) -> list[PollOption]:
        normalized: list[PollOption] = []
        seen_emojis: set[str] = set()
        for option in options:
            emoji = option.emoji.strip()
            label = option.label.strip()
            if not emoji and not label:
                continue
            if not emoji or not label:
                raise PermissionDeniedError("כל אפשרות בסקר חייבת לכלול גם טקסט וגם אימוג'י.")
            if emoji in seen_emojis:
                raise PermissionDeniedError("כל אפשרות בסקר חייבת להשתמש באימוג'י ייחודי.")
            seen_emojis.add(emoji)
            normalized.append(PollOption(emoji=emoji, label=label))

        if len(normalized) < 2:
            raise PermissionDeniedError("סקר חייב להכיל לפחות שתי אפשרויות.")
        return normalized

    @staticmethod
    def _map_poll(row: aiosqlite.Row) -> PollRecord:
        payload = json.loads(str(row["options_json"]))
        return PollRecord(
            id=int(row["id"]),
            channel_id=int(row["channel_id"]),
            message_id=int(row["message_id"]) if row["message_id"] is not None else None,
            question=str(row["question"]),
            options=tuple(PollOption(emoji=str(item["emoji"]), label=str(item["label"])) for item in payload),
            duration_value=int(row["duration_value"]),
            duration_unit=str(row["duration_unit"]),
            ends_at=str(row["ends_at"]),
            status=str(row["status"]),
            result_json=str(row["result_json"]) if row["result_json"] else None,
            created_by=int(row["created_by"]) if row["created_by"] is not None else None,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            closed_at=str(row["closed_at"]) if row["closed_at"] else None,
        )

    @staticmethod
    def _ensure_poll_editable(poll: PollRecord) -> None:
        _ensure_record_editable(
            message="אי אפשר לערוך סקר שכבר הסתיים.",
            status=poll.status,
            ends_at=poll.ends_at,
            closed_at=poll.closed_at,
        )


class GiveawayService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_giveaway(
        self,
        bot: "SalesBot",
        *,
        created_by: int,
        channel_id: int,
        title: str,
        description: str | None,
        requirements: str | None,
        winner_count: int,
        duration_value: int,
        duration_unit: str,
    ) -> GiveawayRecord:
        clean_title = self._normalize_title(title)
        clean_description = self._normalize_optional_text(description)
        clean_requirements = self._normalize_optional_text(requirements)
        clean_winner_count = self._normalize_winner_count(winner_count)
        duration_value, duration_unit, ends_at = _normalize_duration(duration_value, duration_unit)
        giveaway_id = await self.database.insert(
            """
            INSERT INTO giveaways (
                channel_id,
                title,
                description,
                requirements,
                winner_count,
                duration_value,
                duration_unit,
                ends_at,
                created_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                channel_id,
                clean_title,
                clean_description,
                clean_requirements,
                clean_winner_count,
                duration_value,
                duration_unit,
                ends_at,
                created_by,
            ),
        )

        try:
            giveaway = await self.get_giveaway(giveaway_id)
            message = await self._publish_giveaway_message(bot, giveaway)
            await self.database.execute(
                "UPDATE giveaways SET message_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (message.id, giveaway_id),
            )
        except Exception:
            await self.database.execute("DELETE FROM giveaways WHERE id = ?", (giveaway_id,))
            raise

        return await self.get_giveaway(giveaway_id)

    async def update_giveaway(
        self,
        bot: "SalesBot",
        giveaway_id: int,
        *,
        channel_id: int,
        title: str,
        description: str | None,
        requirements: str | None,
        winner_count: int,
        duration_value: int,
        duration_unit: str,
    ) -> GiveawayRecord:
        current = await self.get_giveaway(giveaway_id)
        self._ensure_giveaway_editable(current)
        clean_title = self._normalize_title(title)
        clean_description = self._normalize_optional_text(description)
        clean_requirements = self._normalize_optional_text(requirements)
        clean_winner_count = self._normalize_winner_count(winner_count)
        duration_value, duration_unit, ends_at = _normalize_duration(duration_value, duration_unit)
        preview_record = GiveawayRecord(
            id=current.id,
            channel_id=channel_id,
            message_id=current.message_id,
            title=clean_title,
            description=clean_description,
            requirements=clean_requirements,
            winner_count=clean_winner_count,
            duration_value=duration_value,
            duration_unit=duration_unit,
            ends_at=ends_at.isoformat(),
            status="active",
            result_json=None,
            created_by=current.created_by,
            created_at=current.created_at,
            updated_at=current.updated_at,
            closed_at=None,
        )

        message_id = current.message_id
        if current.message_id is None or current.channel_id != channel_id:
            new_message = await self._publish_giveaway_message(bot, preview_record)
            message_id = new_message.id
            await self._safe_delete_message(bot, current.channel_id, current.message_id)
        else:
            try:
                existing_message = await self._fetch_message(bot, current.channel_id, current.message_id)
                await existing_message.edit(embed=self.build_embed(preview_record))
                if not any(str(reaction.emoji) == GIVEAWAY_ENTRY_EMOJI for reaction in existing_message.reactions):
                    await existing_message.add_reaction(GIVEAWAY_ENTRY_EMOJI)
                message_id = existing_message.id
            except (discord.Forbidden, discord.HTTPException, NotFoundError):
                new_message = await self._publish_giveaway_message(bot, preview_record)
                message_id = new_message.id
                await self._safe_delete_message(bot, current.channel_id, current.message_id)

        await self.database.execute(
            """
            UPDATE giveaways
            SET channel_id = ?,
                message_id = ?,
                title = ?,
                description = ?,
                requirements = ?,
                winner_count = ?,
                duration_value = ?,
                duration_unit = ?,
                ends_at = ?,
                status = 'active',
                result_json = NULL,
                updated_at = CURRENT_TIMESTAMP,
                closed_at = NULL
            WHERE id = ?
            """,
            (
                channel_id,
                message_id,
                clean_title,
                clean_description,
                clean_requirements,
                clean_winner_count,
                duration_value,
                duration_unit,
                ends_at,
                giveaway_id,
            ),
        )
        return await self.get_giveaway(giveaway_id)

    async def get_giveaway(self, giveaway_id: int) -> GiveawayRecord:
        row = await self.database.fetchone("SELECT * FROM giveaways WHERE id = ?", (giveaway_id,))
        if row is None:
            raise NotFoundError("ההגרלה לא נמצאה.")
        return self._map_giveaway(row)

    async def get_editable_giveaway(self, giveaway_id: int) -> GiveawayRecord:
        giveaway = await self.get_giveaway(giveaway_id)
        self._ensure_giveaway_editable(giveaway)
        return giveaway

    async def close_due_giveaways(self, bot: "SalesBot") -> int:
        rows = await self.database.fetchall(
            "SELECT * FROM giveaways WHERE status IN ('active', 'פעיל') AND ends_at <= ? ORDER BY ends_at ASC",
            (datetime.now(UTC),),
        )
        finalized = 0
        for row in rows:
            giveaway = self._map_giveaway(row)
            result_payload = await self._build_result_payload(bot, giveaway)
            await self.database.execute(
                """
                UPDATE giveaways
                SET status = 'ended', result_json = ?, closed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (json.dumps(result_payload, ensure_ascii=False), giveaway.id),
            )
            finalized_giveaway = await self.get_giveaway(giveaway.id)
            try:
                message = await self._fetch_message(bot, finalized_giveaway.channel_id, finalized_giveaway.message_id)
                await message.edit(embed=self.build_embed(finalized_giveaway))
                if result_payload["winner_ids"]:
                    winners = " ".join(f"<@{winner_id}>" for winner_id in result_payload["winner_ids"])
                    await message.channel.send(
                        f"🎉 הגרלה מספר #{finalized_giveaway.id} הסתיימה. מזל טוב {winners}!"
                    )
                else:
                    await message.channel.send(
                        f"🎉 הגרלה מספר #{finalized_giveaway.id} הסתיימה ללא משתתפים תקפים."
                    )
            except (ExternalServiceError, NotFoundError, discord.HTTPException):
                pass
            finalized += 1
        return finalized

    def build_embed(self, giveaway: GiveawayRecord) -> discord.Embed:
        ends_at = _parse_datetime(giveaway.ends_at)
        description = "\n".join(
            [
                _format_meta_line(
                    [
                        ("כמות זוכים", giveaway.winner_count),
                        ("מזהה", giveaway.id),
                        ("סטטוס", _display_status(giveaway.status)),
                    ]
                ),
                "",
                giveaway.description or "לחצו על הריאקשן 🎉 כדי להצטרף להגרלה.",
            ]
        )
        embed = discord.Embed(
            title=f"🎉 הגרלה מספר #{giveaway.id}: {giveaway.title}",
            description=description,
            color=discord.Color.green() if _is_active_status(giveaway.status) else discord.Color.dark_grey(),
        )
        embed.add_field(name="מסתיים ב", value=f"<t:{int(ends_at.timestamp())}:F>\n<t:{int(ends_at.timestamp())}:R>", inline=False)
        embed.add_field(name="כיצד להצטרף", value=f"לחצו על הריאקשן {GIVEAWAY_ENTRY_EMOJI}", inline=False)
        embed.add_field(name="דרישות", value=giveaway.requirements or "אין דרישות נוספות.", inline=False)

        if giveaway.result_json:
            result_payload = json.loads(giveaway.result_json)
            winners = result_payload.get("winner_ids", [])
            entrant_count = int(result_payload.get("entrant_count", 0))
            embed.add_field(name="משתתפים", value=str(entrant_count), inline=True)
            embed.add_field(
                name="זוכים נבחרו",
                value=" ".join(f"<@{winner_id}>" for winner_id in winners) if winners else "אין זוכים תקפים.",
                inline=False,
            )

        embed.set_footer(text="Magic Studio's")
        return embed

    async def _publish_giveaway_message(self, bot: "SalesBot", giveaway: GiveawayRecord) -> discord.Message:
        channel = await _resolve_text_channel(bot, giveaway.channel_id)
        message = await channel.send(embed=self.build_embed(giveaway))
        try:
            await message.add_reaction(GIVEAWAY_ENTRY_EMOJI)
        except (discord.Forbidden, discord.HTTPException) as exc:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            raise ExternalServiceError("לא הצלחתי להוסיף את ריאקשן ההצטרפות להגרלה.") from exc
        return message

    async def _build_result_payload(self, bot: "SalesBot", giveaway: GiveawayRecord) -> dict[str, Any]:
        try:
            message = await self._fetch_message(bot, giveaway.channel_id, giveaway.message_id)
        except (ExternalServiceError, NotFoundError):
            return {"winner_ids": [], "entrant_count": 0}

        entrants: list[discord.abc.User] = []
        for reaction in message.reactions:
            if str(reaction.emoji) != GIVEAWAY_ENTRY_EMOJI:
                continue
            async for user in reaction.users(limit=None):
                if user.bot:
                    continue
                entrants.append(user)
            break

        unique_entrants = list({entrant.id: entrant for entrant in entrants}.values())
        winner_total = min(giveaway.winner_count, len(unique_entrants))
        winner_ids = [winner.id for winner in SYSTEM_RANDOM.sample(unique_entrants, k=winner_total)] if winner_total else []
        return {"winner_ids": winner_ids, "entrant_count": len(unique_entrants)}

    async def _fetch_message(self, bot: "SalesBot", channel_id: int, message_id: int | None) -> discord.Message:
        if message_id is None:
            raise NotFoundError("הודעת ההגרלה עדיין לא פורסמה.")
        channel = await _resolve_text_channel(bot, channel_id)
        try:
            return await channel.fetch_message(message_id)
        except discord.NotFound as exc:
            raise NotFoundError("הודעת ההגרלה לא נמצאה.") from exc
        except discord.HTTPException as exc:
            raise ExternalServiceError("לא הצלחתי להביא את הודעת ההגרלה מדיסקורד.") from exc

    async def _safe_delete_message(self, bot: "SalesBot", channel_id: int, message_id: int | None) -> None:
        if message_id is None:
            return
        try:
            message = await self._fetch_message(bot, channel_id, message_id)
            await message.delete()
        except (ExternalServiceError, NotFoundError, discord.HTTPException):
            return

    @staticmethod
    def _normalize_title(title: str) -> str:
        cleaned = title.strip()
        if not cleaned:
            raise PermissionDeniedError("כותרת ההגרלה לא יכולה להיות ריקה.")
        return cleaned

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @staticmethod
    def _normalize_winner_count(winner_count: int) -> int:
        if winner_count <= 0:
            raise PermissionDeniedError("כמות הזוכים בהגרלה חייבת להיות גדולה מאפס.")
        return winner_count

    @staticmethod
    def _map_giveaway(row: aiosqlite.Row) -> GiveawayRecord:
        return GiveawayRecord(
            id=int(row["id"]),
            channel_id=int(row["channel_id"]),
            message_id=int(row["message_id"]) if row["message_id"] is not None else None,
            title=str(row["title"]),
            description=str(row["description"]) if row["description"] else None,
            requirements=str(row["requirements"]) if row["requirements"] else None,
            winner_count=int(row["winner_count"]),
            duration_value=int(row["duration_value"]),
            duration_unit=str(row["duration_unit"]),
            ends_at=str(row["ends_at"]),
            status=str(row["status"]),
            result_json=str(row["result_json"]) if row["result_json"] else None,
            created_by=int(row["created_by"]) if row["created_by"] is not None else None,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            closed_at=str(row["closed_at"]) if row["closed_at"] else None,
        )

    @staticmethod
    def _ensure_giveaway_editable(giveaway: GiveawayRecord) -> None:
        _ensure_record_editable(
            message="אי אפשר לערוך הגרלה שכבר הסתיימה.",
            status=giveaway.status,
            ends_at=giveaway.ends_at,
            closed_at=giveaway.closed_at,
        )


class EventService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_event(
        self,
        bot: "SalesBot",
        *,
        created_by: int,
        channel_id: int,
        title: str,
        description: str | None,
        reward: str,
        duration_value: int,
        duration_unit: str,
    ) -> EventRecord:
        clean_title = self._normalize_title(title)
        clean_description = self._normalize_optional_text(description)
        clean_reward = self._normalize_reward(reward)
        duration_value, duration_unit, ends_at = _normalize_duration(duration_value, duration_unit)
        event_id = await self.database.insert(
            """
            INSERT INTO events (
                channel_id,
                title,
                description,
                reward,
                duration_value,
                duration_unit,
                ends_at,
                created_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (channel_id, clean_title, clean_description, clean_reward, duration_value, duration_unit, ends_at, created_by),
        )

        try:
            event = await self.get_event(event_id)
            message = await self._publish_event_message(bot, event)
            await self.database.execute(
                "UPDATE events SET message_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (message.id, event_id),
            )
        except Exception:
            await self.database.execute("DELETE FROM events WHERE id = ?", (event_id,))
            raise

        return await self.get_event(event_id)

    async def update_event(
        self,
        bot: "SalesBot",
        event_id: int,
        *,
        channel_id: int,
        title: str,
        description: str | None,
        reward: str,
        duration_value: int,
        duration_unit: str,
    ) -> EventRecord:
        current = await self.get_event(event_id)
        self._ensure_event_editable(current)
        clean_title = self._normalize_title(title)
        clean_description = self._normalize_optional_text(description)
        clean_reward = self._normalize_reward(reward)
        duration_value, duration_unit, ends_at = _normalize_duration(duration_value, duration_unit)
        preview_record = EventRecord(
            id=current.id,
            channel_id=channel_id,
            message_id=current.message_id,
            title=clean_title,
            description=clean_description,
            reward=clean_reward,
            duration_value=duration_value,
            duration_unit=duration_unit,
            ends_at=ends_at.isoformat(),
            status="active",
            winner_user_id=current.winner_user_id,
            winner_message_id=current.winner_message_id,
            rolled_at=current.rolled_at,
            created_by=current.created_by,
            created_at=current.created_at,
            updated_at=current.updated_at,
            closed_at=None,
        )

        message_id = current.message_id
        if current.message_id is None or current.channel_id != channel_id:
            new_message = await self._publish_event_message(bot, preview_record)
            message_id = new_message.id
            await self._safe_delete_message(bot, current.channel_id, current.message_id)
        else:
            try:
                existing_message = await self._fetch_message(bot, current.channel_id, current.message_id)
                await existing_message.edit(embed=self.build_embed(preview_record))
                if not any(str(reaction.emoji) == EVENT_ENTRY_EMOJI for reaction in existing_message.reactions):
                    await existing_message.add_reaction(EVENT_ENTRY_EMOJI)
                message_id = existing_message.id
            except (discord.Forbidden, discord.HTTPException, NotFoundError):
                new_message = await self._publish_event_message(bot, preview_record)
                message_id = new_message.id
                await self._safe_delete_message(bot, current.channel_id, current.message_id)

        await self.database.execute(
            """
            UPDATE events
            SET channel_id = ?,
                message_id = ?,
                title = ?,
                description = ?,
                reward = ?,
                duration_value = ?,
                duration_unit = ?,
                ends_at = ?,
                status = 'active',
                updated_at = CURRENT_TIMESTAMP,
                closed_at = NULL
            WHERE id = ?
            """,
            (channel_id, message_id, clean_title, clean_description, clean_reward, duration_value, duration_unit, ends_at, event_id),
        )
        return await self.get_event(event_id)

    async def get_event(self, event_id: int) -> EventRecord:
        row = await self.database.fetchone("SELECT * FROM events WHERE id = ?", (event_id,))
        if row is None:
            raise NotFoundError("האירוע לא נמצא.")
        return self._map_event(row)

    async def get_editable_event(self, event_id: int) -> EventRecord:
        event = await self.get_event(event_id)
        self._ensure_event_editable(event)
        return event

    async def list_rollable_events(self) -> list[EventRecord]:
        rows = await self.database.fetchall(
            """
            SELECT * FROM events
            WHERE message_id IS NOT NULL AND winner_message_id IS NULL
            ORDER BY created_at DESC
            """
        )
        return [self._map_event(row) for row in rows]

    async def list_rerollable_events(self) -> list[EventRecord]:
        rows = await self.database.fetchall(
            """
            SELECT * FROM events
            WHERE message_id IS NOT NULL AND winner_message_id IS NOT NULL
            ORDER BY rolled_at DESC, created_at DESC
            """
        )
        return [self._map_event(row) for row in rows]

    async def close_due_events(self, bot: "SalesBot") -> int:
        rows = await self.database.fetchall(
            "SELECT * FROM events WHERE status IN ('active', 'פעיל') AND ends_at <= ? ORDER BY ends_at ASC",
            (datetime.now(UTC),),
        )
        finalized = 0
        for row in rows:
            event = self._map_event(row)
            await self.database.execute(
                """
                UPDATE events
                SET status = 'ended', closed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (event.id,),
            )
            finalized_event = await self.get_event(event.id)
            try:
                message = await self._fetch_message(bot, finalized_event.channel_id, finalized_event.message_id)
                await message.edit(embed=self.build_embed(finalized_event))
            except (ExternalServiceError, NotFoundError, discord.HTTPException):
                pass
            finalized += 1
        return finalized

    async def roll_winner(self, bot: "SalesBot", *, event_id: int) -> tuple[EventRecord, discord.User | discord.Member, discord.Message]:
        event = await self.get_event(event_id)
        entrants = await self._collect_entrants(bot, event)
        if not entrants:
            raise PermissionDeniedError("אין כרגע משתתפים תקפים באירוע הזה.")
        winner = SYSTEM_RANDOM.choice(entrants)
        channel = await _resolve_text_channel(bot, event.channel_id)
        winner_message = await channel.send(
            f"ברכותיי {winner.mention} נבחרת כזוכה. פתח טיקט בכדי לקבל את הפרס שלך"
        )
        await self.database.execute(
            """
            UPDATE events
            SET winner_user_id = ?, winner_message_id = ?, rolled_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (winner.id, winner_message.id, event.id),
        )
        return await self.get_event(event.id), winner, winner_message

    async def reroll_winner(self, bot: "SalesBot", *, event_id: int) -> tuple[EventRecord, discord.User | discord.Member, discord.Message]:
        event = await self.get_event(event_id)
        if event.winner_message_id is None:
            raise PermissionDeniedError("לא בוצעה עדיין הגרלה ידנית לאירוע הזה.")
        entrants = await self._collect_entrants(bot, event)
        if event.winner_user_id is not None and len(entrants) > 1:
            entrants = [entrant for entrant in entrants if entrant.id != event.winner_user_id]
        if not entrants:
            raise PermissionDeniedError("אין משתתף חלופי זמין כדי לבצע רירול.")
        winner = SYSTEM_RANDOM.choice(entrants)
        channel = await _resolve_text_channel(bot, event.channel_id)
        try:
            winner_message = await channel.fetch_message(event.winner_message_id)
        except discord.NotFound as exc:
            raise NotFoundError("הודעת הזוכה הקודמת לא נמצאה.") from exc
        except discord.HTTPException as exc:
            raise ExternalServiceError("לא הצלחתי לטעון את הודעת הזוכה הקודמת.") from exc
        await winner_message.edit(
            content=f"אדמין החליף זוכה\nברכותיי {winner.mention} נבחרת כזוכה. פתח טיקט בכדי לקבל את הפרס שלך"
        )
        await self.database.execute(
            """
            UPDATE events
            SET winner_user_id = ?, rolled_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (winner.id, event.id),
        )
        return await self.get_event(event.id), winner, winner_message

    def build_embed(self, event: EventRecord) -> discord.Embed:
        ends_at = _parse_datetime(event.ends_at)
        description = "\n".join(
            [
                _format_meta_line(
                    [
                        ("מזהה", event.id),
                        ("סטטוס", _display_status(event.status)),
                    ]
                ),
                "",
                event.description or "לחצו על הכוכב כדי להשתתף באירוע.",
            ]
        )
        embed = discord.Embed(
            title=f"⭐ אירוע מספר #{event.id}: {event.title}",
            description=description,
            color=discord.Color.gold() if _is_active_status(event.status) else discord.Color.dark_grey(),
        )
        embed.add_field(name="פרס", value=event.reward, inline=False)
        embed.add_field(name="מסתיים ב", value=f"<t:{int(ends_at.timestamp())}:F>\n<t:{int(ends_at.timestamp())}:R>", inline=False)
        embed.add_field(name="איך משתתפים", value=f"לחצו על הריאקשן {EVENT_ENTRY_EMOJI}", inline=False)
        if event.winner_user_id is not None:
            embed.add_field(name="זוכה נוכחי", value=f"<@{event.winner_user_id}>", inline=False)
        embed.set_footer(text="Magic Studio's")
        return embed

    async def _publish_event_message(self, bot: "SalesBot", event: EventRecord) -> discord.Message:
        channel = await _resolve_text_channel(bot, event.channel_id)
        message = await channel.send(embed=self.build_embed(event))
        try:
            await message.add_reaction(EVENT_ENTRY_EMOJI)
        except (discord.Forbidden, discord.HTTPException) as exc:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            raise ExternalServiceError("לא הצלחתי להוסיף את ריאקשן ההשתתפות לאירוע.") from exc
        return message

    async def _collect_entrants(self, bot: "SalesBot", event: EventRecord) -> list[discord.User | discord.Member]:
        message = await self._fetch_message(bot, event.channel_id, event.message_id)
        entrants: list[discord.User | discord.Member] = []
        for reaction in message.reactions:
            if str(reaction.emoji) != EVENT_ENTRY_EMOJI:
                continue
            async for user in reaction.users(limit=None):
                if user.bot:
                    continue
                entrants.append(user)
            break
        return list({entrant.id: entrant for entrant in entrants}.values())

    async def _fetch_message(self, bot: "SalesBot", channel_id: int, message_id: int | None) -> discord.Message:
        if message_id is None:
            raise NotFoundError("הודעת האירוע עדיין לא פורסמה.")
        channel = await _resolve_text_channel(bot, channel_id)
        try:
            return await channel.fetch_message(message_id)
        except discord.NotFound as exc:
            raise NotFoundError("הודעת האירוע לא נמצאה.") from exc
        except discord.HTTPException as exc:
            raise ExternalServiceError("לא הצלחתי להביא את הודעת האירוע מדיסקורד.") from exc

    async def _safe_delete_message(self, bot: "SalesBot", channel_id: int, message_id: int | None) -> None:
        if message_id is None:
            return
        try:
            message = await self._fetch_message(bot, channel_id, message_id)
            await message.delete()
        except (ExternalServiceError, NotFoundError, discord.HTTPException):
            return

    @staticmethod
    def _normalize_title(title: str) -> str:
        cleaned = title.strip()
        if not cleaned:
            raise PermissionDeniedError("כותרת האירוע לא יכולה להיות ריקה.")
        return cleaned

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @staticmethod
    def _normalize_reward(reward: str) -> str:
        cleaned = reward.strip()
        if not cleaned:
            raise PermissionDeniedError("חובה להזין פרס לאירוע.")
        return cleaned

    @staticmethod
    def _map_event(row: aiosqlite.Row) -> EventRecord:
        return EventRecord(
            id=int(row["id"]),
            channel_id=int(row["channel_id"]),
            message_id=int(row["message_id"]) if row["message_id"] is not None else None,
            title=str(row["title"]),
            description=str(row["description"]) if row["description"] else None,
            reward=str(row["reward"]),
            duration_value=int(row["duration_value"]),
            duration_unit=str(row["duration_unit"]),
            ends_at=str(row["ends_at"]),
            status=str(row["status"]),
            winner_user_id=int(row["winner_user_id"]) if row["winner_user_id"] is not None else None,
            winner_message_id=int(row["winner_message_id"]) if row["winner_message_id"] is not None else None,
            rolled_at=str(row["rolled_at"]) if row["rolled_at"] else None,
            created_by=int(row["created_by"]) if row["created_by"] is not None else None,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            closed_at=str(row["closed_at"]) if row["closed_at"] else None,
        )

    @staticmethod
    def _ensure_event_editable(event: EventRecord) -> None:
        _ensure_record_editable(
            message="אי אפשר לערוך אירוע שכבר הסתיים.",
            status=event.status,
            ends_at=event.ends_at,
            closed_at=event.closed_at,
        )