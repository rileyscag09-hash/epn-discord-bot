import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import re
import aiohttp
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque
from typing import Dict, List, Set, Optional, Union
from unidecode import unidecode
from utils.constants import logger, Constants, EmbedDesign
from utils.staff import StaffUtils
from utils.ai_moderation import ai_moderation
from utils.moderation_reports import get_moderation_report_manager
from utils.security_logger import get_security_logger, SecurityEventType, SecurityEventSeverity
from utils.suspicious_activity_detector import get_suspicious_activity_detector

# Initialize constants
constants = Constants()


class URLCache:
    """Cache for URL threat check results with automatic expiration."""

    def __init__(self):
        self.cache: Dict[str, dict] = {}
        self.expiry_times: Dict[str, datetime] = {}

    def add_result(self, url: str, result: dict, expire_time: str):
        """Add a URL check result to cache with expiration."""
        self.cache[url] = result
        try:
            expire_str = expire_time.replace('Z', '+00:00')
            self.expiry_times[url] = datetime.fromisoformat(expire_str)
        except Exception as e:
            logger.error(f"Error parsing expire time: {e}")
            self.expiry_times[url] = discord.utils.utcnow() + timedelta(hours=1)

    def get_result(self, url: str) -> dict:
        """Get cached result for URL if not expired."""
        if url not in self.cache:
            return None

        try:
            expire_time = self.expiry_times[url]

            if isinstance(expire_time, str):
                try:
                    expire_time = expire_time.replace('Z', '+00:00')
                    expire_time = datetime.fromisoformat(expire_time)
                    self.expiry_times[url] = expire_time
                except Exception as e:
                    logger.error(f"Error parsing expire time for {url}: {e}")
                    self.remove_url(url)
                    return None

            if isinstance(expire_time, datetime) and expire_time.tzinfo is None:
                expire_time = expire_time.replace(tzinfo=timezone.utc)
                self.expiry_times[url] = expire_time

            if discord.utils.utcnow() > expire_time:
                self.remove_url(url)
                return None

        except Exception as e:
            logger.error(f"Error checking expiry for {url}: {e}")
            self.remove_url(url)
            return None

        return self.cache[url]

    def remove_url(self, url: str):
        """Remove URL from cache."""
        self.cache.pop(url, None)
        self.expiry_times.pop(url, None)

    def cleanup_expired(self):
        """Remove all expired entries from cache."""
        current_time = discord.utils.utcnow()
        expired_urls = []

        for url, expire_time in self.expiry_times.items():
            try:
                if isinstance(expire_time, str):
                    try:
                        expire_time = expire_time.replace('Z', '+00:00')
                        expire_time = datetime.fromisoformat(expire_time)
                        self.expiry_times[url] = expire_time
                    except Exception as e:
                        logger.error(f"Error parsing expire time for {url}: {e}")
                        expired_urls.append(url)
                        continue

                if isinstance(expire_time, datetime) and expire_time.tzinfo is None:
                    expire_time = expire_time.replace(tzinfo=timezone.utc)
                    self.expiry_times[url] = expire_time

                if current_time > expire_time:
                    expired_urls.append(url)

            except Exception as e:
                logger.error(f"Error checking expiry for {url}: {e}")
                expired_urls.append(url)

        for url in expired_urls:
            self.remove_url(url)

        if expired_urls:
            logger.info(f"Cleaned up {len(expired_urls)} expired URL cache entries")

    def get_cache_stats(self) -> dict:
        """Get cache statistics."""
        current_time = discord.utils.utcnow()
        expired_count = 0

        for url, expire_time in self.expiry_times.items():
            try:
                if isinstance(expire_time, str):
                    try:
                        expire_time = expire_time.replace('Z', '+00:00')
                        expire_time = datetime.fromisoformat(expire_time)
                        self.expiry_times[url] = expire_time
                    except Exception as e:
                        logger.error(f"Error parsing expire time for {url}: {e}")
                        expired_count += 1
                        continue

                if isinstance(expire_time, datetime) and expire_time.tzinfo is None:
                    expire_time = expire_time.replace(tzinfo=timezone.utc)
                    self.expiry_times[url] = expire_time

                if current_time > expire_time:
                    expired_count += 1

            except Exception as e:
                logger.error(f"Error checking expiry for {url}: {e}")
                expired_count += 1

        return {
            "total_entries": len(self.cache),
            "expired_entries": expired_count
        }


class Events(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.security_logger = get_security_logger(bot)

        # URL cache for threat checking
        self.url_cache = URLCache()

        # Spam detection
        self.message_history: Dict[int, deque] = defaultdict(lambda: deque(maxlen=10))
        self.spam_warnings: Dict[int, int] = defaultdict(int)
        self.spam_cooldowns: Dict[int, datetime] = {}

        # Raid detection
        self.recent_joins: Dict[int, deque] = defaultdict(lambda: deque(maxlen=20))
        self.raid_alerts: Dict[int, datetime] = {}

        # NSFW invite report cooldown to prevent spam
        self.nsfw_invite_report_cooldowns: Dict[int, datetime] = {}
        self.nsfw_invite_report_cooldown_duration = timedelta(minutes=5)

        # NSFW detection
        self.nsfw_keywords = [
            "porn", "sex", "nude", "adult", "xxx", "nsfw", "18+", "+18", "adult content",
            "explicit", "mature", "adult material", "adult entertainment", "🥀", "rose", "flower"
        ]

        # AI Moderation configuration
        self.ai_moderation_enabled = True
        self.scan_forwarded_messages = True
        self.scan_automod_blocked = True
        self.scan_normal_messages = True
        self.moderation_report_manager = None

        for keyword in self.nsfw_keywords:
            normalized = self._normalize_text(keyword)

        self.url_pattern = re.compile(r'https?://[^\s<>"\']+')

    async def _ctx_defer(self, ctx: commands.Context, ephemeral: bool = False):
        """Defer safely for hybrid commands."""
        try:
            if getattr(ctx, "interaction", None):
                if not ctx.interaction.response.is_done():
                    await ctx.interaction.response.defer(ephemeral=ephemeral)
        except Exception as e:
            logger.debug(f"Failed to defer interaction response: {e}")

    async def _ctx_send(
        self,
        ctx: commands.Context,
        content: str = None,
        embed: discord.Embed = None,
        ephemeral: bool = False
    ):
        """Send safely for both prefix and slash/hybrid invocations."""
        try:
            if getattr(ctx, "interaction", None):
                if ctx.interaction.response.is_done():
                    return await ctx.interaction.followup.send(content=content, embed=embed, ephemeral=ephemeral)
                return await ctx.interaction.response.send_message(content=content, embed=embed, ephemeral=ephemeral)

            if content is not None and embed is not None:
                return await ctx.reply(content, embed=embed)
            if embed is not None:
                return await ctx.reply(embed=embed)
            return await ctx.reply(content)
        except Exception:
            if content is not None and embed is not None:
                return await ctx.send(content, embed=embed)
            if embed is not None:
                return await ctx.send(embed=embed)
            return await ctx.send(content)

    def _normalize_text(self, text: str) -> str:
        """Normalize text to resist obfuscation."""
        try:
            ascii_text = unidecode(text).lower()
            return ''.join(ch for ch in ascii_text if ch.isalnum())
        except Exception:
            return text.lower()

    def _check_nsfw_keyword_match(self, text: str, keyword: str) -> bool:
        """Check if a keyword matches in text, with special handling for age-related keywords."""
        text_norm = self._normalize_text(text)
        keyword_norm = self._normalize_text(keyword)

        if keyword in ["18+", "+18"]:
            return keyword.lower() in text.lower()

        return keyword_norm and keyword_norm in text_norm

    def _should_send_nsfw_invite_report(self, user_id: int) -> bool:
        """Check if we should send an NSFW invite report for this user."""
        current_time = discord.utils.utcnow()

        if user_id in self.nsfw_invite_report_cooldowns:
            last_report_time = self.nsfw_invite_report_cooldowns[user_id]
            if current_time - last_report_time < self.nsfw_invite_report_cooldown_duration:
                return False

        self.nsfw_invite_report_cooldowns[user_id] = current_time
        self._cleanup_expired_nsfw_invite_cooldowns()
        return True

    def _cleanup_expired_nsfw_invite_cooldowns(self):
        """Clean up expired NSFW invite report cooldowns."""
        current_time = discord.utils.utcnow()
        expired_users = []

        for user_id, last_report_time in self.nsfw_invite_report_cooldowns.items():
            if current_time - last_report_time >= self.nsfw_invite_report_cooldown_duration:
                expired_users.append(user_id)

        for user_id in expired_users:
            self.nsfw_invite_report_cooldowns.pop(user_id, None)

        if expired_users:
            logger.debug(f"Cleaned up {len(expired_users)} expired NSFW invite report cooldowns")

    async def scan_message_with_ai(self, message: discord.Message) -> bool:
        """Scan message content using AI moderation."""
        try:
            if message.author.bot:
                return True

            if not self.ai_moderation_enabled:
                return True

            scan_result = await ai_moderation.scan_message(message)
            logger.info(f"AI scan result for {message.author.display_name}: {scan_result.get('should_flag', False)}")

            message_type = scan_result.get('message_type', 'normal')
            should_scan = (
                (message_type == 'forwarded' and self.scan_forwarded_messages) or
                (message_type == 'automod_blocked' and self.scan_automod_blocked) or
                (message_type == 'normal' and self.scan_normal_messages)
            )

            if not should_scan:
                logger.debug(f"Skipping AI scan for message type: {message_type}")
                return True

            if scan_result.get('should_flag', False):
                await self.handle_ai_moderation_report(message, scan_result)
                return True

            return True

        except Exception as e:
            logger.error(f"Error scanning message with AI: {e}")
            return True

    async def handle_ai_moderation_report(self, message: discord.Message, scan_result: Dict[str, any]):
        """Handle AI moderation report by sending to report channel."""
        try:
            ai_confidence = scan_result.get('ai_confidence', {})
            confidence = ai_confidence.get('confidence', 0.0)
            reasoning = ai_confidence.get('reasoning', '')

            if confidence < 0.3 or 'skipped - obvious content' in reasoning.lower():
                logger.debug(f"Skipping low confidence report: {confidence:.3f} - {reasoning}")
                return

            should_flag = scan_result.get('should_flag', False)
            if not should_flag:
                logger.debug(f"Content not flagged for report: {message.id}")
                return

            if not self.moderation_report_manager:
                self.moderation_report_manager = get_moderation_report_manager(self.bot)

            report_message = await self.moderation_report_manager.send_moderation_report(scan_result, message)

            if report_message:
                if message.attachments:
                    report_channel = self.bot.get_channel(constants.report_channel_id())
                    if report_channel:
                        await self.moderation_report_manager.send_image_attachments(scan_result, message, report_channel)

                logger.info(
                    f"Sent AI moderation report for message {message.id} from "
                    f"{message.author.display_name} (confidence: {confidence:.3f})"
                )
            else:
                logger.error(f"Failed to send AI moderation report for message {message.id}")

        except Exception as e:
            logger.error(f"Error handling AI moderation report: {e}")

    async def _is_discord_invite_nsfw(self, url: str) -> bool:
        """Run comprehensive checks for Discord invites to determine if they are NSFW."""
        try:
            from urllib.parse import urlparse

            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url

            parsed = urlparse(url)
            original_path = parsed.path or ''
            path_lower = (parsed.path or '').lower()

            invite_code = None
            if original_path.startswith('/invite/'):
                invite_code = original_path.split('/invite/')[-1].split('?')[0]
            elif original_path.startswith('/invites/'):
                invite_code = original_path.split('/invites/')[-1].split('?')[0]
            elif parsed.netloc.lower().endswith('discord.gg'):
                invite_code = original_path.lstrip('/').split('?')[0]

            if not invite_code:
                return False

            try:
                invite = await self.bot.fetch_invite(invite_code)

                if invite.guild and invite.guild.name:
                    for keyword in self.nsfw_keywords:
                        if self._check_nsfw_keyword_match(invite.guild.name, keyword):
                            return True

                if invite.guild and invite.guild.description:
                    for keyword in self.nsfw_keywords:
                        if self._check_nsfw_keyword_match(invite.guild.description, keyword):
                            return True

                if invite.approximate_member_count and invite.approximate_member_count < 5:
                    return True

                for keyword in self.nsfw_keywords:
                    if self._check_nsfw_keyword_match(url, keyword) or self._check_nsfw_keyword_match(path_lower, keyword):
                        return True

                return False

            except discord.NotFound:
                logger.warning(f"Discord invite not found: {invite_code}")
                for keyword in self.nsfw_keywords:
                    if self._check_nsfw_keyword_match(url, keyword) or self._check_nsfw_keyword_match(path_lower, keyword):
                        return True
                return False

            except discord.Forbidden:
                logger.warning(f"Cannot access Discord invite: {invite_code} (forbidden)")
                for keyword in self.nsfw_keywords:
                    if self._check_nsfw_keyword_match(url, keyword) or self._check_nsfw_keyword_match(path_lower, keyword):
                        return True
                return False

        except Exception as e:
            logger.error(f"Error checking Discord invite NSFW status: {e}")
            try:
                for keyword in self.nsfw_keywords:
                    if self._check_nsfw_keyword_match(url, keyword) or self._check_nsfw_keyword_match(path_lower, keyword):
                        return True
            except Exception:
                pass
        return False

    async def check_discord_invite(self, invite_url: str) -> tuple[bool, str]:
        """Check a Discord invite and return (is_nsfw, reason)."""
        try:
            is_nsfw = await self._is_discord_invite_nsfw(invite_url)
            if is_nsfw:
                return True, "Invite appears to contain NSFW or inappropriate content"
            return False, "Invite appears safe"
        except Exception as e:
            logger.error(f"Error checking Discord invite: {e}")
            return False, "Failed to check invite"

    async def check_nsfw_links(self, content: str) -> tuple[bool, list]:
        """Check if content contains NSFW links using Google Web Risk API."""
        urls = self.url_pattern.findall(content)
        malicious_urls = []

        self.url_cache.cleanup_expired()

        for url in urls:
            url = url.strip()
            if not url or len(url) < 10:
                continue

            url = url.rstrip('.,;:!?')

            if not url.startswith(('http://', 'https://')):
                continue

            if any(skip in url.lower() for skip in ['webrisk.googleapis.com', 'localhost', '127.0.0.1']):
                continue

            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                host = (parsed.netloc or '').lower()
                path = (parsed.path or '').lower()

                safe_hosts = {
                    'discord.com',
                    'discordapp.com',
                    'cdn.discordapp.com',
                    'media.discordapp.net',
                    'images-ext-1.discordapp.net',
                    'images-ext-2.discordapp.net',
                    'medal.tv',
                    'streamable.com',
                    'vm.tiktok.com',
                    'tiktok.com',
                    'tenor.com',
                }

                is_tenor = host == 'tenor.com' or host.endswith('.tenor.com')

                is_discord_invite = (
                    host == 'discord.gg' or
                    host.endswith('.discord.gg') or
                    (host in {'discord.com', 'discordapp.com'} and (path.startswith('/invite/') or path.startswith('/invites/')))
                )

                is_safe_discord_resource = (host in safe_hosts) and not is_discord_invite

                if is_discord_invite:
                    try:
                        if await self._is_discord_invite_nsfw(url):
                            malicious_urls.append(url)
                    except Exception as e:
                        logger.error(f"Error checking Discord invite NSFW status: {e}")
                    continue

                if is_tenor or is_safe_discord_resource:
                    continue

            except Exception as e:
                logger.debug(f"URL whitelist parsing error, proceeding to scan: {e}")

            cached_result = self.url_cache.get_result(url)
            if cached_result:
                if cached_result.get("threat"):
                    malicious_urls.append(url)
                continue

            try:
                async with aiohttp.ClientSession() as session:
                    api_key = constants.web_risk_api_key()
                    if not api_key:
                        logger.warning("Web Risk API key not configured")
                        continue

                    params = {
                        "key": api_key,
                        "uri": url,
                        "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE"]
                    }

                    async with session.get(
                        "https://webrisk.googleapis.com/v1/uris:search",
                        params=params
                    ) as response:
                        response_text = await response.text()

                        if response.status == 200:
                            data = await response.json()

                            if data.get("threat") and data["threat"].get("expireTime"):
                                self.url_cache.add_result(url, data, data["threat"]["expireTime"])
                            elif not data.get("threat"):
                                safe_expire = discord.utils.utcnow() + timedelta(hours=1)
                                safe_iso = safe_expire.isoformat().replace('+00:00', 'Z')
                                safe_result = {"threat": None, "expireTime": safe_iso}
                                self.url_cache.add_result(url, safe_result, safe_iso)

                            if data.get("threat"):
                                malicious_urls.append(url)

                        elif response.status == 400:
                            logger.warning(f"Invalid URL format: {url} - Response: {response_text}")
                        elif response.status == 403:
                            logger.error("Web Risk API key is invalid or quota exceeded")
                        else:
                            logger.error(f"Web Risk API error: {response.status} - Response: {response_text}")

            except Exception as e:
                logger.error(f"Error checking URL safety: {e}")

        return len(malicious_urls) > 0, malicious_urls

    async def check_nsfw_content(self, content: str) -> tuple[bool, list]:
        """Check for NSFW content in links only."""
        content_lower = content.lower()
        malicious_urls = []

        logger.info(f"check_nsfw_content called with content: '{content}'")

        has_malicious_links, malicious_urls = await self.check_nsfw_links(content)
        logger.info(f"NSFW links check result: {has_malicious_links}, malicious_urls: {malicious_urls}")

        if has_malicious_links:
            logger.info("Returning True due to malicious links")
            return True, malicious_urls

        logger.info("No NSFW content detected, returning False")
        return False, []

    async def handle_spam_detection(self, message: discord.Message):
        """Handle spam detection for a user."""
        if message.author.guild_permissions.manage_messages:
            return

        user_id = message.author.id
        current_time = discord.utils.utcnow()

        self.message_history[user_id].append(current_time)

        if user_id in self.spam_cooldowns:
            if current_time < self.spam_cooldowns[user_id]:
                return

        recent_messages_15s = [
            msg for msg in self.message_history[user_id]
            if current_time - msg < timedelta(seconds=15)
        ]

        recent_messages_10s = [
            msg for msg in self.message_history[user_id]
            if current_time - msg < timedelta(seconds=10)
        ]

        if len(recent_messages_15s) >= 8 or len(recent_messages_10s) >= 12:
            self.spam_warnings[user_id] += 1

            if self.spam_warnings[user_id] >= 3:
                try:
                    timeout_until = discord.utils.utcnow() + timedelta(minutes=5)
                    await message.author.timeout(timeout_until, reason="Spam detected")
                    await message.channel.send(
                        f"⏰ **{message.author.display_name}** has been timed out for 5 minutes due to spam."
                    )
                    logger.info(f"User {message.author.display_name} timed out for spam")

                    await self.security_logger.log_spam_detection(
                        user_id=message.author.id,
                        guild_id=message.guild.id,
                        channel_id=message.channel.id,
                        message_count=len(recent_messages_15s),
                        time_window="15 seconds"
                    )
                except Exception as e:
                    logger.error(f"Failed to timeout user {message.author.display_name}: {e}")
            else:
                await message.channel.send(f"⚠️ **{message.author.display_name}**, please slow down your messages.")

            self.spam_cooldowns[user_id] = current_time + timedelta(minutes=1)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Handle message events for spam and NSFW detection."""
        if message.author.bot or not message.guild:
            if not message.guild and not message.author.bot:
                detector = get_suspicious_activity_detector(self.bot)
                await detector.check_dm_spam(message)
            return

        ignore_check = await self.bot.db.find_ignore(message.guild.id, channel_id=message.channel.id)
        if ignore_check:
            return

        detector = get_suspicious_activity_detector(self.bot)
        await detector.check_message_patterns(message)

        await self.scan_message_with_ai(message)
        await self.check_banned_server_invites(message)
        await self.handle_spam_detection(message)

        logger.info(f"Checking NSFW content for message: '{message.content}'")
        is_nsfw, malicious_urls = await self.check_nsfw_content(message.content)
        if is_nsfw:
            logger.info(f"NSFW content detected from {message.author.display_name} in {message.guild.name}")
            logger.info(f"Content: {message.content}")
            logger.info(f"Malicious URLs: {malicious_urls}")

            try:
                await message.delete()
                await message.channel.send(
                    f"**{message.author.display_name}**, NSFW or Malicious content is not allowed.",
                    delete_after=10
                )

                await self.log_nsfw_detection(message, message.content, malicious_urls)

                await self.security_logger.log_nsfw_detection(
                    user_id=message.author.id,
                    guild_id=message.guild.id,
                    channel_id=message.channel.id,
                    message_id=message.id,
                    urls=malicious_urls,
                    content_length=len(message.content)
                )

                try:
                    embed = EmbedDesign.warning(
                        title="Malicious Content Detected",
                        description=(
                            f"Your message in **{message.guild.name}** was automatically removed due to "
                            f"containing NSFW or malicious content.\n\n"
                            f"**Server:** {message.guild.name}\n"
                            f"**Channel:** #{message.channel.name}\n\n"
                            f"This is an automated action to protect server members."
                        )
                    )
                    if malicious_urls:
                        embed.add_field(
                            name="Detected URLs",
                            value=f"• {chr(10).join(malicious_urls[:3])}" + ("..." if len(malicious_urls) > 3 else ""),
                            inline=False
                        )
                    embed.set_footer(text="If you believe this was an error, please contact server staff.")
                    await message.author.send(embed=embed)
                except discord.Forbidden:
                    logger.info(f"Could not DM user {message.author} about malicious content removal")

                logger.info("Sending NSFW report to main server")
                await self.send_nsfw_report_to_main_server(message, message.content, malicious_urls)

                is_developer = await StaffUtils.has_developer_permission_cross_guild(self.bot, message.author)
                if not (StaffUtils.is_staff(message.author) or is_developer):
                    logger.info(f"User {message.author.display_name} is not staff, timing out")
                    try:
                        timeout_until = discord.utils.utcnow() + timedelta(hours=24)
                        await message.author.timeout(timeout_until, reason="NSFW content detected")
                        await message.channel.send(
                            f"**{message.author.display_name}** has been timed out for 24 hours due to NSFW content."
                        )
                        logger.info(f"User {message.author.display_name} timed out for NSFW content")
                    except Exception as e:
                        logger.error(f"Failed to timeout user {message.author.display_name}: {e}")
                else:
                    logger.info(f"User {message.author.display_name} is staff, skipping timeout")

            except Exception as e:
                logger.error(f"Error handling NSFW content: {e}")
        else:
            logger.info("No NSFW content detected, returning False")

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Handle persistent moderation report button interactions."""
        if not interaction.type == discord.InteractionType.component:
            return

        if not interaction.data or 'custom_id' not in interaction.data:
            return

        custom_id = interaction.data['custom_id']

        if custom_id.startswith('mod_'):
            await self._handle_moderation_button(interaction, custom_id)

    async def _handle_moderation_button(self, interaction: discord.Interaction, custom_id: str):
        """Handle moderation report button interactions."""
        try:
            parts = custom_id.split('_', 2)
            if len(parts) != 3:
                return

            action = parts[1]
            report_id = parts[2]

            if not await self._check_staff_permission(interaction):
                await interaction.response.send_message("! You don't have permission to use this button.", ephemeral=True)
                return

            if action == "accept":
                await self._handle_accept_report(interaction, report_id)
            elif action == "deny":
                await self._handle_deny_report(interaction, report_id)
            elif action == "view":
                await self._handle_view_message(interaction, report_id)

        except Exception as e:
            logger.error(f"Error handling moderation button: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("! Error processing button interaction.", ephemeral=True)

    async def _check_staff_permission(self, interaction: discord.Interaction) -> bool:
        """Check if user has staff permissions."""
        try:
            if interaction.user.guild_permissions.manage_messages:
                return True
            if interaction.user.guild_permissions.administrator:
                return True
            return False
        except Exception:
            return False

    async def _handle_accept_report(self, interaction: discord.Interaction, report_id: str):
        """Handle accept report button."""
        try:
            parts = report_id.split('_')
            if len(parts) != 3:
                await interaction.response.send_message("! Invalid report ID format.", ephemeral=True)
                return

            guild_id = int(parts[0])
            channel_id = int(parts[1])
            message_id = int(parts[2])

            guild = self.bot.get_guild(guild_id)
            if not guild:
                await interaction.response.send_message("! Guild not found.", ephemeral=True)
                return

            channel = guild.get_channel(channel_id)
            if not channel:
                await interaction.response.send_message("! Channel not found.", ephemeral=True)
                return

            try:
                message = await channel.fetch_message(message_id)
                await message.delete()
                logger.info(f"Deleted message {message_id} from channel {channel_id}")
            except discord.NotFound:
                logger.warning(f"Message {message_id} not found, may have been already deleted")
            except discord.Forbidden:
                logger.error(f"No permission to delete message {message_id}")
                await interaction.response.send_message("! No permission to delete the message.", ephemeral=True)
                return
            except Exception as e:
                logger.error(f"Error deleting message {message_id}: {e}")
                await interaction.response.send_message("! Error deleting the message.", ephemeral=True)
                return

            embed = interaction.message.embeds[0]
            embed.color = 0xFF4444
            embed.add_field(
                name="[Status]",
                value=f"**ACCEPTED** by {interaction.user.mention}\n*Message deleted*",
                inline=False
            )

            view = discord.ui.View()
            for item in interaction.message.components[0].children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
                    view.add_item(item)

            await interaction.response.edit_message(embed=embed, view=view)

        except Exception as e:
            logger.error(f"Error handling accept report: {e}")
            await interaction.response.send_message("! Error processing report acceptance.", ephemeral=True)

    async def _handle_deny_report(self, interaction: discord.Interaction, report_id: str):
        """Handle deny report button."""
        try:
            embed = interaction.message.embeds[0]
            embed.color = 0x00AA00
            embed.add_field(
                name="[Status]",
                value=f"**DENIED** by {interaction.user.mention}\n*No action taken*",
                inline=False
            )

            view = discord.ui.View()
            for item in interaction.message.components[0].children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
                    view.add_item(item)

            await interaction.response.edit_message(embed=embed, view=view)

        except Exception as e:
            logger.error(f"Error handling deny report: {e}")
            await interaction.response.send_message("! Error processing report denial.", ephemeral=True)

    async def _handle_view_message(self, interaction: discord.Interaction, report_id: str):
        """Handle view message button."""
        try:
            parts = report_id.split('_')
            if len(parts) != 3:
                await interaction.response.send_message("! Invalid report ID format.", ephemeral=True)
                return

            guild_id = int(parts[0])
            channel_id = int(parts[1])
            message_id = int(parts[2])

            message_link = f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
            await interaction.response.send_message(f"-> [Click here to view the message]({message_link})", ephemeral=True)

        except Exception as e:
            logger.error(f"Error handling view message: {e}")
            await interaction.response.send_message("! Error retrieving message link.", ephemeral=True)

    async def send_nsfw_report(self, message: discord.Message, malicious_urls: list = None):
        """Send NSFW report to the main server's report channel."""
        try:
            main_server_id = constants.main_server_id()
            report_channel_id = constants.report_channel_id()

            logger.info(
                f"Attempting to send NSFW report - Main Server ID: {main_server_id}, "
                f"Report Channel ID: {report_channel_id}"
            )

            main_server = self.bot.get_guild(main_server_id)
            if not main_server:
                logger.error(f"Main server not found with ID: {main_server_id}")
                logger.info(f"Available guilds: {[guild.name for guild in self.bot.guilds]}")
                return

            report_channel = main_server.get_channel(report_channel_id)
            if not report_channel:
                logger.error(f"Report channel not found with ID: {report_channel_id}")
                logger.info(f"Available channels in {main_server.name}: {[channel.name for channel in main_server.channels]}")
                return

            logger.info(f"Found report channel: {report_channel.name} in {main_server.name}")

            is_staff = StaffUtils.is_staff(message.author) or await StaffUtils.has_developer_permission_cross_guild(
                self.bot, message.author
            )
            action_taken = "Message reported (Staff user)" if is_staff else "User timed out"

            fields = [
                {"name": "User", "value": f"{message.author.mention} ({message.author.id})", "inline": True},
                {"name": "Server", "value": f"{message.guild.name} ({message.guild.id})", "inline": True},
                {"name": "Channel", "value": f"{message.channel.mention}", "inline": True},
                {"name": "Message Link", "value": f"[Jump to Message]({message.jump_url})", "inline": True},
                {"name": "Content", "value": message.content[:1000] + "..." if len(message.content) > 1000 else message.content, "inline": False},
                {"name": "Action Taken", "value": action_taken, "inline": True},
                {"name": "Reported by", "value": "EPN Bot", "inline": True}
            ]

            if malicious_urls:
                fields.append({
                    "name": "Malicious URLs",
                    "value": "\n".join([f"• {url}" for url in malicious_urls]),
                    "inline": False
                })

            embed = EmbedDesign.error(
                title="NSFW Content Report",
                description=f"User sent NSFW content. {action_taken}.",
                fields=fields
            )

            logger.info(f"Sending NSFW report to channel: {report_channel.name}")
            await report_channel.send(embed=embed)
            logger.info("NSFW report sent successfully")

        except Exception as e:
            logger.error(f"Error sending NSFW report: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Handle member join events for raid detection and blacklist checking."""
        if member.bot:
            return

        detector = get_suspicious_activity_detector(self.bot)
        await detector.check_unusual_join_pattern(member)

        await self.handle_raid_detection(member)

        blacklist_record = await self.bot.db.find_blacklist(member.id, active=True)

        if blacklist_record:
            if member.guild.id == constants.main_server_id():
                return

            reason = blacklist_record.get("reason", "No reason provided")
            blacklisted_by_id = blacklist_record.get("blacklisted_by")
            blacklisted_by = f"<@{blacklisted_by_id}>" if blacklisted_by_id else "Unknown"
            timestamp = blacklist_record["timestamp"].strftime("%Y-%m-%d %H:%M:%S")

            ban_successful = False
            try:
                ban_reason = f"EPN Blacklist - Reason: {reason} | Blacklisted by: {blacklisted_by} | Date: {timestamp}"
                await member.ban(reason=ban_reason)
                ban_successful = True
                logger.info(f"Successfully banned blacklisted user {member.id} ({member.display_name})")
            except discord.Forbidden:
                logger.warning(f"Cannot ban blacklisted user {member.id} ({member.display_name}) - missing permissions")
            except Exception as e:
                logger.error(f"Error banning blacklisted user {member.id} ({member.display_name}): {e}")

            await self.log_EPN_ban(member, reason, blacklisted_by, ban_successful)
            await self.handle_EPN_ban_notification(member, reason, blacklisted_by)

        await self.check_alt_evasion(member)
async def send_staff_log(self, guild: discord.Guild, embed: discord.Embed):
    """Send log to server's configured log channel."""
    try:
        log_config = await self.bot.db.find_log_config(guild.id)
        logger.info(f"log_config for guild {guild.id}: {log_config}")

        if log_config:
            channel_id = (
                log_config.get("channel_id")
                or log_config.get("log_channel_id")
                or log_config.get("channel")
            )

            if not channel_id:
                logger.error(f"Log config missing channel field: {log_config}")
                return

            channel = guild.get_channel(int(channel_id))
            if channel and isinstance(channel, discord.TextChannel):
                await channel.send(embed=embed)
            else:
                logger.error(f"Configured log channel {channel_id} not found in guild {guild.id}")
        else:
            for channel in guild.channels:
                if isinstance(channel, discord.TextChannel) and channel.name.lower() in ["staff", "mod-logs", "logs", "admin"]:
                    try:
                        await channel.send(embed=embed)
                        break
                    except discord.Forbidden:
                        continue

    except Exception as e:
        logger.error(f"Error sending staff log: {e}")
    async def log_EPN_ban(self, member: discord.Member, reason: str, blacklisted_by: str, ban_successful: bool = True):
        """Log EPN ban to server's log channel."""
        status = "Banned" if ban_successful else "Ban Failed"
        color = 0xFF0000 if ban_successful else 0xFFA500

        embed = EmbedDesign.error(
            title=f"EPN Auto-Ban ({status})",
            description=f"**{member.display_name}** was detected on EPN blacklist.",
            fields=[
                {"name": "User", "value": f"{member.mention} ({member.id})", "inline": True},
                {"name": "Status", "value": status, "inline": True},
                {"name": "Reason", "value": reason, "inline": True},
                {"name": "Blacklisted by", "value": blacklisted_by, "inline": True}
            ]
        )

        if not ban_successful:
            embed.color = color

        await self.send_staff_log(member.guild, embed)

    async def check_alt_evasion(self, member: discord.Member):
        """Check if joining user is an alt account trying to evade a ban."""
        try:
            roblox_id = None
            try:
                async with aiohttp.ClientSession() as session:
                    bloxlink_url = f"https://api.blox.link/v4/public/discord-to-roblox/{member.id}"
                    headers = {"Authorization": constants.bloxlink_api_key()}

                    async with session.get(bloxlink_url, headers=headers) as response:
                        if response.status == 200:
                            bloxlink_data = await response.json()
                            roblox_id = bloxlink_data.get("robloxId")
                            logger.info(f"Retrieved Roblox ID {roblox_id} for joining user {member.id}")
            except Exception as e:
                logger.error(f"Error getting Roblox ID for joining user {member.id}: {e}")
                return

            if not roblox_id:
                return

            banned_record = None

            if banned_record:
                if member.guild.id == constants.main_server_id():
                    return

                main_user_id = banned_record.get("user_id")
                main_reason = banned_record.get("reason", "No reason provided")
                blacklisted_by_id = banned_record.get("blacklisted_by")
                blacklisted_by = f"<@{blacklisted_by_id}>" if blacklisted_by_id else "Unknown"

                ban_successful = False
                try:
                    ban_reason = f"[EPN] Alt Evasion - {main_user_id}"
                    await member.ban(reason=ban_reason)
                    ban_successful = True
                    logger.info(f"Successfully banned alt evasion user {member.id} ({member.display_name})")
                except discord.Forbidden:
                    logger.warning(f"Cannot ban alt evasion user {member.id} ({member.display_name}) - missing permissions")
                except Exception as e:
                    logger.error(f"Error banning alt evasion user {member.id} ({member.display_name}): {e}")

                await self.log_alt_evasion_ban(
                    member, roblox_id, main_user_id, main_reason, blacklisted_by, ban_successful
                )

                await self.security_logger.log_blacklist_evasion(
                    user_id=member.id,
                    guild_id=member.guild.id,
                    original_user_id=main_user_id,
                    detection_method="roblox_id_matching"
                )

                await self.handle_EPN_ban_notification(member, f"Alt Evasion - {main_user_id}", blacklisted_by)

        except Exception as e:
            logger.error(f"Error checking alt evasion: {e}")

    async def log_alt_evasion_ban(
        self,
        member: discord.Member,
        roblox_id: str,
        main_user_id: int,
        main_reason: str,
        blacklisted_by: str,
        ban_successful: bool = True
    ):
        """Log alt evasion ban to server's log channel."""
        status = "Banned" if ban_successful else "Ban Failed"
        color = 0xFF0000 if ban_successful else 0xFFA500

        embed = EmbedDesign.error(
            title=f"Alt Evasion Detected ({status})",
            description=f"**{member.display_name}** was detected for alt evasion.",
            fields=[
                {"name": "User", "value": f"{member.mention} ({member.id})", "inline": True},
                {"name": "Status", "value": status, "inline": True},
                {"name": "Roblox ID", "value": roblox_id, "inline": True},
                {"name": "Main Banned User", "value": f"<@{main_user_id}> ({main_user_id})", "inline": True},
                {"name": "Original Reason", "value": main_reason, "inline": False},
                {"name": "Blacklisted by", "value": blacklisted_by, "inline": True}
            ]
        )

        if not ban_successful:
            embed.color = color

        await self.send_staff_log(member.guild, embed)

    async def log_nsfw_detection(self, message: discord.Message, content: str, malicious_urls: list = None):
        """Log NSFW detection to server's log channel."""
        fields = [
            {"name": "User", "value": f"{message.author.mention} ({message.author.id})", "inline": True},
            {"name": "Channel", "value": f"{message.channel.mention}", "inline": True},
            {"name": "Message Link", "value": f"[Jump to Message]({message.jump_url})", "inline": True},
            {"name": "Content", "value": content[:1000] + "..." if len(content) > 1000 else content, "inline": False},
            {"name": "Action", "value": "Message deleted, user timed out", "inline": True}
        ]

        if malicious_urls:
            fields.append({
                "name": "Malicious URLs",
                "value": "\n".join([f"• {url}" for url in malicious_urls]),
                "inline": False
            })

        embed = EmbedDesign.error(
            title="NSFW Content Detected",
            description=f"**{message.author.display_name}** sent NSFW content.",
            fields=fields
        )

        await self.send_staff_log(message.guild, embed)

    async def log_raid_detection(self, guild: discord.Guild, join_count: int):
        """Log raid detection to server's log channel."""
        embed = EmbedDesign.error(
            title="Raid Detection",
            description=f"**{join_count} users** joined in the last 30 seconds!",
            fields=[
                {"name": "Recent joins", "value": f"{join_count} users", "inline": True},
                {"name": "Time period", "value": "30 seconds", "inline": True}
            ]
        )

        await self.send_staff_log(guild, embed)

    async def handle_raid_detection(self, member: discord.Member):
        """Handle raid detection for new members."""
        guild_id = member.guild.id
        current_time = discord.utils.utcnow()

        self.recent_joins[guild_id].append(current_time)

        recent_joins = [
            join_time for join_time in self.recent_joins[guild_id]
            if current_time - join_time < timedelta(seconds=30)
        ]

        if len(recent_joins) >= 20:
            if guild_id in self.raid_alerts:
                if current_time - self.raid_alerts[guild_id] < timedelta(minutes=5):
                    return

            self.raid_alerts[guild_id] = current_time

            await self.log_raid_detection(member.guild, len(recent_joins))

            await self.security_logger.log_raid_detection(
                guild_id=member.guild.id,
                join_count=len(recent_joins)
            )

            for join_time in recent_joins:
                for guild_member in member.guild.members:
                    if guild_member.joined_at and abs((guild_member.joined_at - join_time).total_seconds()) < 5:
                        try:
                            timeout_until = discord.utils.utcnow() + timedelta(hours=24)
                            await guild_member.timeout(timeout_until, reason="Raid detection - excessive joins")
                            logger.info(f"Timed out {guild_member.display_name} for raiding")
                        except Exception as e:
                            logger.error(f"Failed to timeout {guild_member.display_name} for raiding: {e}")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Handle member leave events."""
        await self.handle_member_leave_notification(member)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        """Handle bot joining a guild."""
        try:
            await self.log_guild_join(guild)
        except Exception as e:
            logger.error(f"Error in on_guild_join: {e}")

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        """Handle bot leaving a guild."""
        try:
            await self.log_guild_leave(guild)
        except Exception as e:
            logger.error(f"Error in on_guild_remove: {e}")

    async def log_guild_join(self, guild: discord.Guild):
        """Log when the bot joins a guild."""
        try:
            log_channel = self.bot.get_channel(1481976236497571900)
            if not log_channel:
                logger.error("Could not find guild join/leave log channel")
                return

            embed = EmbedDesign.success(
                title="🤖 Bot Joined Server",
                description=f"**{guild.name}**",
                fields=[
                    {"name": "Server ID", "value": f"`{guild.id}`", "inline": True},
                    {"name": "Owner", "value": f"<@{guild.owner_id}>", "inline": True},
                    {"name": "Member Count", "value": f"{guild.member_count:,}", "inline": True},
                    {"name": "Created", "value": f"<t:{int(guild.created_at.timestamp())}:R>", "inline": True}
                ]
            )

            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)

            await log_channel.send(embed=embed)
            logger.info(f"Bot joined guild: {guild.name} ({guild.id})")

        except Exception as e:
            logger.error(f"Error logging guild join: {e}")

    async def log_guild_leave(self, guild: discord.Guild):
        """Log when the bot leaves a guild."""
        try:
            log_channel = self.bot.get_channel(1481976236497571900)
            if not log_channel:
                logger.error("Could not find guild join/leave log channel")
                return

            embed = EmbedDesign.error(
                title="🚪 Bot Left Server",
                description=f"**{guild.name}**",
                fields=[
                    {"name": "Server ID", "value": f"`{guild.id}`", "inline": True},
                    {"name": "Owner", "value": f"<@{guild.owner_id}>", "inline": True},
                    {"name": "Member Count", "value": f"{guild.member_count:,}", "inline": True},
                    {"name": "Joined", "value": f"<t:{int(guild.me.joined_at.timestamp()) if guild.me.joined_at else 0}:R>", "inline": True}
                ]
            )

            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)

            await log_channel.send(embed=embed)
            logger.info(f"Bot left guild: {guild.name} ({guild.id})")

        except Exception as e:
            logger.error(f"Error logging guild leave: {e}")

    async def handle_member_leave_notification(self, member: discord.Member):
        """Handle member leave notifications for configured roles."""
        try:
            configs = await self.bot.db.find_all_configs(member.guild.id)
            alert_config = configs["alert_config"]
            ping_config = configs["ping_config"]

            if not alert_config:
                return

            alert_role = member.guild.get_role(alert_config["role_id"])
            if not alert_role or alert_role not in member.roles:
                return

            if not ping_config:
                return

            ping_role = member.guild.get_role(ping_config["role_id"])
            if not ping_role:
                return

            roblox_info = await self.get_roblox_info(member.id)

            fields = [
                {"name": "User", "value": f"{member.mention} ({member.id})", "inline": True},
                {"name": "Alert Role", "value": alert_role.mention, "inline": True},
                {"name": "Joined At", "value": member.joined_at.strftime("%Y-%m-%d %H:%M:%S") if member.joined_at else "Unknown", "inline": True}
            ]

            embed = EmbedDesign.warning(
                title="Member Left",
                description=f"**{member.display_name}** has left the server.",
                fields=fields
            )

            if roblox_info:
                embed.add_field(name="Roblox Username", value=roblox_info.get("username", "Unknown"), inline=True)
                embed.add_field(name="Roblox Display Name", value=roblox_info.get("displayName", "Unknown"), inline=True)
                embed.add_field(name="Roblox ID", value=roblox_info.get("id", "Unknown"), inline=True)

                if roblox_info.get("thumbnail"):
                    embed.set_thumbnail(url=roblox_info["thumbnail"])

            await self.send_staff_log(member.guild, embed)
            await self.send_ping_notification(member.guild, ping_role, embed)

        except Exception as e:
            logger.error(f"Error handling member leave notification: {e}")

    async def get_roblox_info(self, user_id: int) -> dict:
        """Get Roblox information for a Discord user."""
        try:
            async with aiohttp.ClientSession() as session:
                bloxlink_url = f"https://api.blox.link/v4/public/discord-to-roblox/{user_id}"
                headers = {"Authorization": constants.bloxlink_api_key()}

                async with session.get(bloxlink_url, headers=headers) as response:
                    if response.status == 200:
                        bloxlink_data = await response.json()
                        roblox_id = bloxlink_data.get("robloxId")

                        if roblox_id:
                            roblox_url = f"https://users.roblox.com/v1/users/{roblox_id}"
                            async with session.get(roblox_url) as roblox_response:
                                if roblox_response.status == 200:
                                    roblox_data = await roblox_response.json()

                                    avatar_url = (
                                        f"https://thumbnails.roblox.com/v1/users/avatar-headshot"
                                        f"?userIds={roblox_id}&size=150x150&format=Png&isCircular=false"
                                    )
                                    async with session.get(avatar_url) as avatar_response:
                                        avatar_data = await avatar_response.json() if avatar_response.status == 200 else {}
                                        thumbnail = avatar_data.get("data", [{}])[0].get("imageUrl") if avatar_data.get("data") else None

                                    return {
                                        "username": roblox_data.get("name", "Unknown"),
                                        "displayName": roblox_data.get("displayName", "Unknown"),
                                        "id": str(roblox_id),
                                        "thumbnail": thumbnail
                                    }

        except Exception as e:
            logger.error(f"Error getting Roblox info: {e}")

        return None

    async def send_ping_notification(self, guild: discord.Guild, ping_role: discord.Role, embed: discord.Embed):
        """Send ping notification to the configured channel."""
        try:
            log_config = await self.bot.db.find_log_config(guild.id)

            if log_config:
                channel = guild.get_channel(log_config["channel_id"])
                if channel:
                    await channel.send(f"{ping_role.mention} - Member with alert role has left!", embed=embed)

        except Exception as e:
            logger.error(f"Error sending ping notification: {e}")

    async def handle_EPN_ban_notification(self, member: discord.Member, reason: str, blacklisted_by: str):
        """Handle EPN ban notifications for configured roles."""
        try:
            configs = await self.bot.db.find_all_configs(member.guild.id)
            alert_config = configs["alert_config"]
            ping_config = configs["ping_config"]

            if not alert_config:
                return

            alert_role = member.guild.get_role(alert_config["role_id"])
            if not alert_role or alert_role not in member.roles:
                return

            if not ping_config:
                return

            ping_role = member.guild.get_role(ping_config["role_id"])
            if not ping_role:
                return

            roblox_info = await self.get_roblox_info(member.id)

            fields = [
                {"name": "User", "value": f"{member.mention} ({member.id})", "inline": True},
                {"name": "Alert Role", "value": alert_role.mention, "inline": True},
                {"name": "Reason", "value": reason, "inline": True},
                {"name": "Blacklisted by", "value": blacklisted_by, "inline": True}
            ]

            embed = EmbedDesign.error(
                title="Member EPN Banned",
                description=f"**{member.display_name}** has been EPN banned.",
                fields=fields
            )

            if roblox_info:
                embed.add_field(name="Roblox Username", value=roblox_info.get("username", "Unknown"), inline=True)
                embed.add_field(name="Roblox Display Name", value=roblox_info.get("displayName", "Unknown"), inline=True)
                embed.add_field(name="Roblox ID", value=roblox_info.get("id", "Unknown"), inline=True)

                if roblox_info.get("thumbnail"):
                    embed.set_thumbnail(url=roblox_info["thumbnail"])

            await self.send_staff_log(member.guild, embed)
            await self.send_ping_notification(member.guild, ping_role, embed)

        except Exception as e:
            logger.error(f"Error handling EPN ban notification: {e}")

    @commands.hybrid_group(name="check", description="Check commands")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def check_group(self, ctx: commands.Context):
        """Check commands."""
        if not ctx.invoked_subcommand:
            embed = EmbedDesign.info(
                title="Check Commands",
                description="Available check commands:",
                fields=[
                    {"name": "invite", "value": "Check if a Discord invite is NSFW or inappropriate", "inline": True}
                ]
            )
            await self._ctx_send(ctx, embed=embed, ephemeral=True)

    @check_group.command(name="invite", description="Check if a Discord invite is NSFW or inappropriate")
    @app_commands.describe(invite_url="The Discord invite URL to check")
    async def check_invite_command(self, ctx: commands.Context, invite_url: str):
        """Check if a Discord invite is NSFW or inappropriate."""
        if not await StaffUtils.has_developer_permission_cross_guild(self.bot, ctx.author, "developer"):
            await self._ctx_send(ctx, content="You don't have permission to use this command.", ephemeral=True)
            return

        await self._ctx_defer(ctx, ephemeral=True)

        discord_invite_pattern = re.compile(
            r'(?:https?://)?(?:www\.)?(?:discord(?:app)?\.com/invite/|discord\.gg/)[a-zA-Z0-9-]+',
            re.IGNORECASE
        )
        if not discord_invite_pattern.match(invite_url):
            await self._ctx_send(ctx, content="Invalid Discord invite URL format.", ephemeral=True)
            return

        try:
            is_nsfw, reason = await self.check_discord_invite(invite_url)

            if is_nsfw:
                embed = EmbedDesign.error(
                    title="Discord Invite Check",
                    description=f"**Result:** NSFW/Inappropriate\n**Reason:** {reason}\n**URL:** {invite_url}"
                )
            else:
                embed = EmbedDesign.success(
                    title="Discord Invite Check",
                    description=f"**Result:** Safe\n**Reason:** {reason}\n**URL:** {invite_url}"
                )

            await self._ctx_send(ctx, embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in check_invite_command: {e}")
            embed = EmbedDesign.error(
                title="Error",
                description=f"An error occurred while checking the invite: {e}"
            )
            await self._ctx_send(ctx, embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """Handle command errors to prevent Sentry logging for common issues."""
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.BadArgument):
            return
        if isinstance(error, commands.MissingRequiredArgument):
            return
        if isinstance(error, commands.TooManyArguments):
            return

        logger.error(f"Command error in {ctx.guild.name} ({ctx.guild.id}): {error}")

    async def check_banned_server_invites(self, message: discord.Message):
        """Check if message contains invite links to banned servers."""
        try:
            if message.author.bot:
                return

            banned_server_invite_pattern = re.compile(
                r'(?:https?://)?(?:www\.)?(?:discord(?:\.gg|app\.com/invite)/|discordapp\.com/invite/)([a-zA-Z0-9-]+)',
                re.IGNORECASE
            )

            invite_matches = banned_server_invite_pattern.findall(message.content)
            if not invite_matches:
                return

            for invite_code in invite_matches:
                try:
                    invite = await self.bot.fetch_invite(f"https://discord.gg/{invite_code}")
                    if not invite or not invite.guild:
                        continue

                    server_ban = await self.bot.db.find_server_ban(invite.guild.id, active=True)
                    if server_ban:
                        try:
                            await message.delete()
                            logger.info(f"Deleted message with banned server invite from {message.author} in {message.guild.name}")
                        except discord.NotFound:
                            pass
                        except discord.Forbidden:
                            logger.warning(
                                f"No permission to delete message with banned server invite in {message.guild.name}"
                            )

                        try:
                            embed = EmbedDesign.warning(
                                title="Banned Server Invite Detected",
                                description=(
                                    f"Your message contained an invite to a banned server: **{invite.guild.name}**\n\n"
                                    f"**Reason for ban:** {server_ban.get('reason', 'No reason provided')}\n\n"
                                    f"Your message has been automatically removed."
                                )
                            )
                            embed.set_footer(text="Appeals can be submitted to EPN staff if you believe this is an error.")
                            await message.author.send(embed=embed)
                        except discord.Forbidden:
                            logger.info(f"Could not DM user {message.author} about banned server invite")

                        await self.report_banned_server_invite(message, invite.guild, server_ban)
                        break

                except discord.NotFound:
                    continue
                except discord.HTTPException:
                    continue
                except Exception as e:
                    logger.error(f"Error checking invite {invite_code}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error checking banned server invites: {e}")

    async def report_banned_server_invite(self, message: discord.Message, banned_guild: discord.Guild, server_ban: dict):
        """Report a banned server invite violation to staff."""
        try:
            notification_channel_id = constants.EPN_notification_channel()
            if not notification_channel_id:
                return

            notification_channel = self.bot.get_channel(notification_channel_id)
            if not notification_channel:
                return

            embed = EmbedDesign.error(
                title="🚫 Banned Server Invite Detected",
                description=(
                    f"**User:** {message.author.mention} (`{message.author.id}`)\n"
                    f"**Guild:** {message.guild.name} (`{message.guild.id}`)\n"
                    f"**Channel:** {message.channel.mention}\n"
                    f"**Banned Server:** {banned_guild.name} (`{banned_guild.id}`)\n"
                    f"**Ban Reason:** {server_ban.get('reason', 'No reason provided')}"
                )
            )
            embed.add_field(
                name="Message Content",
                value=f"```{message.content[:900] + '...' if len(message.content) > 900 else message.content}```",
                inline=False
            )
            embed.add_field(
                name="Action Taken",
                value="✅ Message deleted\n✅ User notified\n📋 Staff reported",
                inline=True
            )
            if server_ban.get('appeal_allowed'):
                embed.add_field(name="Appeals", value="✅ Appeals allowed", inline=True)
            embed.set_thumbnail(url=message.author.display_avatar.url)
            embed.set_footer(
                text=f"Server Ban ID: {server_ban.get('id')} • Banned by: {server_ban.get('banned_by')}"
            )

            await notification_channel.send(embed=embed)

        except Exception as e:
            logger.error(f"Error reporting banned server invite: {e}")

    @commands.Cog.listener()
    async def on_automod_action_execution(self, execution):
        """Handle AutoMod action execution events for blocked messages."""
        try:
            if execution.action.type != discord.AutoModActionType.block_message:
                return

            if not execution.content or not execution.member or execution.member.bot:
                return

            ignore_check = await self.bot.db.find_ignore(
                execution.guild.id,
                channel_id=execution.channel.id
            )
            if ignore_check:
                return

            mock_message = type('MockMessage', (), {
                'content': execution.content,
                'author': execution.member,
                'guild': execution.guild,
                'channel': execution.channel,
                'id': None,
                'created_at': datetime.now(timezone.utc),
                'mentions': [],
                'role_mentions': [],
                'bot': False
            })()

            logger.info(
                f"AutoMod blocked message detected: '{execution.content}' from {execution.member.display_name}"
            )

            detector = get_suspicious_activity_detector(self.bot)
            await detector.check_message_patterns(mock_message)

            await self.scan_message_with_ai(mock_message)
            await self.check_banned_server_invites(mock_message)

            logger.info(f"Checking NSFW content for AutoMod blocked message: '{execution.content}'")
            is_nsfw, malicious_urls = await self.check_nsfw_content(execution.content)
            if is_nsfw:
                logger.info(f"NSFW content detected in AutoMod blocked message from {execution.member.display_name}")
                logger.info(f"Content: {execution.content}")
                logger.info(f"Malicious URLs: {malicious_urls}")

                await self.log_nsfw_detection(mock_message, execution.content, malicious_urls)

                await self.security_logger.log_nsfw_detection(
                    user_id=execution.member.id,
                    guild_id=execution.guild.id,
                    channel_id=execution.channel.id,
                    message_id=None,
                    urls=malicious_urls,
                    content_length=len(execution.content)
                )

                await self.security_logger.log_event(
                    SecurityEventType.SUSPICIOUS_ACTIVITY,
                    SecurityEventSeverity.HIGH,
                    user_id=execution.member.id,
                    guild_id=execution.guild.id,
                    channel_id=execution.channel.id,
                    details={
                        "activity_type": "automod_bypass_attempt",
                        "blocked_content": execution.content[:200],
                        "automod_rule": execution.rule_trigger_type.name if execution.rule_trigger_type else "unknown",
                        "detection_reason": "NSFW content blocked by AutoMod",
                        "malicious_urls": malicious_urls
                    },
                    action_taken="Content blocked by AutoMod, flagged for review"
                )

        except Exception as e:
            logger.error(f"Error handling AutoMod action execution: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Events(bot))
