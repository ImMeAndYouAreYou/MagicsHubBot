from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiohttp
import aiosqlite
import discord

from sales_bot.config import Settings
from sales_bot.db import Database
from sales_bot.exceptions import ExternalServiceError
from sales_bot.models import AIKnowledgeRecord, AITrainingStateRecord

if TYPE_CHECKING:
    from sales_bot.bot import SalesBot


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9\u0590-\u05FF_]{2,}")


def _normalize_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()


def _contains_hebrew(value: str) -> bool:
    return any("\u0590" <= character <= "\u05FF" for character in value)


class AIAssistantService:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings
        self._cached_readme_knowledge: list[AIKnowledgeRecord] | None = None

    async def get_training_state(self) -> AITrainingStateRecord:
        await self._ensure_training_state_row()
        row = await self.database.fetchone("SELECT * FROM ai_training_state WHERE id = 1")
        assert row is not None
        return self._map_training_state(row)

    async def start_training(self, admin_user_id: int) -> AITrainingStateRecord:
        await self._ensure_training_state_row()
        await self.database.execute(
            """
            UPDATE ai_training_state
            SET is_active = ?, started_by = ?, started_at = CURRENT_TIMESTAMP, ended_at = NULL
            WHERE id = ?
            """,
            (True, admin_user_id, 1),
        )
        return await self.get_training_state()

    async def end_training(self) -> AITrainingStateRecord:
        await self._ensure_training_state_row()
        await self.database.execute(
            """
            UPDATE ai_training_state
            SET is_active = ?, ended_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (False, 1),
        )
        return await self.get_training_state()

    async def add_knowledge(
        self,
        *,
        content: str,
        created_by: int | None,
        source_channel_id: int | None,
        source_message_id: int | None,
    ) -> AIKnowledgeRecord | None:
        cleaned = content.strip()
        if not cleaned:
            return None
        knowledge_id = await self.database.insert(
            """
            INSERT INTO ai_knowledge_entries (content, created_by, source_channel_id, source_message_id)
            VALUES (?, ?, ?, ?)
            """,
            (cleaned, created_by, source_channel_id, source_message_id),
        )
        row = await self.database.fetchone("SELECT * FROM ai_knowledge_entries WHERE id = ?", (knowledge_id,))
        assert row is not None
        return self._map_knowledge(row)

    async def add_training_message(self, message: discord.Message) -> AIKnowledgeRecord | None:
        parts: list[str] = []
        if message.content.strip():
            parts.append(message.content.strip())
        if message.attachments:
            attachment_lines = "\n".join(
                f"{attachment.filename}: {attachment.url}"
                for attachment in message.attachments
            )
            parts.append(f"Attachments:\n{attachment_lines}")

        return await self.add_knowledge(
            content="\n\n".join(parts),
            created_by=message.author.id,
            source_channel_id=message.channel.id,
            source_message_id=message.id,
        )

    async def search_knowledge(self, question: str, *, limit: int = 8) -> list[AIKnowledgeRecord]:
        stored_rows = await self.database.fetchall(
            "SELECT * FROM ai_knowledge_entries ORDER BY created_at DESC LIMIT 500"
        )
        records = [self._map_knowledge(row) for row in stored_rows]
        records.extend(await self._build_builtin_knowledge())
        normalized_question = _normalize_text(question)
        question_tokens = set(TOKEN_PATTERN.findall(normalized_question))
        if not question_tokens and normalized_question:
            question_tokens = {normalized_question}

        scored_records: list[tuple[float, AIKnowledgeRecord]] = []
        for record in records:
            normalized_content = _normalize_text(record.content)
            content_tokens = set(TOKEN_PATTERN.findall(normalized_content))
            overlap = len(question_tokens & content_tokens)
            phrase_bonus = 2.0 if normalized_question and normalized_question in normalized_content else 0.0
            if overlap == 0 and phrase_bonus == 0:
                continue
            scored_records.append((overlap + phrase_bonus, record))

        scored_records.sort(key=lambda item: item[0], reverse=True)
        top_records = [record for _, record in scored_records[:limit]]
        if top_records:
            return top_records

        builtin_records = await self._build_builtin_knowledge()
        return builtin_records[:limit]

    async def answer_question(self, session: aiohttp.ClientSession, question: str) -> str:
        knowledge = await self.search_knowledge(question)
        if not knowledge:
            return self._fallback_unknown_answer(question)

        if not self.settings.gemini_api_key:
            return self._fallback_unconfigured_answer(question)

        prompt = self._build_prompt(question, knowledge)
        return await self._call_gemini(session, prompt)

    def _build_prompt(self, question: str, knowledge: list[AIKnowledgeRecord]) -> str:
        knowledge_blocks = []
        for index, record in enumerate(knowledge, start=1):
            trimmed_content = record.content.strip()
            if len(trimmed_content) > 1400:
                trimmed_content = f"{trimmed_content[:1400].rstrip()}..."
            knowledge_blocks.append(f"[{index}]\n{trimmed_content}")

        return (
            "You are Magic Studio's Discord support assistant. "
            "Answer only from the provided knowledge blocks. "
            "Support both Hebrew and English, and reply in the same language as the user's question. "
            "If the answer is not clearly present in the knowledge blocks, say that you do not know yet and ask an admin to train you. "
            "Keep the answer practical and concise.\n\n"
            f"User question:\n{question.strip()}\n\n"
            f"Knowledge blocks:\n{'\n\n'.join(knowledge_blocks)}"
        )

    async def _ensure_training_state_row(self) -> None:
        row = await self.database.fetchone("SELECT 1 FROM ai_training_state WHERE id = 1")
        if row is not None:
            return
        await self.database.execute(
            "INSERT INTO ai_training_state (id, is_active) VALUES (?, ?)",
            (1, False),
        )

    async def _build_builtin_knowledge(self) -> list[AIKnowledgeRecord]:
        records: list[AIKnowledgeRecord] = []
        records.extend(self._build_feature_knowledge())
        records.extend(await self._build_system_catalog_knowledge())
        records.extend(self._load_readme_knowledge())
        return records

    def _build_feature_knowledge(self) -> list[AIKnowledgeRecord]:
        overview = (
            "Magic Studio bot built-in knowledge / מידע מובנה של הבוט:\n"
            "- Roblox linking / קישור רובלוקס: users can link with /link when Roblox OAuth is configured.\n"
            "- System downloads / הורדת מערכות: /getsystem lets a user re-download owned systems or claim systems via a matching Roblox gamepass after linking.\n"
            "- PayPal purchases / רכישת פייפאל: /buywithpaypal creates a pending purchase for systems that have a PayPal link configured.\n"
            "- Robux purchases / רכישת רובקס: /buywithrobux opens the Roblox gamepass for systems that have a Roblox gamepass configured.\n"
            "- Custom orders / הזמנות אישיות: admins can send the custom order panel with /sendorderpanel to the configured order channel.\n"
            "- Ownership tools / כלי בעלות: admins can give, revoke, transfer, and inspect system ownership.\n"
            "- Vouches / הוכחות: the bot supports vouch creation and publishing to the configured vouch channel.\n"
            "- AI training / אימון AI: admins can start training mode with /trainbot and stop it with /endtraining."
        )

        config_summary = (
            "Current bot configuration summary / סיכום תצורה:\n"
            f"- Roblox OAuth enabled: {'yes' if self.settings.roblox_oauth_enabled else 'no'}.\n"
            f"- AI support channel ID: {self.settings.ai_support_channel_id}.\n"
            f"- Order channel ID: {self.settings.order_channel_id}.\n"
            f"- Vouch channel ID: {self.settings.vouch_channel_id}.\n"
            f"- Primary guild ID: {self.settings.primary_guild_id or 'not configured'}."
        )

        return [
            AIKnowledgeRecord(
                id=-1,
                content=overview,
                created_by=None,
                source_channel_id=None,
                source_message_id=None,
                created_at="builtin",
            ),
            AIKnowledgeRecord(
                id=-2,
                content=config_summary,
                created_by=None,
                source_channel_id=None,
                source_message_id=None,
                created_at="builtin",
            ),
        ]

    async def _build_system_catalog_knowledge(self) -> list[AIKnowledgeRecord]:
        rows = await self.database.fetchall(
            "SELECT id, name, description, paypal_link, roblox_gamepass_id FROM systems ORDER BY LOWER(name) ASC LIMIT 200"
        )
        if not rows:
            return []

        records: list[AIKnowledgeRecord] = []
        for index, row in enumerate(rows, start=1):
            payment_modes: list[str] = []
            if row["paypal_link"]:
                payment_modes.append("PayPal")
            if row["roblox_gamepass_id"]:
                payment_modes.append("Robux gamepass")
            if not payment_modes:
                payment_modes.append("manual/admin delivery only")

            content = (
                f"System / מערכת #{row['id']}: {row['name']}\n"
                f"Description / תיאור: {row['description']}\n"
                f"Purchase methods / דרכי רכישה: {', '.join(payment_modes)}\n"
                f"Has PayPal link: {'yes' if row['paypal_link'] else 'no'}\n"
                f"Has Roblox gamepass: {'yes' if row['roblox_gamepass_id'] else 'no'}"
            )
            records.append(
                AIKnowledgeRecord(
                    id=-(1000 + index),
                    content=content,
                    created_by=None,
                    source_channel_id=None,
                    source_message_id=None,
                    created_at="builtin",
                )
            )

        catalog_lines = [
            f"- {row['name']}: {'PayPal' if row['paypal_link'] else ''}{' + ' if row['paypal_link'] and row['roblox_gamepass_id'] else ''}{'Robux gamepass' if row['roblox_gamepass_id'] else ''}".rstrip(': ')
            for row in rows
        ]
        records.append(
            AIKnowledgeRecord(
                id=-999,
                content=(
                    "Current system catalog / קטלוג מערכות נוכחי:\n"
                    + "\n".join(catalog_lines)
                ),
                created_by=None,
                source_channel_id=None,
                source_message_id=None,
                created_at="builtin",
            )
        )
        return records

    def _load_readme_knowledge(self) -> list[AIKnowledgeRecord]:
        if self._cached_readme_knowledge is not None:
            return self._cached_readme_knowledge

        readme_path = Path(__file__).resolve().parents[2] / "README.md"
        if not readme_path.is_file():
            self._cached_readme_knowledge = []
            return self._cached_readme_knowledge

        text = readme_path.read_text(encoding="utf-8")
        sections: list[AIKnowledgeRecord] = []
        heading = "README Overview"
        buffer: list[str] = []
        next_id = -2000

        def flush_section() -> None:
            nonlocal heading, buffer, next_id
            content = "\n".join(buffer).strip()
            if not content:
                buffer = []
                return
            sections.append(
                AIKnowledgeRecord(
                    id=next_id,
                    content=f"{heading}\n{content}",
                    created_by=None,
                    source_channel_id=None,
                    source_message_id=None,
                    created_at="builtin",
                )
            )
            next_id -= 1
            buffer = []

        for line in text.splitlines():
            if line.startswith("## "):
                flush_section()
                heading = line[3:].strip()
                continue
            buffer.append(line)

        flush_section()
        self._cached_readme_knowledge = sections
        return sections

    async def _call_gemini(self, session: aiohttp.ClientSession, prompt: str) -> str:
        api_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.settings.gemini_model}:generateContent?key={self.settings.gemini_api_key}"
        )
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.25,
                "maxOutputTokens": 600,
            },
        }
        async with session.post(api_url, json=payload) as response:
            data: dict[str, Any] = await response.json(content_type=None)
            if response.status >= 400:
                message = data.get("error", {}).get("message") if isinstance(data.get("error"), dict) else None
                raise ExternalServiceError(message or "Gemini request failed.")

        candidates = data.get("candidates") or []
        if not candidates:
            raise ExternalServiceError("Gemini returned no candidates.")

        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        cleaned = text.strip()
        if not cleaned:
            raise ExternalServiceError("Gemini returned an empty answer.")
        return cleaned

    @staticmethod
    def chunk_response(text: str, *, limit: int = 1900) -> list[str]:
        chunks: list[str] = []
        remaining = text.strip()
        while remaining:
            if len(remaining) <= limit:
                chunks.append(remaining)
                break
            split_index = remaining.rfind("\n", 0, limit)
            if split_index <= 0:
                split_index = remaining.rfind(" ", 0, limit)
            if split_index <= 0:
                split_index = limit
            chunks.append(remaining[:split_index].rstrip())
            remaining = remaining[split_index:].lstrip()
        return chunks or [text]

    @staticmethod
    def _map_knowledge(row: aiosqlite.Row) -> AIKnowledgeRecord:
        return AIKnowledgeRecord(
            id=int(row["id"]),
            content=str(row["content"]),
            created_by=int(row["created_by"]) if row["created_by"] is not None else None,
            source_channel_id=int(row["source_channel_id"]) if row["source_channel_id"] is not None else None,
            source_message_id=int(row["source_message_id"]) if row["source_message_id"] is not None else None,
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _map_training_state(row: aiosqlite.Row) -> AITrainingStateRecord:
        is_active_value = row["is_active"]
        if isinstance(is_active_value, bool):
            is_active = is_active_value
        else:
            is_active = bool(int(is_active_value))
        return AITrainingStateRecord(
            is_active=is_active,
            started_by=int(row["started_by"]) if row["started_by"] is not None else None,
            started_at=str(row["started_at"]) if row["started_at"] else None,
            ended_at=str(row["ended_at"]) if row["ended_at"] else None,
        )

    @staticmethod
    def _fallback_unknown_answer(question: str) -> str:
        if _contains_hebrew(question):
            return "עדיין אין לי מספיק מידע מאומן כדי לענות על זה. בקש מאדמין להפעיל אימון ולהוסיף את המידע החסר."
        return "I don't have enough trained information to answer that yet. Ask an admin to train me with the missing details."

    @staticmethod
    def _fallback_unconfigured_answer(question: str) -> str:
        if _contains_hebrew(question):
            return "מערכת ה-AI עדיין לא הוגדרה עם מפתח Gemini תקין, ולכן אני לא יכול לענות כרגע."
        return "The AI assistant is not configured with a valid Gemini API key yet, so I can't answer right now."