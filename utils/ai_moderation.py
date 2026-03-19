import asyncio
import base64
import io
import hashlib
import time
import json
import re
from typing import Dict, List, Optional, Any

from PIL import Image
import discord
from openai import AsyncOpenAI, RateLimitError

from utils.constants import logger, Constants

# Initialize constants
constants = Constants()


class AIModerationService:
    """AI-powered moderation service using OpenAI and OpenRouter with safer rate limiting."""

    def __init__(self):
        self.openai_api_key = constants.openai_api_key()
        self.openrouter_api_key = constants.openrouter_api_key()

        # Initialize async clients
        self.openai_client = AsyncOpenAI(api_key=self.openai_api_key) if self.openai_api_key else None

        self.openrouter_client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.openrouter_api_key,
        ) if self.openrouter_api_key else None

        # Report channel configuration
        self.report_channel_id = constants.report_channel_id()

        # Moderation categories from OpenAI Omni moderation
        self.moderation_categories = [
            "sexual",
            "sexual_minors",
            "harassment",
            "harassment_threatening",
            "hate",
            "hate_threatening",
            "illicit",
            "illicit_violent",
            "self_harm",
            "self_harm_intent",
            "self_harm_instructions",
            "violence",
            "violence_graphic",
        ]

        # Optimization configurations
        self.cache = {}
        self.cache_ttl = 300  # 5 minutes
        self.max_concurrent_requests = 2
        self.semaphore = asyncio.Semaphore(self.max_concurrent_requests)
        self.request_spacing = 1.0  # 1 second between requests
        self.last_request_time = 0.0
        self.request_lock = asyncio.Lock()

        self.circuit_breaker_threshold = 5
        self.circuit_breaker_timeout = 60
        self.failure_count = 0
        self.circuit_breaker_open = False
        self.circuit_breaker_reset_time = 0.0

        # Image processing limits
        self.max_image_size = 1024
        self.max_images_per_message = 10
        self.max_content_length = 4000

        # Confidence thresholds
        self.min_confidence_threshold = 0.7
        self.high_confidence_threshold = 0.9
        self.category_score_threshold = 0.7

    async def scan_message(self, message: discord.Message) -> Dict[str, Any]:
        """Comprehensive message scanning using AI moderation with batching and optimizations."""
        try:
            if not self._should_scan_message(message):
                return self._create_skip_result(message, "Message skipped by filters")

            if self.circuit_breaker_open:
                if time.time() < self.circuit_breaker_reset_time:
                    return self._create_skip_result(message, "Circuit breaker open")
                self.circuit_breaker_open = False
                self.failure_count = 0

            message_type = self._detect_message_type(message.content)

            scan_data = {
                "message_id": message.id,
                "user_id": message.author.id,
                "guild_id": message.guild.id,
                "channel_id": message.channel.id,
                "message_type": message_type,
                "content": message.content,
                "attachments": [],
                "timestamp": message.created_at.isoformat(),
            }

            cache_key = self._generate_cache_key(message.content, message.attachments)
            cached_result = self._get_from_cache(cache_key)
            if cached_result:
                logger.debug(f"Using cached result for message {message.id}")
                cached_result.update(scan_data)
                return cached_result

            async with self.semaphore:
                batch_analysis = await self._analyze_content_batch(message.content, message.attachments)
                scan_data.update(batch_analysis)

            text_flagged = scan_data.get("text_analysis", {}).get("flagged", False)
            image_flagged = any(img.get("flagged", False) for img in scan_data.get("image_analysis", []))
            high_confidence_categories = scan_data.get("text_analysis", {}).get("high_confidence_categories", [])

            # Only do second-pass AI confidence when moderation looks strong
            if high_confidence_categories or image_flagged:
                scan_data["ai_confidence"] = await self._get_ai_confidence(scan_data)
            else:
                scan_data["ai_confidence"] = {
                    "confidence": 0.0,
                    "reasoning": "Skipped secondary AI confidence check",
                    "recommended_action": "ignore",
                    "context_notes": "Secondary AI check avoided to reduce rate limit pressure",
                }

            should_flag = self._should_flag_content(scan_data)
            scan_data["should_flag"] = should_flag

            self._store_in_cache(cache_key, scan_data)
            return scan_data

        except Exception as e:
            logger.error(f"Error scanning message: {e}")
            self._handle_api_failure()
            return {
                "message_id": message.id,
                "user_id": message.author.id,
                "guild_id": message.guild.id,
                "channel_id": message.channel.id,
                "error": str(e),
                "should_flag": False,
            }

    def _detect_message_type(self, content: str) -> str:
        """Detect message type based on content patterns."""
        content_lower = content.lower()

        if any(pattern in content_lower for pattern in ["forwarded message", "fwd:", "forwarded:", "from:"]):
            return "forwarded"
        if any(pattern in content_lower for pattern in ["automod blocked", "blocked by automod", "automod filter"]):
            return "automod_blocked"
        return "normal"

    def _detect_roleplay_context(self, content: str) -> Dict[str, Any]:
        """Detect if message appears to be roleplay content with comprehensive analysis."""
        content_lower = content.lower()

        roleplay_indicators = [
            "((", "))", "[*", "*]", "[ooc", "[ic", "[out of character", "[in character",
            "{{", "}}", "{{{", "}}}", "[rp", "[roleplay", "[char", "[character",
            "*", "says", "whispers", "shouts", "thinks", "narrates", "speaks", "mumbles",
            "exclaims", "declares", "announces", "states", "responds", "replies",
            "actions", "does", "performs", "executes", "carries out",
            "as", "playing as", "character", "rp", "roleplay", "role play",
            "story", "narrative", "plot", "scene", "setting", "scenario",
            "character name", "char name", "playing", "acts", "acting",
            "erlc", "emergency response", "liberty county", "police", "ems", "fire", "dispatch",
            "officer", "sergeant", "lieutenant", "captain", "chief", "deputy", "sheriff",
            "paramedic", "emt", "firefighter", "responder", "unit", "patrol", "beat",
            "10-4", "10-20", "10-8", "10-7", "copy", "roger", "over", "out",
            "scene", "incident", "call", "response", "backup", "code", "status",
            "suspect", "victim", "witness", "perp", "civ", "civilian",
            "arrest", "detain", "cuff", "miranda", "rights", "booking",
            "medical", "injury", "wounded", "hurt", "bleeding", "conscious",
            "vehicle", "car", "truck", "ambulance", "patrol car", "cruiser",
            "location", "address", "street", "avenue", "road", "highway",
            "abusing powers", "power abuse", "admin abuse", "staff abuse",
            "kicked", "banned", "warned", "punished", "disciplined",
            "server", "game", "simulation", "sim", "larp", "larping",
            "in-game", "ingame", "ic", "ooc", "in character", "out of character",
            "secure", "securing", "assets", "facility", "building", "compound",
            "mission", "operation", "assignment", "task", "objective",
            "team", "squad", "unit", "division", "department", "agency",
            "protocol", "procedure", "standard", "operating", "sop",
            "radio", "comms", "communication", "channel", "frequency",
            "report", "reporting", "status", "update", "briefing", "debrief",
            "investigation", "investigate", "evidence", "witness", "testimony",
            "court", "trial", "hearing", "judge", "jury", "verdict",
            "prison", "jail", "cell", "inmate", "prisoner", "detainee",
            "bail", "bond", "release", "parole", "probation",
            "crime", "criminal", "offense", "violation", "infraction",
            "fine", "penalty", "sentence", "punishment", "discipline",
        ]

        roleplay_violence = [
            "attacks", "strikes", "hits", "fights", "battles", "combat",
            "sword", "weapon", "spell", "magic", "dragon", "monster",
            "adventure", "quest", "dungeon", "castle", "kingdom",
            "shoot", "shot", "fired", "gun", "weapon", "taser", "baton",
            "pursuit", "chase", "chasing", "fleeing", "escape", "run",
            "threat", "threaten", "threatening", "danger", "dangerous",
            "hostage", "robbery", "theft", "stolen", "stole", "steal",
            "assault", "assaulted", "assaulting", "battery", "battered",
            "resisting", "resistance", "struggle", "struggling", "fight",
            "secure", "securing", "breach", "breached", "intrusion",
            "defend", "defending", "defense", "protect", "protecting",
            "guard", "guarding", "patrol", "patrolling", "watch", "watching",
        ]

        roleplay_patterns = [
            r"\b(10-\d+)\b",
            r"\b(unit|patrol|beat)\s+\d+",
            r"\b(responding|en route|on scene|clear)\b",
            r"\b(copy|roger|over|out)\b",
            r"\b(dispatch|control|central)\b",
            r"\b(abusing|abuse)\s+(powers|admin|staff)\b",
            r"\b(kicked|banned|warned)\s+(by|from)\b",
            r"\b(was|were)\s+(kicked|banned|warned|punished)\b",
            r"\*[^*]+\*",
            r"\[[^\]]+\]",
            r"\b(character|char)\s+\w+",
            r"\b(playing|as)\s+\w+",
            r"\b(in|out)\s+(character|char)",
            r"\b(roleplay|rp)\b",
            r"\b(server|game|simulation)\b",
            r"\b(mission|operation|assignment)\b",
            r"\b(secure|securing|assets|facility)\b",
            r"\b(report|reporting|status|update)\b",
        ]

        roleplay_score = sum(1 for indicator in roleplay_indicators if indicator in content_lower)
        violence_score = sum(1 for indicator in roleplay_violence if indicator in content_lower)
        pattern_matches = sum(1 for pattern in roleplay_patterns if re.search(pattern, content_lower))

        context_analysis = {
            "has_asterisks": "*" in content,
            "has_brackets": "[" in content and "]" in content,
            "has_parentheses": "(" in content and ")" in content,
            "has_quotes": '"' in content or "'" in content,
            "has_dialogue_indicators": any(ind in content_lower for ind in ["says", "whispers", "shouts", "thinks", "narrates"]),
            "has_character_references": any(ind in content_lower for ind in ["character", "char", "playing as", "as"]),
            "has_gaming_terms": any(ind in content_lower for ind in ["server", "game", "simulation", "ic", "ooc", "roleplay"]),
            "has_emergency_terms": any(ind in content_lower for ind in ["police", "ems", "fire", "dispatch", "officer", "unit"]),
            "has_action_verbs": any(ind in content_lower for ind in ["secure", "investigate", "arrest", "patrol", "respond"]),
        }

        is_roleplay = (
            roleplay_score >= 1
            or pattern_matches >= 1
            or context_analysis["has_asterisks"]
            or context_analysis["has_brackets"]
            or (context_analysis["has_dialogue_indicators"] and context_analysis["has_character_references"])
            or (context_analysis["has_gaming_terms"] and (roleplay_score >= 1 or violence_score >= 1))
            or (context_analysis["has_emergency_terms"] and context_analysis["has_action_verbs"])
        )

        return {
            "is_roleplay": is_roleplay,
            "roleplay_score": roleplay_score,
            "violence_score": violence_score,
            "pattern_matches": pattern_matches,
            "indicators_found": [ind for ind in roleplay_indicators if ind in content_lower],
            "context_analysis": context_analysis,
            "confidence_factors": {
                "strong_indicators": roleplay_score >= 3,
                "pattern_matches": pattern_matches >= 1,
                "formatting_indicators": context_analysis["has_asterisks"] or context_analysis["has_brackets"],
                "dialogue_indicators": context_analysis["has_dialogue_indicators"],
                "gaming_context": context_analysis["has_gaming_terms"],
                "emergency_context": context_analysis["has_emergency_terms"],
            },
        }

    def _should_scan_message(self, message: discord.Message) -> bool:
        """Early exit checks to avoid unnecessary processing."""
        if message.author.bot:
            return False

        if not message.content and not message.attachments:
            return False

        if message.content and len(message.content) > self.max_content_length:
            logger.debug(f"Skipping message {message.id}: content too long ({len(message.content)} chars)")
            return False

        image_count = sum(
            1 for att in message.attachments
            if att.content_type and att.content_type.startswith("image/")
        )
        if image_count > self.max_images_per_message:
            logger.debug(f"Skipping message {message.id}: too many images ({image_count})")
            return False

        return True

    def _create_skip_result(self, message: discord.Message, reason: str) -> Dict[str, Any]:
        """Create a result for skipped messages."""
        return {
            "message_id": message.id,
            "user_id": message.author.id,
            "guild_id": message.guild.id,
            "channel_id": message.channel.id,
            "skip_reason": reason,
            "should_flag": False,
        }

    def _generate_cache_key(self, content: str, attachments: List[discord.Attachment]) -> str:
        """Generate a cache key for the message content."""
        key_data = content or ""
        for att in attachments:
            if att.content_type and att.content_type.startswith("image/"):
                key_data += f"|{att.url}"
        return hashlib.md5(key_data.encode()).hexdigest()

    def _get_from_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Get result from cache if valid."""
        if cache_key in self.cache:
            cached_data, timestamp = self.cache[cache_key]
            if time.time() - timestamp < self.cache_ttl:
                return cached_data.copy()
            del self.cache[cache_key]
        return None

    def _store_in_cache(self, cache_key: str, data: Dict[str, Any]) -> None:
        """Store result in cache."""
        if not data.get("should_flag", False):
            self.cache[cache_key] = (data.copy(), time.time())
            if len(self.cache) > 1000:
                self._cleanup_cache()

    def _cleanup_cache(self) -> None:
        """Remove expired cache entries."""
        current_time = time.time()
        expired_keys = [
            key for key, (_, timestamp) in self.cache.items()
            if current_time - timestamp > self.cache_ttl
        ]
        for key in expired_keys:
            del self.cache[key]

    def _handle_api_failure(self) -> None:
        """Handle API failures for circuit breaker."""
        self.failure_count += 1
        if self.failure_count >= self.circuit_breaker_threshold:
            self.circuit_breaker_open = True
            self.circuit_breaker_reset_time = time.time() + self.circuit_breaker_timeout
            logger.warning(f"Circuit breaker opened after {self.failure_count} failures")

    def _handle_api_success(self) -> None:
        """Reset failure counter after successful API call."""
        self.failure_count = 0
        self.circuit_breaker_open = False

    async def _rate_limit_delay(self) -> None:
        """Add spacing between outgoing AI requests."""
        async with self.request_lock:
            current_time = time.time()
            time_since_last = current_time - self.last_request_time
            if time_since_last < self.request_spacing:
                await asyncio.sleep(self.request_spacing - time_since_last)
            self.last_request_time = time.time()

    async def _call_openai_moderation_with_retry(self, input_items, retries: int = 5):
        """Call OpenAI moderation with retry/backoff."""
        delay = 2.0

        for attempt in range(retries):
            try:
                await self._rate_limit_delay()
                result = await self.openai_client.moderations.create(
                    model="omni-moderation-latest",
                    input=input_items,
                )
                self._handle_api_success()
                return result

            except RateLimitError as e:
                logger.warning(
                    f"OpenAI moderation rate limited (attempt {attempt + 1}/{retries}): {e}"
                )
                if attempt == retries - 1:
                    raise
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

            except Exception:
                raise

    async def _call_openrouter_with_retry(self, messages, retries: int = 4):
        """Call OpenRouter with retry/backoff."""
        delay = 2.0

        for attempt in range(retries):
            try:
                await self._rate_limit_delay()
                result = await self.openrouter_client.chat.completions.create(
                    extra_headers={
                        "HTTP-Referer": "https://EPN.jadyn.au",
                        "X-Title": "EPN Bot Moderation",
                    },
                    model="google/gemini-2.5-flash",
                    messages=messages,
                    max_tokens=300,
                    temperature=0.1,
                )
                self._handle_api_success()
                return result

            except Exception as e:
                if "429" in str(e) or "Too Many Requests" in str(e):
                    logger.warning(
                        f"OpenRouter rate limited (attempt {attempt + 1}/{retries}): {e}"
                    )
                    if attempt == retries - 1:
                        raise
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 30)
                else:
                    raise

    async def _analyze_content_batch(self, content: str, attachments: List[discord.Attachment]) -> Dict[str, Any]:
        """Analyze both text and images in a single batched API call with optimizations."""
        if not self.openai_client:
            return {
                "text_analysis": {"flagged": False, "categories": {}},
                "image_analysis": [],
                "attachments": [],
            }

        try:
            input_items = []

            if content:
                truncated_content = content[:self.max_content_length]
                input_items.append({"type": "text", "text": truncated_content})

            image_analyses = []
            attachment_urls = []
            processed_attachments = []

            for attachment in attachments:
                if len(processed_attachments) >= self.max_images_per_message:
                    logger.debug(
                        f"Reached max images limit ({self.max_images_per_message}), skipping remaining"
                    )
                    break

                if not attachment.content_type or not attachment.content_type.startswith("image/"):
                    continue

                try:
                    image_result = await self._process_image_async(attachment)
                    if image_result:
                        input_items.append(image_result["input_item"])
                        attachment_urls.append(attachment.url)
                        processed_attachments.append(attachment)

                except Exception as e:
                    logger.error(f"Error processing image {attachment.filename}: {e}")
                    image_analyses.append(
                        {
                            "filename": attachment.filename,
                            "url": attachment.url,
                            "error": str(e),
                            "flagged": False,
                        }
                    )

            if not input_items:
                return {
                    "text_analysis": {"flagged": False, "categories": {}},
                    "image_analysis": image_analyses,
                    "attachments": attachment_urls,
                }

            result = await self._call_openai_moderation_with_retry(input_items)

            text_analysis = {"flagged": False, "categories": {}}
            image_analysis_results = list(image_analyses)

            for i, moderation_result in enumerate(result.results):
                if i == 0 and content:
                    text_analysis = self._process_omni_moderation(moderation_result)
                else:
                    image_result = self._process_omni_moderation(moderation_result)
                    attachment_index = i - (1 if content else 0)
                    if 0 <= attachment_index < len(processed_attachments):
                        attachment = processed_attachments[attachment_index]
                        image_result.update(
                            {
                                "filename": attachment.filename,
                                "url": attachment.url,
                            }
                        )
                    image_analysis_results.append(image_result)

            return {
                "text_analysis": text_analysis,
                "image_analysis": image_analysis_results,
                "attachments": attachment_urls,
            }

        except Exception as e:
            logger.error(f"Error in batch content analysis: {e}")
            self._handle_api_failure()
            return {
                "text_analysis": {"flagged": False, "categories": {}},
                "image_analysis": [],
                "attachments": [],
            }

    async def _process_image_async(self, attachment: discord.Attachment) -> Optional[Dict[str, Any]]:
        """Process a single image asynchronously with optimizations."""
        try:
            image_data = await attachment.read()

            if len(image_data) > 10 * 1024 * 1024:
                logger.debug(f"Skipping large image {attachment.filename}: {len(image_data)} bytes")
                return None

            image = Image.open(io.BytesIO(image_data))

            if image.width > self.max_image_size or image.height > self.max_image_size:
                ratio = min(self.max_image_size / image.width, self.max_image_size / image.height)
                new_size = (int(image.width * ratio), int(image.height * ratio))
                image = image.resize(new_size, Image.Resampling.LANCZOS)

            buffer = io.BytesIO()

            original_mode = image.mode
            if image.mode in ("RGBA", "LA", "P"):
                image = image.convert("RGB")
                image.save(buffer, format="JPEG", quality=85, optimize=True)
                mime_type = "image/jpeg"
            else:
                image.save(buffer, format="PNG", optimize=True)
                mime_type = "image/png"

            image_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

            return {
                "input_item": {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{image_b64}"
                    },
                },
                "filename": attachment.filename,
                "url": attachment.url,
                "original_mode": original_mode,
            }

        except Exception as e:
            logger.error(f"Error processing image {attachment.filename}: {e}")
            return None

    async def _get_ai_confidence(self, scan_data: Dict[str, Any]) -> Dict[str, Any]:
        """Get AI confidence score using OpenRouter with optimizations."""
        if not self.openrouter_client:
            return {
                "confidence": 0.0,
                "reasoning": "OpenRouter API not configured",
                "recommended_action": "ignore",
                "context_notes": "No OpenRouter client configured",
            }

        try:
            if self._should_skip_ai_confidence(scan_data):
                return {
                    "confidence": 0.0,
                    "reasoning": "Skipped - obvious content",
                    "recommended_action": "ignore",
                    "context_notes": "Skipped by pre-check",
                }

            content_parts = []

            if scan_data.get("content"):
                content = scan_data["content"][:1000]
                content_parts.append(f"Text: {content}")

                roleplay_context = self._detect_roleplay_context(content)
                if roleplay_context["is_roleplay"]:
                    content_parts.append(
                        f"ROLEPLAY CONTEXT DETECTED: {roleplay_context['indicators_found']}"
                    )
                    content_parts.append(
                        f"Roleplay Score: {roleplay_context['roleplay_score']}, "
                        f"Violence Score: {roleplay_context['violence_score']}, "
                        f"Pattern Matches: {roleplay_context.get('pattern_matches', 0)}"
                    )

                    context_analysis = roleplay_context.get("context_analysis", {})
                    confidence_factors = roleplay_context.get("confidence_factors", {})

                    formatting_indicators = []
                    if context_analysis.get("has_asterisks"):
                        formatting_indicators.append("asterisks (*)")
                    if context_analysis.get("has_brackets"):
                        formatting_indicators.append("brackets ([])")
                    if context_analysis.get("has_parentheses"):
                        formatting_indicators.append("parentheses (())")
                    if context_analysis.get("has_quotes"):
                        formatting_indicators.append("quotes")
                    if formatting_indicators:
                        content_parts.append(f"ROLEPLAY FORMATTING: {', '.join(formatting_indicators)}")

                    context_types = []
                    if context_analysis.get("has_dialogue_indicators"):
                        context_types.append("dialogue")
                    if context_analysis.get("has_character_references"):
                        context_types.append("character references")
                    if context_analysis.get("has_gaming_terms"):
                        context_types.append("gaming context")
                    if context_analysis.get("has_emergency_terms"):
                        context_types.append("emergency response")
                    if context_analysis.get("has_action_verbs"):
                        context_types.append("action verbs")
                    if context_types:
                        content_parts.append(f"ROLEPLAY CONTEXT TYPES: {', '.join(context_types)}")

                    strong_factors = []
                    if confidence_factors.get("strong_indicators"):
                        strong_factors.append("strong roleplay indicators")
                    if confidence_factors.get("pattern_matches"):
                        strong_factors.append("pattern matches")
                    if confidence_factors.get("formatting_indicators"):
                        strong_factors.append("roleplay formatting")
                    if confidence_factors.get("dialogue_indicators"):
                        strong_factors.append("dialogue indicators")
                    if confidence_factors.get("gaming_context"):
                        strong_factors.append("gaming context")
                    if confidence_factors.get("emergency_context"):
                        strong_factors.append("emergency response context")
                    if strong_factors:
                        content_parts.append(f"STRONG ROLEPLAY FACTORS: {', '.join(strong_factors)}")

                    erlc_indicators = [
                        "erlc", "emergency response", "police", "ems", "fire",
                        "dispatch", "abusing powers", "kicked", "banned",
                        "warned", "secure", "securing", "assets",
                    ]
                    erlc_found = [ind for ind in erlc_indicators if ind in content.lower()]
                    if erlc_found:
                        content_parts.append(
                            f"ERLC ROLEPLAY DETECTED: {erlc_found} - This is likely emergency response roleplay content"
                        )

                    content_parts.append(
                        "ROLEPLAY GUIDELINES: This content appears to be roleplay and should be "
                        "evaluated with roleplay context in mind. Consider if the content would be "
                        "acceptable in a roleplay gaming scenario."
                    )

            if scan_data.get("text_analysis", {}).get("categories"):
                categories = scan_data["text_analysis"]["categories"]
                content_parts.append(f"OpenAI Categories: {categories}")

            if scan_data.get("image_analysis"):
                for img in scan_data["image_analysis"][:3]:
                    if img.get("categories"):
                        content_parts.append(f"Image {img.get('filename', 'unknown')}: {img['categories']}")

            content_text = "\n".join(content_parts)

            messages = [
                {
                    "role": "system",
                    "content": """You are an AI moderation assistant for a roleplay gaming server. Analyze the provided content and determine if it contains harmful, inappropriate, or NSFW content that would be problematic in a roleplay context.

IMPORTANT CONTEXT:
- This is a roleplay server where players may engage in character interactions, combat scenarios, and dramatic storytelling
- Consider the context: is this clearly roleplay/character dialogue vs real threats or harassment?
- Distinguish between in-character threats (acceptable in roleplay) and out-of-character harassment (not acceptable)
- Look for clear indicators of roleplay context like character names, roleplay brackets, or story context
- Be more lenient with violence/threats that appear to be part of roleplay scenarios
- Only flag content that would be genuinely harmful or inappropriate even in a roleplay context

ROLEPLAY DETECTION GUIDELINES:
- When you see "ROLEPLAY CONTEXT DETECTED" with indicators, this is STRONG evidence of roleplay
- Formatting indicators (asterisks, brackets, parentheses) are common roleplay markers
- Dialogue indicators (says, whispers, shouts, thinks) suggest character speech
- Gaming context (server, game, simulation, IC/OOC) indicates roleplay environment
- Emergency response context (police, EMS, fire, dispatch) is often roleplay
- Action verbs (secure, investigate, arrest, patrol) in context suggest roleplay scenarios

SPECIAL CONSIDERATIONS FOR EMERGENCY RESPONSE ROLEPLAY (ERLC):
- Emergency response roleplay (police, EMS, fire, dispatch) often involves discussions of:
  * Admin abuse reports ("abusing powers", "power abuse", "staff abuse")
  * Punishment reports ("was kicked", "got banned", "was warned")
  * Police/emergency terminology ("10-4", "copy", "roger", "unit", "patrol")
  * Incident reports and roleplay scenarios
  * Security operations ("secure assets", "facility breach", "investigation")
- These discussions are NORMAL roleplay content and should be IGNORED unless they contain genuine harassment
- Focus on distinguishing between roleplay admin reports vs real harassment complaints
- ERLC content about "abusing powers" or being "kicked" is typically roleplay, not real abuse
- Security and investigation language is common in roleplay scenarios

ANALYSIS REQUIREMENTS:
- Pay close attention to ROLEPLAY CONTEXT DETECTED sections
- Consider all formatting, context types, and confidence factors provided
- If multiple roleplay indicators are present, heavily weight this in your analysis
- Remember: roleplay content should be evaluated differently than real-world content
- Only flag content that would be genuinely harmful even in a roleplay context

CRITICAL INSTRUCTION FOR ROLEPLAY CONTENT:
- If you detect ANY roleplay context indicators (formatting, dialogue, gaming terms, emergency response, etc.), you MUST return "ignore" as the recommended_action
- Roleplay content should NEVER be flagged for review, regardless of the content
- Set confidence to 0.0 for roleplay content
- Only use "flag" or "review" for genuine real-world harassment or harmful content

Respond with a JSON object containing:
{
  "confidence": 0.0-1.0,
  "reasoning": "detailed explanation of your analysis, including roleplay context considerations and specific indicators found",
  "recommended_action": "flag|review|ignore",
  "context_notes": "specific roleplay context indicators, formatting markers, or gaming context that influenced your decision"
}""",
                },
                {
                    "role": "user",
                    "content": f"Analyze this content for moderation in a roleplay gaming context:\n\n{content_text}",
                },
            ]

            response = await self._call_openrouter_with_retry(messages)
            raw_content = response.choices[0].message.content or ""

            try:
                content_clean = raw_content.strip()
                if content_clean.startswith("```json"):
                    content_clean = content_clean[7:]
                if content_clean.endswith("```"):
                    content_clean = content_clean[:-3]
                content_clean = content_clean.strip()

                json_match = re.search(r"\{.*\}", content_clean, re.DOTALL)
                json_str = json_match.group(0) if json_match else content_clean
                confidence_data = json.loads(json_str)

                if not isinstance(confidence_data.get("confidence"), (int, float)):
                    confidence_data["confidence"] = 0.5
                confidence_data["confidence"] = max(0.0, min(1.0, float(confidence_data["confidence"])))

                confidence_data.setdefault("reasoning", "No reasoning provided")
                confidence_data.setdefault("recommended_action", "review")
                confidence_data.setdefault("context_notes", "No context notes provided")

                context_notes = confidence_data.get("context_notes", "").lower()
                reasoning = confidence_data.get("reasoning", "")

                erlc_indicators = [
                    "erlc", "emergency response", "police", "ems", "fire",
                    "dispatch", "abusing powers", "kicked", "banned",
                    "warned", "admin abuse", "power abuse",
                ]
                is_erlc_roleplay = any(
                    indicator in context_notes or indicator in reasoning.lower()
                    for indicator in erlc_indicators
                )

                if (
                    any(indicator in context_notes for indicator in ["roleplay", "character", "in-character", "ic", "story", "narrative"])
                    or is_erlc_roleplay
                ):
                    confidence_data["confidence"] = 0.0
                    confidence_data["recommended_action"] = "ignore"
                    if is_erlc_roleplay:
                        confidence_data["reasoning"] += " [FORCED IGNORE - ERLC roleplay detected]"
                        logger.debug("Forced ignore for ERLC roleplay context")
                    else:
                        confidence_data["reasoning"] += " [FORCED IGNORE - roleplay context detected]"
                        logger.debug("Forced ignore for roleplay context")

                if confidence_data["recommended_action"] == "ignore":
                    confidence_data["confidence"] = 0.0
                    confidence_data["reasoning"] += " [Ignored per AI recommendation]"

                return confidence_data

            except json.JSONDecodeError:
                confidence = 0.5
                raw_lower = raw_content.lower()

                if "high" in raw_lower and "roleplay" not in raw_lower:
                    confidence = 0.8
                elif "low" in raw_lower or "roleplay" in raw_lower:
                    confidence = 0.2
                elif "ignore" in raw_lower:
                    confidence = 0.0

                reasoning = raw_content.replace("```json", "").replace("```", "").strip()
                if reasoning.startswith("{"):
                    if '"reasoning":' in reasoning:
                        try:
                            reasoning_start = reasoning.find('"reasoning":') + 12
                            reasoning_end = reasoning.find('"', reasoning_start + 1)
                            if reasoning_end > reasoning_start:
                                reasoning = reasoning[reasoning_start:reasoning_end]
                        except Exception:
                            reasoning = "Analysis completed with fallback parsing"
                    else:
                        reasoning = "Analysis completed with fallback parsing"

                return {
                    "confidence": confidence,
                    "reasoning": reasoning[:200] if len(reasoning) > 200 else reasoning,
                    "recommended_action": "review",
                    "context_notes": "JSON parsing failed, using fallback analysis",
                }

        except Exception as e:
            logger.error(f"Error getting AI confidence: {e}")
            self._handle_api_failure()
            return {
                "confidence": 0.0,
                "reasoning": str(e),
                "recommended_action": "review",
                "context_notes": "AI confidence request failed",
            }

    def _should_skip_ai_confidence(self, scan_data: Dict[str, Any]) -> bool:
        """Determine if we should skip AI confidence analysis for obvious cases."""
        text_flagged = scan_data.get("text_analysis", {}).get("flagged", False)
        image_flagged = any(img.get("flagged", False) for img in scan_data.get("image_analysis", []))

        if not text_flagged and not image_flagged:
            return True

        content = scan_data.get("content", "")
        if len(content) < 10 and not image_flagged:
            return True

        return False

    def _process_openai_moderation(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Process OpenAI moderation API response."""
        try:
            moderation = result["results"][0]

            categories = {}
            flagged_categories = []

            for category in self.moderation_categories:
                if category in moderation["categories"]:
                    categories[category] = moderation["categories"][category]
                    if moderation["categories"][category]:
                        flagged_categories.append(category)

            return {
                "flagged": moderation["flagged"],
                "categories": categories,
                "flagged_categories": flagged_categories,
                "scores": moderation["category_scores"],
            }

        except Exception as e:
            logger.error(f"Error processing OpenAI moderation: {e}")
            return {"flagged": False, "categories": {}, "flagged_categories": []}

    def _process_omni_moderation(self, moderation_result) -> Dict[str, Any]:
        """Process OpenAI Omni moderation API response with confidence thresholds."""
        try:
            categories = {}
            flagged_categories = []
            high_confidence_categories = []

            categories_dict = {}
            scores_dict = {}

            if hasattr(moderation_result, "categories"):
                categories_dict = moderation_result.categories
            if hasattr(moderation_result, "category_scores"):
                scores_dict = moderation_result.category_scores

            if not categories_dict and hasattr(moderation_result, "model_dump"):
                data = moderation_result.model_dump()
                categories_dict = data.get("categories", {})
                scores_dict = data.get("category_scores", {})

            for category in self.moderation_categories:
                category_value = None
                category_score = 0.0

                if hasattr(categories_dict, category):
                    category_value = getattr(categories_dict, category)
                elif isinstance(categories_dict, dict):
                    category_value = categories_dict.get(category)

                if hasattr(scores_dict, category):
                    category_score = getattr(scores_dict, category, 0.0)
                elif isinstance(scores_dict, dict):
                    category_score = scores_dict.get(category, 0.0)

                if category_value and category_score >= self.category_score_threshold:
                    categories[category] = category_value
                    flagged_categories.append(category)

                    if category_score >= self.high_confidence_threshold:
                        high_confidence_categories.append(category)

            original_flagged = moderation_result.flagged if hasattr(moderation_result, "flagged") else False
            confidence_based_flagged = len(flagged_categories) > 0

            logger.debug(f"Final flagged: {confidence_based_flagged}")

            return {
                "flagged": confidence_based_flagged,
                "categories": categories,
                "flagged_categories": flagged_categories,
                "high_confidence_categories": high_confidence_categories,
                "scores": scores_dict,
                "original_flagged": original_flagged,
                "confidence_filtered": original_flagged != confidence_based_flagged,
            }

        except Exception as e:
            logger.error(f"Error processing Omni moderation: {e}")
            return {"flagged": False, "categories": {}, "flagged_categories": []}

    def _should_flag_content(self, scan_data: Dict[str, Any]) -> bool:
        """Determine if content should be flagged for human review."""
        content = scan_data.get("content", "")
        if content:
            roleplay_context = self._detect_roleplay_context(content)
            if roleplay_context["is_roleplay"]:
                logger.debug(
                    f"Skipping roleplay content from flagging: {roleplay_context['indicators_found'][:3]}..."
                )
                return False

        text_analysis = scan_data.get("text_analysis", {})
        if text_analysis.get("flagged"):
            logger.debug(f"Text flagged for review: {text_analysis.get('flagged_categories', [])}")
            return True

        image_analysis = scan_data.get("image_analysis", [])
        for img in image_analysis:
            if img.get("flagged"):
                logger.debug(f"Image flagged for review: {img.get('flagged_categories', [])}")
                return True

        ai_confidence = scan_data.get("ai_confidence", {})
        confidence = ai_confidence.get("confidence", 0.0)
        recommended_action = ai_confidence.get("recommended_action", "review")

        if confidence >= self.min_confidence_threshold:
            logger.debug(f"AI confidence review: {confidence:.3f} (action: {recommended_action})")
            return True

        logger.debug(f"AI confidence too low: {confidence:.3f} < {self.min_confidence_threshold}")

        if confidence < 0.3:
            logger.debug(f"Very low confidence alert ignored: {confidence:.3f} < 0.3")
            return False

        return False

    def configure_confidence_thresholds(
        self,
        min_confidence: float = 0.2,
        high_confidence: float = 0.7,
        category_score: float = 0.3,
    ) -> None:
        """Configure confidence thresholds for human review."""
        self.min_confidence_threshold = min_confidence
        self.high_confidence_threshold = high_confidence
        self.category_score_threshold = category_score

        logger.info(
            f"Updated review thresholds: min={min_confidence}, "
            f"high={high_confidence}, category={category_score}"
        )

    def get_confidence_stats(self) -> Dict[str, Any]:
        """Get current confidence threshold configuration."""
        return {
            "min_confidence_threshold": self.min_confidence_threshold,
            "high_confidence_threshold": self.high_confidence_threshold,
            "category_score_threshold": self.category_score_threshold,
            "cache_size": len(self.cache),
            "circuit_breaker_open": self.circuit_breaker_open,
            "failure_count": self.failure_count,
        }


# Global instance
ai_moderation = AIModerationService()
