from __future__ import annotations

import asyncio
import base64
import html as html_lib
import ipaddress
import json
import re
import unicodedata
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
DEFAULT_MAX_OUTPUT_TOKENS = 220
MULTIMODAL_MAX_OUTPUT_TOKENS = 260
TRAINING_IMAGE_SUMMARY_TOKENS = 320
GEMINI_FALLBACK_MODELS = ("gemini-2.5-flash",)


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

    async def search_knowledge(self, question: str, *, limit: int = MAX_KNOWLEDGE_BLOCKS) -> list[AIKnowledgeRecord]:
        normalized_question = _normalize_text(question)
        if not normalized_question:
            return []

        stored_rows = await self.database.fetchall(
            "SELECT * FROM ai_knowledge_entries ORDER BY created_at DESC LIMIT 500"
        )
        records = [self._map_knowledge(row) for row in stored_rows]
        records.extend(await self._build_builtin_knowledge())

        question_tokens = set(TOKEN_PATTERN.findall(normalized_question))
        if not question_tokens:
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
        return [record for _, record in scored_records[:limit]]

    async def answer_message(self, session: aiohttp.ClientSession, message: discord.Message) -> str:
        question = message.content.strip()
        text_sources = await self._extract_message_text_sources(session, message, store_for_training=False)
        search_text = question or "\n".join(text_sources[:1])
        knowledge = await self.search_knowledge(search_text)
        image_parts = await self._extract_image_parts(message)

        if image_parts or text_sources:
            if not self.settings.gemini_api_key:
                return self._build_local_answer(
                    question,
                    knowledge,
                    text_sources,
                    image_unprocessed=bool(image_parts),
                )

            prompt = self._build_multimodal_prompt(question, knowledge, text_sources, image_attached=bool(image_parts))
            try:
                return await self._call_gemini(
                    session,
                    [{"text": prompt}, *image_parts],
                    max_output_tokens=MULTIMODAL_MAX_OUTPUT_TOKENS,
                )
            except ExternalServiceError as exc:
                if self._looks_like_quota_error(str(exc)):
                    return self._build_local_answer(
                        question,
                        knowledge,
                        text_sources,
                        quota_limited=True,
                        image_unprocessed=bool(image_parts),
                    )
                raise

        if knowledge:
            return self._build_local_answer(question, knowledge, [])

        return self._fallback_unknown_answer(question)

    def _build_multimodal_prompt(
        self,
        question: str,
        knowledge: Sequence[AIKnowledgeRecord],
        text_sources: Sequence[str],
        *,
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
            raise

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
        quota_limited: bool = False,
        image_unprocessed: bool = False,
    ) -> str:
        tokens = set(TOKEN_PATTERN.findall(_normalize_text(question)))
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

        if not lines:
            if image_unprocessed:
                return self._fallback_rate_limited_answer(question, image_only=True)
            return self._fallback_unknown_answer(question)

        if _contains_hebrew(question):
            header = "לפי המידע שהצלחתי לקרוא כרגע:"
            quota_note = "מכסת Gemini כרגע מוגבלת, אז עניתי מתוך המידע המקומי של הבוט בלבד."
            image_note = "לא היה לי כרגע עיבוד תמונה חי, אז הסתמכתי רק על הטקסט והמידע הקיים."
        else:
            header = "Based on the data I could read right now:"
            quota_note = "Gemini quota is limited right now, so I answered only from the bot's local data."
            image_note = "Live image analysis was not available right now, so I relied only on text and existing bot data."

        prefix_parts: list[str] = []
        if quota_limited:
            prefix_parts.append(quota_note)
        if image_unprocessed:
            prefix_parts.append(image_note)
        prefix_parts.append(header)

        body = "\n".join(f"- {self._truncate(line, 220)}" for line in lines[:8])
        return "\n\n".join([" ".join(prefix_parts), body])

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

    def _candidate_models(self) -> list[str]:
        models: list[str] = []
        for candidate in (self.settings.gemini_model, *GEMINI_FALLBACK_MODELS):
            cleaned = candidate.strip()
            if cleaned and cleaned not in models:
                models.append(cleaned)
        return models

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