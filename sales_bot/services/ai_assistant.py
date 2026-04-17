from __future__ import annotations

import ast
import asyncio
import base64
import html as html_lib
import ipaddress
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence
from urllib.parse import urlparse

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
URL_PATTERN = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
COMMAND_PATTERN = re.compile(r"/([a-z0-9_]+)")
GLOSSARY_PATTERN = re.compile(r"^\s*(?:[-•]\s*)?([A-Za-z][A-Za-z0-9 ._/-]{1,40})\s*(?:->|=>|→)\s*(.{1,80})$", re.MULTILINE)
TEXT_FILE_EXTENSIONS = {
    ".txt",
    ".md",
    ".log",
    ".json",
    ".yaml",
    ".yml",
    ".csv",
    ".ini",
    ".cfg",
    ".lua",
    ".py",
    ".js",
    ".ts",
    ".html",
    ".css",
    ".xml",
}
MAX_TEXT_ATTACHMENT_BYTES = 200_000
MAX_LINK_TEXT_CHARS = 5_000
MAX_ATTACHMENT_TEXT_CHARS = 5_000
MAX_EXTERNAL_PROMPT_CHARS = 1_200
MAX_STORED_SOURCE_CHARS = 5_000
MAX_IMAGE_ATTACHMENTS = 3
MAX_IMAGE_BYTES = 4_000_000
MAX_KNOWLEDGE_BLOCKS = 4
MAX_KNOWLEDGE_BLOCK_CHARS = 650
MAX_PROFILE_RECORDS = 80
MAX_PROFILE_GLOSSARY_ITEMS = 12
DEFAULT_MAX_OUTPUT_TOKENS = 220
MULTIMODAL_MAX_OUTPUT_TOKENS = 260
TRAINING_IMAGE_SUMMARY_TOKENS = 320
GEMINI_PRIMARY_MODEL = "gemini-2.5-flash"
GEMINI_FALLBACK_MODELS = ("gemini-2.5-flash",)
AUTO_LEARN_MIN_TEXT_CHARS = 160
AUTO_LEARN_MAX_TEXT_CHARS = 3_200

PASSIVE_LEARNING_KEYWORDS = {
    "important",
    "remember",
    "rule",
    "rules",
    "always",
    "never",
    "from now on",
    "important info",
    "חשוב",
    "חשובה",
    "תזכור",
    "תזכרי",
    "כלל",
    "כללים",
    "חייב",
    "חייבים",
    "תמיד",
    "אסור",
    "מעתה",
}
DOMAIN_KNOWLEDGE_KEYWORDS = {
    "roblox",
    "discord",
    "dm",
    "paypal",
    "robux",
    "gamepass",
    "system",
    "systems",
    "order",
    "orders",
    "support",
    "poll",
    "giveaway",
    "vouch",
    "blacklist",
    "role",
    "roles",
    "channel",
    "server",
    "guild",
    "ownership",
    "transfer",
    "payment",
    "link",
    "oauth",
    "רובלוקס",
    "דיסקורד",
    "הודעה",
    "פייפאל",
    "רובקס",
    "גיימפאס",
    "מערכת",
    "מערכות",
    "הזמנה",
    "הזמנות",
    "תמיכה",
    "סקר",
    "גיבאווי",
    "הוכחה",
    "בלקליסט",
    "רול",
    "תפקיד",
    "ערוץ",
    "שרת",
    "בעלות",
    "העברה",
    "תשלום",
    "קישור",
}
HEBREW_ONLY_HINTS = {
    "עברית בלבד",
    "רק בעברית",
    "להשיב בעברית",
    "לענות בעברית",
    "reply in hebrew",
    "answer in hebrew",
    "hebrew only",
}
ENGLISH_ONLY_HINTS = {
    "english only",
    "reply in english",
    "answer in english",
    "באנגלית בלבד",
    "לענות באנגלית",
}

HOW_TO_KEYWORDS = {
    "how",
    "steps",
    "guide",
    "explain",
    "איך",
    "שלבים",
    "מדריך",
    "להסביר",
    "עושים",
    "לעשות",
}
LINK_KEYWORDS = {
    "roblox",
    "link",
    "linked",
    "oauth",
    "קישור",
    "לקשר",
    "לחבר",
    "מחבר",
    "חיבור",
    "להתחבר",
    "רובלוקס",
    "מקושר",
    "שם",
    "username",
    "nickname",
}
BUY_KEYWORDS = {
    "buy",
    "purchase",
    "paypal",
    "robux",
    "gamepass",
    "לקנות",
    "קונה",
    "קניה",
    "קנייה",
    "תשלום",
    "פייפאל",
    "רובקס",
    "גיימפאס",
}
RECEIVE_KEYWORDS = {
    "receive",
    "delivery",
    "deliver",
    "dm",
    "get",
    "מקבל",
    "אקבל",
    "לקבל",
    "לקחת",
    "נשלח",
    "נשלחת",
}
ORDER_KEYWORDS = {"order", "orders", "custom", "panel", "הזמנה", "הזמנות", "אישית"}
SYSTEM_KEYWORDS = {"system", "systems", "מערכת", "מערכות", "file", "קובץ"}

COMMAND_DETAIL_OVERRIDES: dict[str, dict[str, str]] = {
    "link": {
        "en": "Opens a Roblox authorization button. After approval, the bot stores the linked Roblox account and in the primary guild it tries to sync the member nickname and assign the verified Roblox role.",
        "he": "פותח כפתור הרשאה ל-Roblox. אחרי האישור הבוט שומר את החשבון המקושר, ובשרת הראשי מנסה לעדכן את הכינוי ולתת את רול האימות של Roblox.",
    },
    "linkedaccount": {
        "en": "Shows the Roblox account currently linked to the user, including the Roblox ID, username, display name, link time, and profile link.",
        "he": "מציג את חשבון ה-Roblox שמקושר כרגע למשתמש, כולל Roblox ID, שם משתמש, Display Name, זמן הקישור וקישור לפרופיל.",
    },
    "checkroblox": {
        "en": "Admin lookup for another user's linked Roblox profile. It also shows the linked profile details and the systems that Discord user currently owns.",
        "he": "בדיקת אדמין לחשבון ה-Roblox המקושר של משתמש אחר. הפקודה מציגה את פרטי הפרופיל המקושר וגם את המערכות שיש לאותו משתמש ב-Discord.",
    },
    "systemslist": {
        "en": "Lists every stored system in the bot. This command requires a linked Roblox account first.",
        "he": "מציג את כל המערכות ששמורות בבוט. הפקודה הזאת דורשת קודם חשבון Roblox מקושר.",
    },
    "addsystem": {
        "en": "Admin-only system creation. It stores the main file, optional image, optional PayPal link, and optional Roblox gamepass reference for delivery and purchase flows.",
        "he": "יצירת מערכת לאדמינים בלבד. הפקודה שומרת את הקובץ הראשי, תמונה אופציונלית, קישור PayPal אופציונלי והפניה אופציונלית לגיימפאס Roblox לצורך מסירה ורכישה.",
    },
    "editsystem": {
        "en": "Admin-only system edit flow. It opens the web edit panel where the name, description, file, image, PayPal link, and Roblox gamepass can be changed.",
        "he": "זרימת עריכת מערכת לאדמינים בלבד. היא פותחת פאנל ווב שבו אפשר לשנות שם, תיאור, קובץ, תמונה, קישור PayPal וגיימפאס Roblox.",
    },
    "sendsystem": {
        "en": "Admin-only direct delivery. It sends the chosen system to the target user in DM and records ownership.",
        "he": "מסירה ישירה לאדמינים בלבד. הפקודה שולחת את המערכת שנבחרה למשתמש ב-DM ורושמת בעלות.",
    },
    "buywithpaypal": {
        "en": "Lets a linked user choose a system that has a PayPal link. The bot creates a pending purchase and sends a PayPal button. After the webhook confirms payment, the system is delivered automatically by DM.",
        "he": "מאפשרת למשתמש מקושר לבחור מערכת שיש לה קישור PayPal. הבוט יוצר רכישה ממתינה ושולח כפתור PayPal. אחרי שה-webhook מאשר את התשלום, המערכת נשלחת אוטומטית ב-DM.",
    },
    "buywithrobux": {
        "en": "Lets a linked user choose a system that has a Roblox gamepass. The bot sends the gamepass button so the user can buy it in Roblox.",
        "he": "מאפשרת למשתמש מקושר לבחור מערכת שיש לה גיימפאס Roblox. הבוט שולח כפתור גיימפאס כדי שהמשתמש יוכל לקנות אותו ב-Roblox.",
    },
    "getsystem": {
        "en": "Checks whether the user already owns the system or whether the linked Roblox account owns the matching gamepass. If the check succeeds, the system is delivered by DM.",
        "he": "בודקת אם למשתמש כבר יש את המערכת או אם לחשבון ה-Roblox המקושר יש את הגיימפאס המתאים. אם הבדיקה מצליחה, המערכת נשלחת ב-DM.",
    },
    "sendorderpanel": {
        "en": "Admin-only command that posts the custom-order panel in the configured order channel.",
        "he": "פקודה לאדמינים בלבד ששולחת את פאנל ההזמנות האישיות לערוץ ההזמנות המוגדר.",
    },
    "list": {
        "en": "Admin order-management command. It opens the active order list and sends the selected order details to the admin's DM.",
        "he": "פקודת ניהול הזמנות לאדמינים. היא פותחת את רשימת ההזמנות הפעילות ושולחת את פרטי ההזמנה שנבחרה ל-DM של האדמין.",
    },
    "vouch": {
        "en": "Opens the vouch creation modal for a seller/admin in the bot.",
        "he": "פותחת חלון יצירת הוכחה עבור מוכר או אדמין שקיים בבוט.",
    },
    "vouches": {
        "en": "Shows the total vouches and average rating for the selected seller/admin.",
        "he": "מציגה את סך ההוכחות ואת הדירוג הממוצע של המוכר או האדמין שנבחר.",
    },
    "poll": {
        "en": "Admin-only poll creation. It opens the web poll panel used to build and publish a stored poll.",
        "he": "יצירת סקר לאדמינים בלבד. היא פותחת את פאנל הווב של הסקרים כדי לבנות ולפרסם סקר שמור.",
    },
    "giveaway": {
        "en": "Admin-only giveaway creation. It opens the web giveaway panel used to build and publish a stored giveaway.",
        "he": "יצירת גיבאווי לאדמינים בלבד. היא פותחת את פאנל הווב של הגיבאווי כדי לבנות ולפרסם גיבאווי שמור.",
    },
    "trainbot": {
        "en": "Admin-only training mode. While it is active, admins can feed messages, files, links, and screenshots into the AI knowledge base and normal AI replies are paused.",
        "he": "מצב אימון לאדמינים בלבד. בזמן שהוא פעיל, אדמינים יכולים להזין הודעות, קבצים, קישורים וצילומי מסך למאגר הידע של ה-AI, והתגובות הרגילות של ה-AI נעצרות.",
    },
    "endtraining": {
        "en": "Turns training mode off so the AI starts answering again in the support channel.",
        "he": "מכבה את מצב האימון כדי שה-AI יחזור לענות בערוץ התמיכה.",
    },
}


@dataclass(slots=True)
class CommandGuide:
    name: str
    description: str
    admin_only: bool
    linked_roblox_required: bool
    allowed_contexts: tuple[str, ...]
    parameter_descriptions: dict[str, str]
    source_file: str


@dataclass(slots=True)
class ResponseProfile:
    force_hebrew: bool = False
    force_english: bool = False
    glossary: tuple[tuple[str, str], ...] = ()


def _normalize_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()


def _contains_hebrew(value: str) -> bool:
    return any("\u0590" <= character <= "\u05FF" for character in value)


class AIAssistantService:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings
        self._cached_readme_knowledge: list[AIKnowledgeRecord] | None = None
        self._cached_command_guides: list[CommandGuide] | None = None

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
            SET is_active = TRUE, started_by = ?, started_at = CURRENT_TIMESTAMP, ended_at = NULL
            WHERE id = 1
            """,
            (admin_user_id,),
        )
        return await self.get_training_state()

    async def end_training(self) -> AITrainingStateRecord:
        await self._ensure_training_state_row()
        await self.database.execute(
            """
            UPDATE ai_training_state
            SET is_active = FALSE, ended_at = CURRENT_TIMESTAMP
            WHERE id = 1
            """,
            (),
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

    async def add_training_message(
        self,
        message: discord.Message,
        session: aiohttp.ClientSession | None,
    ) -> AIKnowledgeRecord | None:
        parts: list[str] = []
        parts.append("Trusted admin training entry.")
        content = message.content.strip()
        if content:
            parts.append(f"Admin training note:\n{self._truncate(content, MAX_STORED_SOURCE_CHARS)}")

        if session is not None:
            parts.extend(await self._extract_message_text_sources(session, message, store_for_training=True))
            image_summary = await self._summarize_training_images(session, message)
            if image_summary:
                parts.append(image_summary)

        attachment_lines = [
            f"{attachment.filename}: {attachment.url}"
            for attachment in message.attachments
        ]
        if attachment_lines:
            parts.append("Attachment references:\n" + "\n".join(attachment_lines[:6]))

        if not parts:
            return None

        return await self.add_knowledge(
            content="\n\n".join(parts),
            created_by=message.author.id,
            source_channel_id=message.channel.id,
            source_message_id=message.id,
        )

    async def maybe_learn_from_message(
        self,
        message: discord.Message,
        session: aiohttp.ClientSession | None,
        *,
        author_is_admin: bool,
        text_sources: Sequence[str] | None = None,
    ) -> AIKnowledgeRecord | None:
        if await self._knowledge_exists_for_message(message.id):
            return None

        content = message.content.strip()
        prepared_sources = list(text_sources or [])
        has_sources = bool(prepared_sources)
        combined_context = "\n".join(part for part in [content, *prepared_sources[:2]] if part).strip()
        if not self._should_passively_learn(
            combined_context,
            author_is_admin=author_is_admin,
            has_sources=has_sources,
        ):
            return None

        parts: list[str] = ["Passive learned context."]
        if content and self._should_store_passive_text(combined_context, content, author_is_admin=author_is_admin):
            parts.append(f"Passive user note:\n{self._truncate(content, AUTO_LEARN_MAX_TEXT_CHARS)}")

        if prepared_sources:
            parts.extend(prepared_sources[:2])

        attachment_lines = [
            f"{attachment.filename}: {attachment.url}"
            for attachment in message.attachments[:4]
        ]
        if attachment_lines:
            parts.append("Attachment references:\n" + "\n".join(attachment_lines))

        if len(parts) == 1:
            return None

        return await self.add_knowledge(
            content="\n\n".join(parts),
            created_by=message.author.id,
            source_channel_id=message.channel.id,
            source_message_id=message.id,
        )

    async def search_knowledge(self, question: str, *, limit: int = MAX_KNOWLEDGE_BLOCKS) -> list[AIKnowledgeRecord]:
        normalized_question = _normalize_text(question)
        if not normalized_question:
            return []

        stored_rows = await self.database.fetchall(
            "SELECT * FROM ai_knowledge_entries ORDER BY created_at DESC LIMIT 500"
        )
        stored_records = [self._map_knowledge(row) for row in stored_rows]
        builtin_records = await self._build_builtin_knowledge()

        question_tokens = set(TOKEN_PATTERN.findall(normalized_question))
        if not question_tokens:
            question_tokens = {normalized_question}

        stored_scored = self._score_knowledge_records(stored_records, question_tokens, normalized_question)
        builtin_scored = self._score_knowledge_records(builtin_records, question_tokens, normalized_question)

        results = [record for _, record in stored_scored[:limit]]
        remaining = max(0, limit - len(results))
        if remaining > 0:
            results.extend(record for _, record in builtin_scored[:remaining])
        return results

    async def answer_message(
        self,
        session: aiohttp.ClientSession,
        message: discord.Message,
        *,
        author_is_admin: bool = False,
    ) -> str:
        question = message.content.strip()
        text_sources = await self._extract_message_text_sources(session, message, store_for_training=False)
        search_text = question or "\n".join(text_sources[:1])
        knowledge = await self.search_knowledge(search_text)
        image_parts = await self._extract_image_parts(message)
        response_profile = await self.get_response_profile()

        if image_parts or text_sources:
            if not self.settings.gemini_api_key:
                answer = self._build_local_answer(
                    question,
                    knowledge,
                    text_sources,
                    response_profile=response_profile,
                    image_unprocessed=bool(image_parts),
                )
                await self.maybe_learn_from_message(
                    message,
                    session,
                    author_is_admin=author_is_admin,
                    text_sources=text_sources,
                )
                return answer

            prompt = self._build_multimodal_prompt(
                question,
                knowledge,
                text_sources,
                response_profile=response_profile,
                image_attached=bool(image_parts),
            )
            try:
                answer = await self._call_gemini(
                    session,
                    [{"text": prompt}, *image_parts],
                    max_output_tokens=MULTIMODAL_MAX_OUTPUT_TOKENS,
                )
                answer = self._apply_response_profile(answer, response_profile)
            except ExternalServiceError as exc:
                answer = self._build_live_ai_unavailable_answer(
                    question,
                    knowledge,
                    text_sources,
                    response_profile=response_profile,
                    image_unprocessed=bool(image_parts),
                    reason=str(exc),
                )
            await self.maybe_learn_from_message(
                message,
                session,
                author_is_admin=author_is_admin,
                text_sources=text_sources,
            )
            return answer

        if knowledge:
            answer = self._build_local_answer(question, knowledge, [], response_profile=response_profile)
            await self.maybe_learn_from_message(
                message,
                session,
                author_is_admin=author_is_admin,
                text_sources=text_sources,
            )
            return answer

        answer = self._fallback_unknown_answer(question)
        await self.maybe_learn_from_message(
            message,
            session,
            author_is_admin=author_is_admin,
            text_sources=text_sources,
        )
        return answer

    async def get_response_profile(self) -> ResponseProfile:
        rows = await self.database.fetchall(
            f"SELECT * FROM ai_knowledge_entries ORDER BY created_at DESC LIMIT {MAX_PROFILE_RECORDS}"
        )
        return self._extract_response_profile([self._map_knowledge(row) for row in rows])

    def _build_multimodal_prompt(
        self,
        question: str,
        knowledge: Sequence[AIKnowledgeRecord],
        text_sources: Sequence[str],
        *,
        response_profile: ResponseProfile,
        image_attached: bool,
    ) -> str:
        knowledge_blocks = []
        for index, record in enumerate(knowledge[:MAX_KNOWLEDGE_BLOCKS], start=1):
            trimmed_content = self._truncate(record.content.strip(), MAX_KNOWLEDGE_BLOCK_CHARS)
            knowledge_blocks.append(f"[{index}]\n{trimmed_content}")

        source_blocks = []
        for index, source_text in enumerate(text_sources[:2], start=1):
            source_blocks.append(f"[Source {index}]\n{self._truncate(source_text, MAX_EXTERNAL_PROMPT_CHARS)}")

        request_label = question or "The user sent attachments or links without extra text."
        prompt_parts = [
            "You are Magic Studio's Discord support assistant.",
            "Use the provided bot knowledge, fetched link text, text file content, and attached screenshots if present.",
            "Reply in the same language as the user's message whenever possible.",
            "Keep the answer concise, practical, and do not invent missing details.",
            f"User request:\n{request_label}",
        ]
        profile_block = self._build_profile_prompt_block(response_profile)
        if profile_block:
            prompt_parts.insert(1, profile_block)
        if knowledge_blocks:
            prompt_parts.append("Bot knowledge:\n" + "\n\n".join(knowledge_blocks))
        if source_blocks:
            prompt_parts.append("File and link text:\n" + "\n\n".join(source_blocks))
        if image_attached:
            prompt_parts.append("Attached screenshots or images are included below. Read visible text and UI details from them before answering.")
        return "\n\n".join(prompt_parts)

    async def _ensure_training_state_row(self) -> None:
        row = await self.database.fetchone("SELECT 1 FROM ai_training_state WHERE id = 1")
        if row is not None:
            return
        await self.database.execute(
            "INSERT INTO ai_training_state (id, is_active) VALUES (1, FALSE)",
            (),
        )

    async def _build_builtin_knowledge(self) -> list[AIKnowledgeRecord]:
        records: list[AIKnowledgeRecord] = []
        records.extend(self._build_feature_knowledge())
        records.extend(self._build_command_catalog_knowledge())
        records.extend(await self._build_system_catalog_knowledge())
        records.extend(self._load_readme_knowledge())
        return records

    def _build_command_catalog_knowledge(self) -> list[AIKnowledgeRecord]:
        records: list[AIKnowledgeRecord] = []
        for index, guide in enumerate(self._load_command_guides(), start=1):
            access_parts: list[str] = []
            if guide.admin_only:
                access_parts.append("admin-only")
            if guide.linked_roblox_required:
                access_parts.append("requires linked Roblox account")
            if guide.allowed_contexts:
                access_parts.append("contexts: " + ", ".join(guide.allowed_contexts))
            access_summary = "; ".join(access_parts) if access_parts else "standard access"
            parameter_summary = "\n".join(
                f"- {name}: {description}"
                for name, description in list(guide.parameter_descriptions.items())[:3]
            )
            content = (
                f"Command / פקודה: /{guide.name}\n"
                f"Description / תיאור: {guide.description or 'No description provided.'}\n"
                f"Access / גישה: {access_summary}\n"
                f"Source file: {guide.source_file}"
            )
            if parameter_summary:
                content += f"\nParameters / פרמטרים:\n{parameter_summary}"
            detail_override = COMMAND_DETAIL_OVERRIDES.get(guide.name)
            if detail_override:
                content += (
                    f"\nBehavior / התנהגות:\n"
                    f"- EN: {detail_override.get('en', '').strip()}\n"
                    f"- HE: {detail_override.get('he', '').strip()}"
                )
            records.append(
                AIKnowledgeRecord(
                    id=-(3000 + index),
                    content=content,
                    created_by=None,
                    source_channel_id=None,
                    source_message_id=None,
                    created_at="builtin",
                )
            )
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
            "- AI training / אימון AI: admins can start training mode with /trainbot and stop it with /endtraining.\n"
            "- Rich AI inputs / קלט AI עשיר: the assistant can read screenshots, image attachments, public links, and text files."
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

    async def _call_gemini(
        self,
        session: aiohttp.ClientSession,
        parts: Sequence[dict[str, Any]],
        *,
        max_output_tokens: int,
    ) -> str:
        last_error: ExternalServiceError | None = None
        for model_name in self._candidate_models():
            api_url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model_name}:generateContent?key={self.settings.gemini_api_key}"
            )
            payload = {
                "contents": [{"role": "user", "parts": list(parts)}],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": max_output_tokens,
                },
            }
            async with session.post(api_url, json=payload) as response:
                data: dict[str, Any] = await response.json(content_type=None)
                if response.status >= 400:
                    error = data.get("error") if isinstance(data, dict) else None
                    message = error.get("message") if isinstance(error, dict) else None
                    last_error = ExternalServiceError(message or f"Gemini request failed for {model_name}.")
                    if response.status in {404, 429} or self._looks_like_quota_error(str(last_error)):
                        continue
                    raise last_error

            candidates = data.get("candidates") or []
            if not candidates:
                last_error = ExternalServiceError(f"Gemini returned no candidates for {model_name}.")
                continue

            response_parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(part.get("text", "") for part in response_parts if isinstance(part, dict))
            cleaned = text.strip()
            if cleaned:
                return cleaned

            last_error = ExternalServiceError(f"Gemini returned an empty answer for {model_name}.")

        if last_error is not None:
            raise last_error
        raise ExternalServiceError("Gemini request failed.")

    async def _extract_message_text_sources(
        self,
        session: aiohttp.ClientSession,
        message: discord.Message,
        *,
        store_for_training: bool,
    ) -> list[str]:
        sources: list[str] = []
        sources.extend(await self._extract_text_file_sources(message, store_for_training=store_for_training))
        sources.extend(await self._extract_link_sources(session, message.content, store_for_training=store_for_training))
        return sources

    async def _extract_text_file_sources(
        self,
        message: discord.Message,
        *,
        store_for_training: bool,
    ) -> list[str]:
        sources: list[str] = []
        for attachment in message.attachments[:4]:
            if not self._is_supported_text_attachment(attachment):
                continue
            if attachment.size > MAX_TEXT_ATTACHMENT_BYTES:
                sources.append(
                    f"Text file skipped because it is too large: {attachment.filename} ({attachment.size} bytes)."
                )
                continue

            try:
                file_bytes = await attachment.read()
            except discord.HTTPException:
                continue

            decoded = self._decode_text_bytes(file_bytes)
            if not decoded:
                continue

            limit = MAX_STORED_SOURCE_CHARS if store_for_training else MAX_ATTACHMENT_TEXT_CHARS
            sources.append(
                f"Text file {attachment.filename}:\n{self._truncate(decoded, limit)}"
            )
        return sources

    async def _extract_link_sources(
        self,
        session: aiohttp.ClientSession,
        text: str,
        *,
        store_for_training: bool,
    ) -> list[str]:
        sources: list[str] = []
        for raw_url in self._extract_public_urls(text)[:2]:
            if not await self._is_safe_public_url(raw_url):
                continue
            try:
                fetched_text = await self._fetch_link_text(session, raw_url)
            except ExternalServiceError:
                continue
            if not fetched_text:
                continue
            limit = MAX_STORED_SOURCE_CHARS if store_for_training else MAX_LINK_TEXT_CHARS
            sources.append(f"Public link {raw_url}:\n{self._truncate(fetched_text, limit)}")
        return sources

    async def _summarize_training_images(
        self,
        session: aiohttp.ClientSession,
        message: discord.Message,
    ) -> str | None:
        image_parts = await self._extract_image_parts(message)
        if not image_parts:
            return None

        if not self.settings.gemini_api_key:
            return "Image attachments were included, but live image extraction is unavailable without Gemini."

        instruction = (
            "Extract reusable support knowledge from these screenshots or images. "
            "Return plain text bullets. Preserve visible error messages, buttons, menus, filenames, settings, steps, and URLs. "
            "Do not invent missing details."
        )
        if message.content.strip():
            instruction += f"\n\nAdmin note:\n{self._truncate(message.content.strip(), 800)}"

        try:
            summary = await self._call_gemini(
                session,
                [{"text": instruction}, *image_parts],
                max_output_tokens=TRAINING_IMAGE_SUMMARY_TOKENS,
            )
        except ExternalServiceError as exc:
            if self._looks_like_quota_error(str(exc)):
                return "Image attachments were included, but Gemini quota was unavailable, so only non-image text could be stored."
            return "Image attachments were included, but live image extraction was unavailable, so only non-image text could be stored."

        return f"Image training summary:\n{self._truncate(summary, MAX_STORED_SOURCE_CHARS)}"

    async def _extract_image_parts(self, message: discord.Message) -> list[dict[str, Any]]:
        parts: list[dict[str, Any]] = []
        for attachment in message.attachments[:MAX_IMAGE_ATTACHMENTS]:
            if not attachment.content_type or not attachment.content_type.startswith("image/"):
                continue
            if attachment.size > MAX_IMAGE_BYTES:
                continue
            try:
                image_bytes = await attachment.read()
            except discord.HTTPException:
                continue
            parts.append(
                {
                    "inlineData": {
                        "mimeType": attachment.content_type,
                        "data": base64.b64encode(image_bytes).decode("ascii"),
                    }
                }
            )
        return parts

    async def _is_safe_public_url(self, raw_url: str) -> bool:
        parsed = urlparse(raw_url)
        if parsed.scheme not in {"http", "https"}:
            return False

        hostname = parsed.hostname
        if not hostname:
            return False

        lowered = hostname.casefold()
        if lowered in {"localhost", "0.0.0.0"} or lowered.endswith(".local"):
            return False

        try:
            ip_address = ipaddress.ip_address(hostname)
        except ValueError:
            ip_address = None

        if ip_address is not None:
            return ip_address.is_global

        try:
            lookup = await asyncio.get_running_loop().getaddrinfo(
                hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=0,
                proto=0,
            )
        except OSError:
            return False

        for result in lookup:
            resolved_ip = result[4][0]
            try:
                if not ipaddress.ip_address(resolved_ip).is_global:
                    return False
            except ValueError:
                return False
        return True

    async def _fetch_link_text(self, session: aiohttp.ClientSession, url: str) -> str:
        timeout = aiohttp.ClientTimeout(total=12)
        headers = {"User-Agent": "MagicStudiosBot/1.0"}
        async with session.get(url, headers=headers, timeout=timeout) as response:
            if response.status >= 400:
                raise ExternalServiceError(f"Failed to fetch linked page: HTTP {response.status}")

            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            body = await response.text(errors="ignore")
            if content_type in {"text/html", "application/xhtml+xml"}:
                cleaned = self._strip_html(body)
            elif content_type.startswith("text/") or content_type in {"application/json", "application/xml", "text/xml"}:
                cleaned = body
            else:
                raise ExternalServiceError("Unsupported linked content type.")
            return self._truncate(cleaned, MAX_LINK_TEXT_CHARS)

    def _build_local_answer(
        self,
        question: str,
        knowledge: Sequence[AIKnowledgeRecord],
        text_sources: Sequence[str],
        *,
        response_profile: ResponseProfile | None = None,
        quota_limited: bool = False,
        image_unprocessed: bool = False,
    ) -> str:
        tokens = set(TOKEN_PATTERN.findall(_normalize_text(question)))
        guides = self._match_command_guides(question)
        lines = self._collect_supporting_lines(tokens, knowledge, text_sources)
        priority_lines = self._collect_priority_supporting_lines(tokens, knowledge, text_sources)
        is_hebrew_response = self._prefers_hebrew_response(question, response_profile)

        if not lines and not guides:
            if image_unprocessed:
                return self._fallback_rate_limited_answer(question, image_only=True)
            return self._fallback_unknown_answer(question)

        note = self._build_local_note(
            is_hebrew=is_hebrew_response,
            quota_limited=quota_limited,
            image_unprocessed=image_unprocessed,
        )
        scenario_body = self._build_scenario_answer(question, guides, priority_lines, is_hebrew=is_hebrew_response)
        if scenario_body:
            return self._apply_response_profile(
                self._compose_local_answer(note, scenario_body),
                response_profile,
            )

        guide_body = self._build_command_guide_answer(guides, priority_lines, is_hebrew=is_hebrew_response)
        if guide_body:
            return self._apply_response_profile(
                self._compose_local_answer(note, guide_body),
                response_profile,
            )

        if is_hebrew_response:
            header = "הנה הפרטים הכי רלוונטיים שמצאתי בקוד ובמידע של הבוט:"
        else:
            header = "Here are the most relevant details I found in the bot code and data:"
        body = "\n".join(f"- {self._truncate(line, 220)}" for line in lines[:8])
        return self._apply_response_profile(
            self._compose_local_answer(note, header + "\n" + body),
            response_profile,
        )

    def _collect_supporting_lines(
        self,
        tokens: set[str],
        knowledge: Sequence[AIKnowledgeRecord],
        text_sources: Sequence[str],
    ) -> list[str]:
        lines: list[str] = []
        seen: set[str] = set()

        for record in knowledge[:MAX_KNOWLEDGE_BLOCKS]:
            for line in self._relevant_lines(record.content, tokens):
                normalized_line = _normalize_text(line)
                if not normalized_line or normalized_line in seen:
                    continue
                seen.add(normalized_line)
                lines.append(line)
                if len(lines) >= 6:
                    break
            if len(lines) >= 6:
                break

        for source_text in text_sources[:2]:
            for line in self._relevant_lines(source_text, tokens):
                normalized_line = _normalize_text(line)
                if not normalized_line or normalized_line in seen:
                    continue
                seen.add(normalized_line)
                lines.append(line)
                if len(lines) >= 8:
                    break
            if len(lines) >= 8:
                break
        return lines

    def _collect_priority_supporting_lines(
        self,
        tokens: set[str],
        knowledge: Sequence[AIKnowledgeRecord],
        text_sources: Sequence[str],
    ) -> list[str]:
        lines: list[str] = []
        seen: set[str] = set()

        for record in knowledge:
            if self._knowledge_kind(record) == "builtin":
                continue
            for line in self._relevant_lines(record.content, tokens):
                normalized_line = _normalize_text(line)
                if not normalized_line or normalized_line in seen:
                    continue
                seen.add(normalized_line)
                lines.append(line)
                if len(lines) >= 4:
                    break
            if len(lines) >= 4:
                break

        for source_text in text_sources[:2]:
            for line in self._relevant_lines(source_text, tokens):
                normalized_line = _normalize_text(line)
                if not normalized_line or normalized_line in seen:
                    continue
                seen.add(normalized_line)
                lines.append(line)
                if len(lines) >= 6:
                    break
            if len(lines) >= 6:
                break
        return lines

    def _relevant_lines(self, content: str, tokens: set[str]) -> list[str]:
        candidate_lines = [line.strip(" -•\t") for line in content.splitlines() if line.strip()]
        if not candidate_lines:
            return []
        if not tokens:
            return candidate_lines[:3]

        matching_lines = [
            line for line in candidate_lines
            if tokens & set(TOKEN_PATTERN.findall(_normalize_text(line)))
        ]
        if matching_lines:
            return matching_lines[:4]
        return candidate_lines[:2]

    def _score_knowledge_records(
        self,
        records: Sequence[AIKnowledgeRecord],
        question_tokens: set[str],
        normalized_question: str,
    ) -> list[tuple[float, AIKnowledgeRecord]]:
        scored_records: list[tuple[float, AIKnowledgeRecord]] = []
        for record in records:
            score = self._score_knowledge_record(record, question_tokens, normalized_question)
            if score <= 0:
                continue
            scored_records.append((score, record))

        scored_records.sort(
            key=lambda item: (
                item[0],
                self._knowledge_sort_priority(item[1]),
                item[1].id,
            ),
            reverse=True,
        )
        return scored_records

    def _score_knowledge_record(
        self,
        record: AIKnowledgeRecord,
        question_tokens: set[str],
        normalized_question: str,
    ) -> float:
        normalized_content = _normalize_text(record.content)
        content_tokens = set(TOKEN_PATTERN.findall(normalized_content))
        overlap = len(question_tokens & content_tokens)
        phrase_bonus = 2.0 if normalized_question and normalized_question in normalized_content else 0.0
        if overlap == 0 and phrase_bonus == 0:
            return 0.0

        kind = self._knowledge_kind(record)
        trust_bonus = 0.0
        if kind == "admin-training":
            trust_bonus += 3.5
        elif kind == "passive-learning":
            trust_bonus += 1.25
        elif kind == "stored":
            trust_bonus += 0.5

        if self._is_instruction_like(record.content):
            trust_bonus += 0.75

        return (overlap * 1.5) + phrase_bonus + trust_bonus

    def _knowledge_sort_priority(self, record: AIKnowledgeRecord) -> int:
        kind = self._knowledge_kind(record)
        if kind == "admin-training":
            return 4
        if kind == "passive-learning":
            return 3
        if kind == "stored":
            return 2
        return 1

    def _knowledge_kind(self, record: AIKnowledgeRecord) -> str:
        if record.id < 0:
            return "builtin"
        stripped = record.content.lstrip()
        if stripped.startswith("Trusted admin training entry.") or stripped.startswith("Admin training note:"):
            return "admin-training"
        if stripped.startswith("Passive learned context.") or stripped.startswith("Passive user note:"):
            return "passive-learning"
        return "stored"

    def _candidate_models(self) -> list[str]:
        models: list[str] = []
        for candidate in (GEMINI_PRIMARY_MODEL, self.settings.gemini_model, *GEMINI_FALLBACK_MODELS):
            cleaned = candidate.strip()
            if cleaned and cleaned not in models:
                models.append(cleaned)
        return models

    def _load_command_guides(self) -> list[CommandGuide]:
        if self._cached_command_guides is not None:
            return self._cached_command_guides

        guides: list[CommandGuide] = []
        cogs_dir = Path(__file__).resolve().parents[1] / "cogs"
        for file_path in sorted(cogs_dir.glob("*.py")):
            if file_path.name == "__init__.py":
                continue
            try:
                source = file_path.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except (OSError, SyntaxError):
                continue

            for node in ast.walk(tree):
                if not isinstance(node, ast.AsyncFunctionDef):
                    continue
                guide = self._build_command_guide_from_node(node, file_path.name)
                if guide is not None:
                    guides.append(guide)

        guides.sort(key=lambda guide: guide.name)
        self._cached_command_guides = guides
        return guides

    def _build_command_guide_from_node(self, node: ast.AsyncFunctionDef, source_file: str) -> CommandGuide | None:
        command_name: str | None = None
        description = ""
        admin_required = False
        linked_required = False
        allowed_contexts: list[str] = []
        parameter_descriptions: dict[str, str] = {}

        for decorator in node.decorator_list:
            dotted_name = self._ast_dotted_name(decorator.func if isinstance(decorator, ast.Call) else decorator)
            if dotted_name == "app_commands.command" and isinstance(decorator, ast.Call):
                command_name = self._ast_keyword_string(decorator, "name") or node.name
                description = self._ast_keyword_string(decorator, "description") or ""
            elif dotted_name == "admin_only":
                admin_required = True
            elif dotted_name == "linked_roblox_required":
                linked_required = True
            elif dotted_name == "app_commands.allowed_contexts" and isinstance(decorator, ast.Call):
                for keyword in decorator.keywords:
                    if isinstance(keyword.value, ast.Constant) and keyword.value.value is True and keyword.arg:
                        allowed_contexts.append(keyword.arg)
            elif dotted_name == "app_commands.describe" and isinstance(decorator, ast.Call):
                for keyword in decorator.keywords:
                    if keyword.arg:
                        description_text = self._ast_literal_string(keyword.value)
                        if description_text:
                            parameter_descriptions[keyword.arg] = description_text

        if not command_name:
            return None

        return CommandGuide(
            name=command_name,
            description=description,
            admin_only=admin_required,
            linked_roblox_required=linked_required,
            allowed_contexts=tuple(dict.fromkeys(allowed_contexts)),
            parameter_descriptions=parameter_descriptions,
            source_file=source_file,
        )

    def _match_command_guides(self, question: str) -> list[CommandGuide]:
        normalized_question = _normalize_text(question)
        if not normalized_question:
            return []

        tokens = set(TOKEN_PATTERN.findall(normalized_question))
        explicit_commands = {match.casefold() for match in COMMAND_PATTERN.findall(question)}
        guides = self._load_command_guides()
        scored: list[tuple[float, CommandGuide]] = []

        for guide in guides:
            score = 0.0
            if guide.name.casefold() in explicit_commands:
                score += 12.0
            if guide.name.casefold() in normalized_question:
                score += 6.0

            description_tokens = set(TOKEN_PATTERN.findall(_normalize_text(guide.description)))
            score += len(tokens & description_tokens)

            for keyword in self._command_intent_keywords(guide.name):
                if keyword in normalized_question:
                    score += 2.0

            if score > 0:
                scored.append((score, guide))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [guide for _, guide in scored[:4]]

    def _build_scenario_answer(
        self,
        question: str,
        guides: Sequence[CommandGuide],
        supporting_lines: Sequence[str],
        *,
        is_hebrew: bool,
    ) -> str | None:
        normalized = _normalize_text(question)
        tokens = set(TOKEN_PATTERN.findall(normalized))
        if not tokens:
            return None

        has_link_intent = bool(tokens & LINK_KEYWORDS)
        has_buy_intent = bool(tokens & BUY_KEYWORDS)
        has_receive_intent = bool(tokens & RECEIVE_KEYWORDS)
        has_order_intent = bool(tokens & ORDER_KEYWORDS)
        has_system_intent = bool(tokens & SYSTEM_KEYWORDS)

        if has_link_intent and (has_buy_intent or has_receive_intent):
            return self._build_flow_answer(
                ["link", "linkedaccount", "buywithpaypal", "buywithrobux", "getsystem"],
                supporting_lines,
                is_hebrew=is_hebrew,
                title_he="לפי הזרימה שממומשת בבוט, זה הסדר הנכון:",
                title_en="Based on the flow implemented in the bot, this is the right order:",
            )

        if has_link_intent:
            return self._build_flow_answer(
                ["link", "linkedaccount"],
                supporting_lines,
                is_hebrew=is_hebrew,
                title_he="ככה קישור חשבון רובלוקס עובד בבוט:",
                title_en="This is how Roblox account linking works in the bot:",
            )

        if has_buy_intent and has_receive_intent:
            return self._build_flow_answer(
                ["buywithpaypal", "buywithrobux", "getsystem", "linkedaccount"],
                supporting_lines,
                is_hebrew=is_hebrew,
                title_he="ככה קנייה ומסירה עובדות בבוט:",
                title_en="This is how purchase and delivery work in the bot:",
            )

        if has_order_intent:
            return self._build_flow_answer(
                ["sendorderpanel", "list"],
                supporting_lines,
                is_hebrew=is_hebrew,
                title_he="ככה מערכת ההזמנות עובדת לפי הקוד של הבוט:",
                title_en="This is how the order system works according to the bot code:",
            )

        if has_system_intent and any(keyword in normalized for keyword in {"edit", "add", "send", "remove", "admin", "לערוך", "להוסיף", "לשלוח", "אדמין"}):
            return self._build_flow_answer(
                ["addsystem", "editsystem", "sendsystem", "systemslist"],
                supporting_lines,
                is_hebrew=is_hebrew,
                title_he="ככה ניהול מערכות עובד בבוט:",
                title_en="This is how system management works in the bot:",
            )

        if guides and self._is_how_to_question(tokens):
            return self._build_command_guide_answer(guides, supporting_lines, is_hebrew=is_hebrew)

        return None

    def _build_flow_answer(
        self,
        command_order: Sequence[str],
        supporting_lines: Sequence[str],
        *,
        is_hebrew: bool,
        title_he: str,
        title_en: str,
    ) -> str:
        guide_map = {guide.name: guide for guide in self._load_command_guides()}
        lines: list[str] = [title_he if is_hebrew else title_en]
        step_number = 1
        step_lines: list[str] = []
        for command_name in command_order:
            guide = guide_map.get(command_name)
            line = self._format_command_guide(guide, is_hebrew=is_hebrew) if guide is not None else None
            if not line:
                continue
            step_lines.append(f"{step_number}. {line}")
            step_number += 1

        lines.extend(self._merge_supporting_lines_into_steps(step_lines, supporting_lines, command_order))

        return "\n".join(lines)

    def _build_command_guide_answer(
        self,
        guides: Sequence[CommandGuide],
        supporting_lines: Sequence[str],
        *,
        is_hebrew: bool,
    ) -> str | None:
        if not guides:
            return None

        lines: list[str] = []
        for index, guide in enumerate(guides[:3], start=1):
            formatted = self._format_command_guide(guide, is_hebrew=is_hebrew)
            if formatted:
                lines.append(f"{index}. {formatted}")

        for line in self._clean_supporting_lines(supporting_lines)[:2]:
            lines.append(f"- {line}")

        return "\n".join(lines)

    def _merge_supporting_lines_into_steps(
        self,
        step_lines: Sequence[str],
        supporting_lines: Sequence[str],
        command_order: Sequence[str],
    ) -> list[str]:
        if not step_lines:
            return []

        cleaned_facts = self._clean_supporting_lines(supporting_lines)
        if not cleaned_facts:
            return list(step_lines)

        enriched_lines = list(step_lines)
        attached_counts = [0] * len(enriched_lines)
        leftovers: list[str] = []

        for fact in cleaned_facts[:4]:
            target_index = self._choose_step_index_for_fact(fact, command_order)
            if target_index is None or target_index >= len(enriched_lines):
                leftovers.append(fact)
                continue
            if attached_counts[target_index] >= 1:
                leftovers.append(fact)
                continue
            enriched_lines[target_index] = f"{enriched_lines[target_index]} {fact}"
            attached_counts[target_index] += 1

        for fact in leftovers[:2]:
            enriched_lines.append(f"- {fact}")

        return enriched_lines

    def _choose_step_index_for_fact(self, fact: str, command_order: Sequence[str]) -> int | None:
        normalized = _normalize_text(fact)
        command_priority: list[tuple[set[str], tuple[str, ...]]] = [
            (LINK_KEYWORDS, ("link", "linkedaccount")),
            ({"paypal", "פייפאל", "payment", "webhook"}, ("buywithpaypal",)),
            ({"robux", "רובקס", "gamepass", "גיימפאס"}, ("buywithrobux",)),
            (RECEIVE_KEYWORDS | {"confirm", "approved", "אישור", "נשלחת", "ownership", "בעלות"}, ("getsystem", "linkedaccount")),
            (ORDER_KEYWORDS, ("sendorderpanel", "list")),
            (SYSTEM_KEYWORDS, ("addsystem", "editsystem", "sendsystem", "systemslist")),
        ]
        for keyword_set, commands in command_priority:
            if not any(keyword in normalized for keyword in keyword_set):
                continue
            for command_name in commands:
                if command_name in command_order:
                    return command_order.index(command_name)
        return 0 if command_order else None

    def _clean_supporting_lines(self, supporting_lines: Sequence[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw_line in supporting_lines:
            line = self._truncate(raw_line.strip(), 220)
            if not line:
                continue
            lowered = line.casefold()
            if lowered.startswith(("command /", "description /", "parameters /", "source file")):
                continue
            if lowered.startswith(("access /", "behavior /", "attachment references")):
                continue
            if lowered.startswith(("trusted admin training entry", "admin training note", "passive learned context", "passive user note")):
                continue
            if lowered.startswith(("en:", "he:", "user:", "contexts:")):
                continue
            if "->" in line or "=>" in line or "→" in line:
                continue
            if re.match(r"^[a-z_]+:\s", line):
                continue
            if lowered in seen:
                continue
            seen.add(lowered)
            cleaned.append(line.rstrip(". ") + ".")
        return cleaned

    def _format_command_guide(self, guide: CommandGuide, *, is_hebrew: bool) -> str:
        detail = COMMAND_DETAIL_OVERRIDES.get(guide.name, {}).get("he" if is_hebrew else "en") or guide.description
        detail = detail.strip()
        access_parts: list[str] = []
        if guide.admin_only:
            access_parts.append("לאדמינים בלבד" if is_hebrew else "admin-only")
        if guide.linked_roblox_required:
            access_parts.append("דורש חשבון Roblox מקושר קודם" if is_hebrew else "requires a linked Roblox account first")
        context_text = self._format_allowed_contexts(guide.allowed_contexts, is_hebrew=is_hebrew)
        if context_text:
            access_parts.append(context_text)

        parameter_text = self._format_parameter_hint(guide, is_hebrew=is_hebrew)
        suffix_parts = access_parts[:]
        if parameter_text:
            suffix_parts.append(parameter_text)

        if suffix_parts:
            return f"`/{guide.name}` - {detail} ({'; '.join(suffix_parts)})."
        return f"`/{guide.name}` - {detail}."

    def _format_allowed_contexts(self, contexts: Sequence[str], *, is_hebrew: bool) -> str | None:
        if not contexts:
            return None
        values = set(contexts)
        if values >= {"guilds", "dms", "private_channels"}:
            return "עובד גם בשרת וגם ב-DM" if is_hebrew else "works in both servers and DMs"
        if "guilds" in values and not {"dms", "private_channels"} & values:
            return "מיועד לשרתים" if is_hebrew else "meant for servers"
        if {"dms", "private_channels"} & values and "guilds" not in values:
            return "מיועד ל-DM" if is_hebrew else "meant for DMs"
        return None

    def _format_parameter_hint(self, guide: CommandGuide, *, is_hebrew: bool) -> str | None:
        if not guide.parameter_descriptions:
            return None
        important_parameters = list(guide.parameter_descriptions.items())[:2]
        labels = []
        for name, description in important_parameters:
            labels.append(f"{name}: {self._truncate(description, 70)}")
        if not labels:
            return None
        if is_hebrew:
            return "פרמטרים חשובים: " + ", ".join(labels)
        return "important parameters: " + ", ".join(labels)

    def _build_local_note(self, *, is_hebrew: bool, quota_limited: bool, image_unprocessed: bool) -> str | None:
        if is_hebrew:
            quota_note = "מכסת Gemini כרגע מוגבלת, אז לא השתמשתי בתשובה חיצונית."
            image_note = "עיבוד תמונה חי לא היה זמין כרגע, אז נשענתי רק על הטקסט והקוד המקומי."
        else:
            quota_note = "Gemini quota is limited right now, so I did not rely on an external AI response."
            image_note = "Live image processing was not available right now, so I relied only on local text and source code."

        parts = []
        if quota_limited:
            parts.append(quota_note)
        if image_unprocessed:
            parts.append(image_note)
        if not parts:
            return None
        return " ".join(parts)

    @staticmethod
    def _compose_local_answer(note: str | None, body: str) -> str:
        if note:
            return "\n\n".join([note, body])
        return body

    def _prefers_hebrew_response(self, question: str, response_profile: ResponseProfile | None) -> bool:
        if response_profile is not None:
            if response_profile.force_hebrew and not response_profile.force_english:
                return True
            if response_profile.force_english and not response_profile.force_hebrew:
                return False
        return _contains_hebrew(question)

    def _extract_response_profile(self, records: Sequence[AIKnowledgeRecord]) -> ResponseProfile:
        force_hebrew = False
        force_english = False
        glossary: dict[str, str] = {}
        for record in records:
            if self._knowledge_kind(record) != "admin-training":
                continue
            normalized_content = _normalize_text(record.content)
            if not force_hebrew and any(hint in normalized_content for hint in HEBREW_ONLY_HINTS):
                force_hebrew = True
            if not force_english and any(hint in normalized_content for hint in ENGLISH_ONLY_HINTS):
                force_english = True
            for source_term, target_term in self._extract_glossary_pairs(record.content):
                key = source_term.casefold()
                if key in glossary:
                    continue
                glossary[key] = target_term
                if len(glossary) >= MAX_PROFILE_GLOSSARY_ITEMS:
                    break

        glossary_items = tuple((source, target) for source, target in glossary.items())
        return ResponseProfile(
            force_hebrew=force_hebrew,
            force_english=force_english,
            glossary=glossary_items,
        )

    def _build_profile_prompt_block(self, response_profile: ResponseProfile) -> str | None:
        lines: list[str] = []
        if response_profile.force_hebrew and not response_profile.force_english:
            lines.append("Trained response rule: reply in Hebrew.")
        elif response_profile.force_english and not response_profile.force_hebrew:
            lines.append("Trained response rule: reply in English.")

        if response_profile.glossary:
            lines.append("Preferred trained glossary:")
            for source, target in response_profile.glossary[:6]:
                lines.append(f"- {source} -> {target}")

        if not lines:
            return None
        return "\n".join(lines)

    def _apply_response_profile(self, text: str, response_profile: ResponseProfile | None) -> str:
        if response_profile is None or not response_profile.glossary:
            return text

        updated = text
        for source_term, target_term in sorted(
            response_profile.glossary,
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            pattern = re.compile(re.escape(source_term), re.IGNORECASE)

            def replace_match(match: re.Match[str]) -> str:
                if match.start() > 0 and updated[match.start() - 1] == "/":
                    return match.group(0)
                return target_term

            updated = pattern.sub(replace_match, updated)
        return updated

    def _extract_glossary_pairs(self, content: str) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for match in GLOSSARY_PATTERN.finditer(content):
            source = match.group(1).strip().strip('"\'')
            target = match.group(2).strip().strip('"\'')
            if not source or not target:
                continue
            pairs.append((source, target))
        return pairs

    def _is_instruction_like(self, content: str) -> bool:
        normalized = _normalize_text(content)
        if any(keyword in normalized for keyword in PASSIVE_LEARNING_KEYWORDS):
            return True
        if any(hint in normalized for hint in HEBREW_ONLY_HINTS | ENGLISH_ONLY_HINTS):
            return True
        return bool(GLOSSARY_PATTERN.search(content))

    async def _knowledge_exists_for_message(self, message_id: int) -> bool:
        row = await self.database.fetchone(
            "SELECT 1 FROM ai_knowledge_entries WHERE source_message_id = ? LIMIT 1",
            (message_id,),
        )
        return row is not None

    def _should_passively_learn(
        self,
        combined_context: str,
        *,
        author_is_admin: bool,
        has_sources: bool,
    ) -> bool:
        content = combined_context.strip()
        if has_sources:
            return self._is_domain_relevant(content) and self._looks_like_reference_note(content)
        if not content:
            return False
        normalized = _normalize_text(content)
        if author_is_admin and self._is_instruction_like(content):
            return True
        if not self._is_domain_relevant(content):
            return False
        if content.count("?") > 0 or normalized.startswith("/"):
            return False
        if not self._looks_like_reference_note(content):
            return False
        if len(content) >= AUTO_LEARN_MIN_TEXT_CHARS:
            return author_is_admin or any(keyword in normalized for keyword in PASSIVE_LEARNING_KEYWORDS)
        return any(keyword in normalized for keyword in PASSIVE_LEARNING_KEYWORDS)

    def _should_store_passive_text(self, combined_context: str, content: str, *, author_is_admin: bool) -> bool:
        normalized = _normalize_text(combined_context)
        if author_is_admin:
            return self._is_domain_relevant(combined_context)
        if not self._is_domain_relevant(combined_context):
            return False
        if content.count("?") > 0:
            return False
        if not self._looks_like_reference_note(combined_context):
            return False
        if len(content) >= AUTO_LEARN_MIN_TEXT_CHARS:
            return any(keyword in normalized for keyword in PASSIVE_LEARNING_KEYWORDS)
        return any(keyword in normalized for keyword in PASSIVE_LEARNING_KEYWORDS)

    def _is_domain_relevant(self, content: str) -> bool:
        normalized = _normalize_text(content)
        if any(keyword in normalized for keyword in DOMAIN_KNOWLEDGE_KEYWORDS):
            return True
        if COMMAND_PATTERN.search(content):
            return True
        return False

    @staticmethod
    def _looks_like_reference_note(content: str) -> bool:
        sentence_count = sum(content.count(marker) for marker in (". ", "! ", "? ", "\n")) + 1
        has_structure = any(marker in content for marker in ("->", "=>", "→", ":", "\n-", "\n•"))
        return has_structure or sentence_count >= 2

    @staticmethod
    def _is_how_to_question(tokens: set[str]) -> bool:
        return bool(tokens & HOW_TO_KEYWORDS)

    @staticmethod
    def _command_intent_keywords(command_name: str) -> set[str]:
        mapping: dict[str, set[str]] = {
            "link": LINK_KEYWORDS,
            "linkedaccount": LINK_KEYWORDS,
            "checkroblox": LINK_KEYWORDS | {"check", "profile", "ownership", "owned", "בדיקה"},
            "systemslist": SYSTEM_KEYWORDS | {"list", "show", "רשימה"},
            "addsystem": SYSTEM_KEYWORDS | {"add", "upload", "create", "להוסיף"},
            "editsystem": SYSTEM_KEYWORDS | {"edit", "update", "לערוך", "לעדכן"},
            "sendsystem": SYSTEM_KEYWORDS | RECEIVE_KEYWORDS | {"send", "grant", "לשלוח"},
            "buywithpaypal": BUY_KEYWORDS | {"paypal", "webhook"},
            "buywithrobux": BUY_KEYWORDS | {"robux", "gamepass"},
            "getsystem": RECEIVE_KEYWORDS | BUY_KEYWORDS | SYSTEM_KEYWORDS,
            "sendorderpanel": ORDER_KEYWORDS,
            "list": ORDER_KEYWORDS | {"active", "manage", "list", "פעילות"},
            "vouch": {"vouch", "review", "הוכחה", "דירוג"},
            "vouches": {"vouch", "stats", "reviews", "הוכחות", "דירוג"},
            "poll": {"poll", "vote", "סקר"},
            "editpoll": {"poll", "edit", "סקר", "לערוך"},
            "giveaway": {"giveaway", "winner", "prize", "גיבאווי"},
            "editgiveaway": {"giveaway", "edit", "גיבאווי", "לערוך"},
            "trainbot": {"train", "knowledge", "ai", "אימון", "ללמד"},
            "endtraining": {"train", "resume", "ai", "אימון"},
        }
        return mapping.get(command_name, {command_name.casefold()})

    @staticmethod
    def _ast_dotted_name(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = AIAssistantService._ast_dotted_name(node.value)
            return f"{parent}.{node.attr}" if parent else node.attr
        return ""

    @staticmethod
    def _ast_literal_string(node: ast.AST | None) -> str | None:
        if node is None:
            return None
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        try:
            value = ast.literal_eval(node)
        except (ValueError, SyntaxError):
            return None
        return value if isinstance(value, str) else None

    @staticmethod
    def _ast_keyword_string(call: ast.Call, key: str) -> str | None:
        for keyword in call.keywords:
            if keyword.arg == key:
                return AIAssistantService._ast_literal_string(keyword.value)
        return None

    def _build_live_ai_unavailable_answer(
        self,
        question: str,
        knowledge: Sequence[AIKnowledgeRecord],
        text_sources: Sequence[str],
        *,
        response_profile: ResponseProfile | None,
        image_unprocessed: bool,
        reason: str,
    ) -> str:
        if knowledge or text_sources:
            return self._build_local_answer(
                question,
                knowledge,
                text_sources,
                response_profile=response_profile,
                quota_limited=self._looks_like_quota_error(reason),
                image_unprocessed=image_unprocessed,
            )

        if self._looks_like_quota_error(reason):
            return self._fallback_rate_limited_answer(question, image_only=image_unprocessed)

        if _contains_hebrew(question):
            if image_unprocessed:
                return "עיבוד ה-AI החי לא היה זמין כרגע, ולכן לא הצלחתי לקרוא את התמונה. נסה שוב בעוד כמה רגעים או שלח גם טקסט."
            return "עיבוד ה-AI החי לא היה זמין כרגע. נסה שוב בעוד כמה רגעים."

        if image_unprocessed:
            return "Live AI processing was unavailable right now, so I couldn't read the image. Try again shortly or include text with it."
        return "Live AI processing was unavailable right now. Try again shortly."

    @staticmethod
    def _extract_public_urls(text: str) -> list[str]:
        return list(dict.fromkeys(URL_PATTERN.findall(text)))

    @staticmethod
    def _is_supported_text_attachment(attachment: discord.Attachment) -> bool:
        if attachment.content_type and attachment.content_type.startswith("text/"):
            return True
        return Path(attachment.filename).suffix.casefold() in TEXT_FILE_EXTENSIONS

    @staticmethod
    def _decode_text_bytes(data: bytes) -> str:
        for encoding in ("utf-8", "utf-16", "cp1255", "latin-1"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="ignore")

    @staticmethod
    def _strip_html(raw_html: str) -> str:
        without_scripts = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw_html)
        without_tags = re.sub(r"(?s)<[^>]+>", " ", without_scripts)
        unescaped = html_lib.unescape(without_tags)
        return re.sub(r"\s+", " ", unescaped).strip()

    @staticmethod
    def _looks_like_quota_error(message: str) -> bool:
        lowered = message.casefold()
        return "quota" in lowered or "rate limit" in lowered or "429" in lowered or "exceeded" in lowered

    @staticmethod
    def _truncate(value: str, limit: int) -> str:
        cleaned = value.strip()
        if len(cleaned) <= limit:
            return cleaned
        return f"{cleaned[:limit].rstrip()}..."

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

    @staticmethod
    def _fallback_rate_limited_answer(question: str, *, image_only: bool = False) -> str:
        if _contains_hebrew(question):
            if image_only:
                return "מכסת Gemini כרגע מוגבלת, ולכן אני לא יכול לנתח את התמונה בזמן אמת. נסה שוב בעוד כמה רגעים או שלח גם טקסט מסביר."
            return "מכסת Gemini כרגע מוגבלת. נסה שוב בעוד כמה רגעים, או שלח מידע נוסף בטקסט כדי שאוכל להסתמך יותר על הידע המקומי של הבוט."
        if image_only:
            return "Gemini quota is limited right now, so I can't analyze the image live. Try again shortly or include some text with the screenshot."
        return "Gemini quota is limited right now. Try again shortly, or include more text so I can rely more on the bot's local knowledge."