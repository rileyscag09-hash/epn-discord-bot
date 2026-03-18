import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta
from typing import Optional, Union
import re
import logging

from utils.constants import Constants, EmbedDesign
from utils.staff import StaffUtils
from utils.rate_limiter import UserCommandRateLimiter
from utils.validation import validate_input, validate_discord_id, InputSanitizer
from utils.security_logger import get_security_logger

logger = logging.getLogger(__name__)
constants = Constants()


class EPNCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.security_logger = get_security_logger(bot)
        self.admin_rate_limiter = UserCommandRateLimiter(
            max_requests=3,
            time_window=3600,
            command_name="EPN_admin_commands"
        )

    def parse_duration(self, duration_str: str) -> datetime:
        """Parse a duration string like '1d', '2h', '30m' into a datetime."""
        duration_str = duration_str.strip().lower()
        match = re.match(r"^(\d+)([dhms])$", duration_str)

        if not match:
            raise ValueError(
                f"Invalid duration format: {duration_str}. Use format like '1d', '2h', '30m', '45s'"
            )

        value, unit = match.groups()
        value = int(value)

        if unit == "s":
            seconds = value
        elif unit == "m":
            seconds = value * 60
        elif unit == "h":
            seconds = value * 3600
        elif unit == "d":
            seconds = value * 86400
        else:
            raise ValueError(f"Invalid time unit: {unit}")

        return datetime.utcnow() + timedelta(seconds=seconds)

    async def check_admin_rate_limit(self, user_id: int) -> tuple[bool, Optional[str]]:
        can_proceed = await self.admin_rate_limiter.can_make_request(user_id)

        if not can_proceed:
            wait_time = await self.admin_rate_limiter.get_wait_time(user_id)
            remaining = await self.admin_rate_limiter.get_remaining_requests(user_id)

            if wait_time > 0:
                wait_minutes = int(wait_time // 60)
                wait_seconds = int(wait_time % 60)
                if wait_minutes > 0:
                    time_str = f"{wait_minutes}m {wait_seconds}s"
                else:
                    time_str = f"{wait_seconds}s"

                error_msg = (
                    f"You have reached the rate limit for EPN commands (3 per hour). "
                    f"Try again in {time_str}."
                )
            else:
                error_msg = (
                    f"You have reached the rate limit for EPN commands (3 per hour). "
                    f"{remaining} requests remaining."
                )

            return False, error_msg

        return True, None

    async def _safe_dm_user(self, user: Union[discord.User, discord.Member], embed: discord.Embed):
        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            logger.info(f"Could not DM user {user} ({user.id})")
        except Exception as e:
            logger.error(f"Error sending DM to user {user.id}: {e}")

    async def send_staff_log(self, guild: discord.Guild, embed: discord.Embed) -> bool:
        """Send a log embed to the configured log channel for this guild."""
        try:
            log_config = await self.bot.db.find_log_config(guild.id)
            logger.info(f"log_config for guild {guild.id}: {log_config}")

            if log_config:
                channel_id = (
                    log_config.get("channel_id")
                    or log_config.get("log_channel_id")
                    or log_config.get("channel")
                )

                if channel_id:
                    channel = guild.get_channel(int(channel_id))
                    if channel and isinstance(channel, discord.TextChannel):
                        perms = channel.permissions_for(guild.me)
                        if perms.view_channel and perms.send_messages and perms.embed_links:
                            await channel.send(embed=embed)
                            return True

            for channel in guild.text_channels:
                if channel.name.lower() in ["staff", "mod-logs", "logs", "admin", "staff-logs"]:
                    perms = channel.permissions_for(guild.me)
                    if perms.view_channel and perms.send_messages and perms.embed_links:
                        await channel.send(embed=embed)
                        return True

            logger.warning(f"No usable log channel found for guild {guild.id}")
            return False

        except Exception as e:
            logger.error(f"Error sending staff log for guild {guild.id}: {e}")
            return False

    async def send_cross_guild_log(
        self,
        guild: discord.Guild,
        action: str,
        user: Union[discord.User, discord.Member],
        staff_member: Union[discord.User, discord.Member],
        reason: str,
        command_guild: Optional[discord.Guild] = None,
        evidence: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        appealable: bool = True,
        failed: bool = False,
        error_text: Optional[str] = None
    ):
        """Send cross-guild ban/unban log to that guild's configured log channel."""
        try:
            action_lower = action.lower()

            if action_lower == "ban":
                title = "🚫 EPN User Ban Failed" if failed else "🚫 EPN User Ban"
                color = EmbedDesign.ERROR
                description = (
                    f"{user.mention} ({user.id}) failed to ban by {staff_member.mention}"
                    if failed else
                    f"{user.mention} ({user.id}) was banned by {staff_member.mention}"
                )
            elif action_lower == "unban":
                title = "✅ EPN User Unban Failed" if failed else "✅ EPN User Unban"
                color = EmbedDesign.WARNING if failed else EmbedDesign.SUCCESS
                description = (
                    f"{user.mention} ({user.id}) failed to unban by {staff_member.mention}"
                    if failed else
                    f"{user.mention} ({user.id}) was unbanned by {staff_member.mention}"
                )
            else:
                title = f"EPN {action.title()}"
                color = EmbedDesign.WARNING
                description = f"{user.mention} ({user.id}) action `{action}` by {staff_member.mention}"

            embed = EmbedDesign.create_embed(
                title=title,
                description=description,
                color=color
            )

            embed.add_field(name="Reason", value=reason or "No reason provided", inline=False)

            if evidence:
                embed.add_field(name="Evidence", value=evidence[:1024], inline=False)

            if action_lower == "ban":
                if expires_at:
                    embed.add_field(
                        name="Expires",
                        value=f"<t:{int(expires_at.timestamp())}:F>",
                        inline=True
                    )
                else:
                    embed.add_field(name="Duration", value="Permanent", inline=True)

                embed.add_field(
                    name="Appeals",
                    value="Allowed" if appealable else "Not allowed",
                    inline=True
                )

            if command_guild:
                embed.add_field(
                    name="Command Run In",
                    value=f"{command_guild.name} ({command_guild.id})",
                    inline=False
                )

            if error_text:
                embed.add_field(name="Error", value=error_text[:1024], inline=False)

            await self.send_staff_log(guild, embed)

        except Exception as e:
            logger.error(f"Error sending cross-guild log in guild {guild.id}: {e}")

async def send_ban_notification(
    self,
    action: str,
    user: Union[discord.User, discord.Member],
    reason: str,
    staff_member: Union[discord.User, discord.Member],
    guild_name: Optional[str] = None,
    evidence: Optional[str] = None,
    expires_at: Optional[datetime] = None,
    appealable: bool = True
):
    """Send central main-server EPN notification."""
    try:
        notification_channel = self.bot.get_channel(constants.EPN_user_notification_channel_id())
        if not notification_channel:
            logger.error("Notification channel not found")
            return

        color = (
            EmbedDesign.ERROR if action.lower() == "ban"
            else EmbedDesign.SUCCESS if action.lower() == "unban"
            else EmbedDesign.WARNING
        )

        description_parts = [
            f"{user.mention} ({user.id}) was {action.lower()} in {guild_name or 'EPN'} by {staff_member.mention}"
        ]
        description_parts.append(f"**Reason:** {reason}")

        if evidence:
            description_parts.append(f"**Evidence:** {evidence}")

        if expires_at:
            description_parts.append(f"**Expires:** <t:{int(expires_at.timestamp())}:F>")

        if not appealable:
            description_parts.append("**Appeals:** Not allowed")

        if action.lower() == "ban":
            title = "🚫 EPN User Ban"
        elif action.lower() == "unban":
            title = "✅ EPN User Unban"
        elif action.lower() == "update":
            title = "📝 EPN Ban Update"
        else:
            title = f"EPN {action.title()}"

        embed = EmbedDesign.create_embed(
            title=title,
            description="\n".join(description_parts),
            color=color
        )

        await notification_channel.send(embed=embed)

    except Exception as e:
        logger.error(f"Error sending ban notification: {e}")
        
    async def send_server_ban_notification(
        self,
        action: str,
        guild_id: int,
        guild_name: str,
        reason: str,
        staff_member: Union[discord.User, discord.Member],
        evidence: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        appealable: bool = True
    ):
        """Send central server-ban notification."""
        try:
            notification_channel = self.bot.get_channel(constants.EPN_server_notification_channel_id())
            if not notification_channel:
                logger.error("Notification channel not found")
                return

            color = (
                EmbedDesign.ERROR if action.lower() in ["ban", "serverban"]
                else EmbedDesign.SUCCESS if action.lower() in ["unban", "serverunban"]
                else EmbedDesign.WARNING
            )

            description_parts = [
                f"Server **{guild_name}** (`{guild_id}`) was {action.lower()} by {staff_member.mention}"
            ]
            description_parts.append(f"**Reason:** {reason}")

            if evidence:
                description_parts.append(f"**Evidence:** {evidence}")

            if expires_at:
                description_parts.append(f"**Expires:** <t:{int(expires_at.timestamp())}:F>")
            else:
                description_parts.append("**Duration:** Permanent")

            if not appealable and action.lower() in ["ban", "serverban"]:
                description_parts.append("**Appeals:** Not allowed")
            elif action.lower() in ["ban", "serverban"]:
                description_parts.append("**Appeals:** Allowed")

            if action.lower() in ["serverban", "ban"]:
                title = "🚫 EPN Server Ban"
            elif action.lower() in ["serverunban", "unban"]:
                title = "✅ EPN Server Unban"
            else:
                title = f"EPN Server {action.title()}"

            embed = EmbedDesign.create_embed(
                title=title,
                description="\n".join(description_parts),
                color=color
            )

            await notification_channel.send(embed=embed)

        except Exception as e:
            logger.error(f"Error sending server ban notification: {e}")

    @commands.hybrid_group(name="epn", description="EPN moderation commands")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def EPN_group(self, ctx: commands.Context):
        """EPN moderation commands."""
        if not ctx.invoked_subcommand:
            embed = EmbedDesign.info(
                title="EPN Commands",
                description="Available EPN moderation commands:",
                fields=[
                    {"name": "ban", "value": "Ban a user across authorized servers except the main server", "inline": True},
                    {"name": "unban", "value": "Unban a user across authorized servers except the main server", "inline": True},
                    {"name": "serverban", "value": "Ban a server from EPN", "inline": True},
                    {"name": "serverunban", "value": "Unban a server from EPN", "inline": True},
                    {"name": "history", "value": "View ban history for a user", "inline": True},
                    {"name": "update", "value": "Update ban details", "inline": True},
                    {"name": "servers", "value": "List all servers the bot is in", "inline": True},
                    {"name": "authorize", "value": "Authorize a server for EPN access", "inline": True},
                    {"name": "deauthorize", "value": "Deauthorize a server from EPN access", "inline": True},
                    {"name": "authorized", "value": "List all authorized servers", "inline": True}
                ]
            )
            await ctx.reply(embed=embed, ephemeral=True)

    @EPN_group.command(name="ban", description="Ban a user across authorized servers except the main server")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @app_commands.describe(
        user="The user to ban",
        reason="Reason for the ban",
        evidence="Evidence supporting the ban (optional)",
        expires="When the ban expires (e.g. 1d, 2h, 30m)",
        appealable="Whether the ban can be appealed"
    )
    async def ban(
        self,
        ctx: commands.Context,
        user: Union[discord.Member, discord.User],
        reason: str = "No reason provided",
        evidence: Optional[str] = None,
        expires: Optional[str] = None,
        appealable: bool = True
    ):
        if not await self.bot.db.is_server_authorized(ctx.guild.id):
            await ctx.reply(
                embed=EmbedDesign.error(
                    title="Server Not Authorized",
                    description="This server is not authorized for EPN access. Only authorized servers can use EPN commands."
                ),
                ephemeral=True
            )
            return

        has_admin = ctx.author.guild_permissions.administrator
        has_staff = await StaffUtils.has_staff_permission_cross_guild(self.bot, ctx.author, "ban")

        if not (has_admin or has_staff):
            await ctx.reply(
                embed=EmbedDesign.error(
                    title="Permission Denied",
                    description="You must have either Administrator permissions in this server OR staff permissions to use EPN commands."
                ),
                ephemeral=True
            )
            return

        if has_admin and not has_staff:
            can_proceed, error_msg = await self.check_admin_rate_limit(ctx.author.id)
            if not can_proceed:
                await ctx.reply(
                    embed=EmbedDesign.error(title="Rate Limit Exceeded", description=error_msg),
                    ephemeral=True
                )
                return

        async def command_logic(interaction: discord.Interaction):
            try:
                if user.bot:
                    await interaction.followup.send(
                        embed=EmbedDesign.error(title="Invalid Target", description="You cannot ban bots."),
                        ephemeral=True
                    )
                    return

                if user.id == interaction.user.id:
                    await interaction.followup.send(
                        embed=EmbedDesign.error(title="Invalid Target", description="You cannot ban yourself."),
                        ephemeral=True
                    )
                    return

                target_is_core_staff = await StaffUtils.has_core_staff_permission_cross_guild(self.bot, user, "ban")
                if target_is_core_staff:
                    await interaction.followup.send(
                        embed=EmbedDesign.error(title="Protected User", description="You cannot ban staff members or developers."),
                        ephemeral=True
                    )
                    return

                if await self.bot.db.find_blacklist(user.id, active=True):
                    await interaction.followup.send(
                        embed=EmbedDesign.error(title="User Already Blacklisted", description="This user is already blacklisted."),
                        ephemeral=True
                    )
                    return

                expires_at = None
                if expires:
                    try:
                        expires_at = self.parse_duration(expires)
                    except ValueError as e:
                        await interaction.followup.send(
                            embed=EmbedDesign.error(title="Invalid Expiry Time", description=str(e)),
                            ephemeral=True
                        )
                        return

                await self.bot.db.insert_blacklist(
                    user.id,
                    reason,
                    evidence or "",
                    interaction.user.id,
                    expires_at,
                    appealable
                )

                if has_admin and not has_staff:
                    await self.admin_rate_limiter.record_request(interaction.user.id)

                authorized_servers = await self.bot.db.get_authorized_servers(limit=500)
                authorized_ids = {
                    int(server["guild_id"])
                    for server in authorized_servers
                    if server.get("guild_id")
                }

                logger.info(f"[EPN BAN] Authorized guild IDs: {sorted(authorized_ids)}")
                logger.info(f"[EPN BAN] Main server ID: {constants.main_server_id()}")

                banned_guilds = []
                failed_guilds = []

                for guild in self.bot.guilds:
                    if guild.id == constants.main_server_id():
                        continue
                    if guild.id not in authorized_ids:
                        continue

                    try:
                        await guild.ban(user, reason=f"EPN Blacklist: {reason}")
                        banned_guilds.append(guild.name)

                        await self.send_cross_guild_log(
                            guild=guild,
                            action="ban",
                            user=user,
                            staff_member=interaction.user,
                            reason=reason,
                            command_guild=interaction.guild,
                            evidence=evidence,
                            expires_at=expires_at,
                            appealable=appealable,
                            failed=False
                        )
                    except Exception as e:
                        failed_guilds.append(guild.name)
                        logger.error(f"Failed to ban user from {guild.name}: {e}")

                        await self.send_cross_guild_log(
                            guild=guild,
                            action="ban",
                            user=user,
                            staff_member=interaction.user,
                            reason=reason,
                            command_guild=interaction.guild,
                            evidence=evidence,
                            expires_at=expires_at,
                            appealable=appealable,
                            failed=True,
                            error_text=str(e)
                        )

                result_embed = EmbedDesign.success(
                    title="User Blacklisted",
                    description=f"**{user.display_name}** has been added to the EPN blacklist."
                )
                result_embed.add_field(name="Successful Guilds", value=str(len(banned_guilds)), inline=True)
                result_embed.add_field(name="Failed Guilds", value=str(len(failed_guilds)), inline=True)

                if banned_guilds:
                    result_embed.add_field(
                        name="Banned In",
                        value="\n".join(f"• {name}" for name in banned_guilds[:20]),
                        inline=False
                    )

                if failed_guilds:
                    result_embed.add_field(
                        name="Failed In",
                        value="\n".join(f"• {name}" for name in failed_guilds[:20]),
                        inline=False
                    )

                dm_embed = EmbedDesign.error(
                    title="You have been blacklisted in ER:LC Partner Network",
                    description=(
                        f"Hello, **{user.display_name}**. You have been banned from EPN.\n"
                        f"**Reason:** {reason}\n\n"
                        f"Appeal at: https://discord.gg/SKVuBHWKCP"
                    )
                )

                await interaction.followup.send(embed=result_embed)
                await user.send(embed=dm_embed)

                # Main server logging/notification
                await self.send_ban_notification(
                    action="ban",
                    user=user,
                    reason=reason,
                    staff_member=interaction.user,
                    guild_name=interaction.guild.name,
                    evidence=evidence,
                    expires_at=expires_at,
                    appealable=appealable
                )

            except Exception as e:
                logger.error(f"Error in ban command logic: {e}")
                await interaction.followup.send(
                    embed=EmbedDesign.error(
                        title="Ban Operation Failed",
                        description=f"Could not complete the ban operation: {str(e)}"
                    ),
                    ephemeral=True
                )

        await self.bot.command_verifier.verify_and_execute(ctx, command_logic)

    @EPN_group.command(name="unban", description="Unban a user across authorized servers except the main server")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @app_commands.describe(user="The user to unban", reason="Reason for the unban")
    async def unban(self, ctx: commands.Context, user: Union[discord.Member, discord.User], *, reason: str = "Appeal accepted"):
        if not await self.bot.db.is_server_authorized(ctx.guild.id):
            await ctx.reply(
                embed=EmbedDesign.error(
                    title="Server Not Authorized",
                    description="This server is not authorized for EPN access. Only authorized servers can use EPN commands."
                ),
                ephemeral=True
            )
            return

        has_admin = ctx.author.guild_permissions.administrator
        has_staff = await StaffUtils.has_staff_permission_cross_guild(self.bot, ctx.author, "ban")

        if not (has_admin or has_staff):
            await ctx.reply(
                embed=EmbedDesign.error(
                    title="Permission Denied",
                    description="You must have either Administrator permissions in this server OR staff permissions to use EPN commands."
                ),
                ephemeral=True
            )
            return

        if has_admin and not has_staff:
            can_proceed, error_msg = await self.check_admin_rate_limit(ctx.author.id)
            if not can_proceed:
                await ctx.reply(
                    embed=EmbedDesign.error(title="Rate Limit Exceeded", description=error_msg),
                    ephemeral=True
                )
                return

        async def command_logic(interaction: discord.Interaction):
            try:
                authorized_servers = await self.bot.db.get_authorized_servers(limit=500)
                authorized_ids = {
                    int(server["guild_id"])
                    for server in authorized_servers
                    if server.get("guild_id")
                }

                unbanned_guilds = []
                failed_guilds = []

                for guild in self.bot.guilds:
                    if guild.id == constants.main_server_id():
                        continue
                    if guild.id not in authorized_ids:
                        continue

                    try:
                        await guild.unban(user, reason=f"EPN Unblacklist: {reason}")
                        unbanned_guilds.append(guild.name)

                        await self.send_cross_guild_log(
                            guild=guild,
                            action="unban",
                            user=user,
                            staff_member=interaction.user,
                            reason=reason,
                            command_guild=interaction.guild,
                            failed=False
                        )
                    except discord.NotFound:
                        pass
                    except Exception as e:
                        failed_guilds.append(guild.name)
                        logger.error(f"Failed to unban user from {guild.name}: {e}")

                        await self.send_cross_guild_log(
                            guild=guild,
                            action="unban",
                            user=user,
                            staff_member=interaction.user,
                            reason=reason,
                            command_guild=interaction.guild,
                            failed=True,
                            error_text=str(e)
                        )

                active_ban = await self.bot.db.find_blacklist(user.id, active=True, use_cache=False)
                result = False
                if active_ban:
                    result = await self.bot.db.deactivate_blacklist(user.id, interaction.user.id, reason)

                if not active_ban:
                    latest_ban = await self.bot.db.get_blacklist_status(user.id)
                    if latest_ban:
                        await interaction.followup.send(
                            embed=EmbedDesign.warning(
                                title="No Active Ban Record",
                                description="User unbanned, but their latest database ban record is already inactive."
                            ),
                            ephemeral=True
                        )
                    else:
                        await interaction.followup.send(
                            embed=EmbedDesign.warning(
                                title="No Ban Record Found",
                                description="User unbanned, but no database ban record exists for this user."
                            ),
                            ephemeral=True
                        )
                    return

                if not result:
                    await interaction.followup.send(
                        embed=EmbedDesign.error(
                            title="Database Update Failed",
                            description="An active ban record was found, but it could not be updated."
                        ),
                        ephemeral=True
                    )
                    return

                if has_admin and not has_staff:
                    await self.admin_rate_limiter.record_request(interaction.user.id)

                result_embed = EmbedDesign.success(
                    title="User Unbanned",
                    description=f"{user.mention} was unbanned by {interaction.user.mention}."
                )
                result_embed.add_field(name="Successful Guilds", value=str(len(unbanned_guilds)), inline=True)
                result_embed.add_field(name="Failed Guilds", value=str(len(failed_guilds)), inline=True)

                if unbanned_guilds:
                    result_embed.add_field(
                        name="Unbanned In",
                        value="\n".join(f"• {name}" for name in unbanned_guilds[:20]),
                        inline=False
                    )

                if failed_guilds:
                    result_embed.add_field(
                        name="Failed In",
                        value="\n".join(f"• {name}" for name in failed_guilds[:20]),
                        inline=False
                    )

                dm_embed = EmbedDesign.success(
                    title="You have been unblacklisted in ER:LC Partner Network",
                    description=(
                        f"Hello, **{user.display_name}**. You have been unbanned from EPN.\n"
                        f"**Reason:** {reason}\n\n"
                        f"You may rejoin our servers at: https://discord.gg/SKVuBHWKCP"
                    )
                )

                await interaction.followup.send(embed=result_embed)
                await user.send(embed=dm_embed)

                # Main server logging/notification
                await self.send_ban_notification(
                    action="unban",
                    user=user,
                    reason=reason,
                    staff_member=interaction.user,
                    guild_name=interaction.guild.name
                )

            except Exception as e:
                logger.error(f"Error in unban command logic: {e}")
                await interaction.followup.send(
                    embed=EmbedDesign.error(
                        title="Unban Operation Failed",
                        description=f"Could not complete the unban operation: {str(e)}"
                    ),
                    ephemeral=True
                )

        await self.bot.command_verifier.verify_and_execute(ctx, command_logic)

    @EPN_group.command(name="history", description="View ban history for a user")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @app_commands.describe(user="The user to check history for")
    async def history(self, ctx: commands.Context, user: Union[discord.Member, discord.User]):
        if not await self.bot.db.is_server_authorized(ctx.guild.id):
            await ctx.reply(
                embed=EmbedDesign.error(
                    title="Server Not Authorized",
                    description="This server is not authorized for EPN access. Only authorized servers can use EPN commands."
                ),
                ephemeral=True
            )
            return

        has_admin = ctx.author.guild_permissions.administrator
        has_staff = await StaffUtils.has_staff_permission_cross_guild(self.bot, ctx.author, "ban")

        if not (has_admin or has_staff):
            await ctx.reply(
                embed=EmbedDesign.error(
                    title="Permission Denied",
                    description="You must have either Administrator permissions in this server OR staff permissions to use EPN commands."
                ),
                ephemeral=True
            )
            return

        blacklist_records = await self.bot.db.find_all_blacklist_by_user(user.id, limit=10)

        if not blacklist_records:
            await ctx.reply(
                embed=EmbedDesign.info(
                    title="No History Found",
                    description=f"No ban history found for **{user.display_name}**."
                ),
                ephemeral=True
            )
            return

        embed = EmbedDesign.info(
            title=f"Ban History for {user.display_name}",
            description=f"User ID: `{user.id}`\nShowing {len(blacklist_records)} most recent ban record(s)"
        )
        embed.set_thumbnail(url=user.display_avatar.url)

        for i, record in enumerate(blacklist_records, 1):
            status = "🔴 Active" if record.get("active", False) else "🟢 Inactive"
            reason = record.get("reason", "No reason provided")
            evidence = record.get("evidence", "")
            appealable = record.get("appeal_allowed", True)

            timestamp = record.get("timestamp")
            expires_at = record.get("expires_at")
            updated_at = record.get("updated_at")

            field_lines = [f"**Status:** {status}", f"**Reason:** {reason}"]

            if evidence:
                evidence_display = evidence if len(evidence) <= 100 else evidence[:97] + "..."
                field_lines.append(f"**Evidence:** {evidence_display}")

            if timestamp:
                field_lines.append(f"**Banned:** <t:{int(timestamp.timestamp())}:F>")

            if expires_at:
                now = datetime.utcnow()
                if expires_at > now:
                    field_lines.append(f"**Expires:** <t:{int(expires_at.timestamp())}:F>")
                    time_left = expires_at - now
                    if time_left.days > 0:
                        field_lines.append(f"**Time Left:** {time_left.days}d {time_left.seconds // 3600}h")
                    elif time_left.seconds > 3600:
                        field_lines.append(f"**Time Left:** {time_left.seconds // 3600}h {(time_left.seconds % 3600) // 60}m")
                    else:
                        field_lines.append(f"**Time Left:** {time_left.seconds // 60}m")
                else:
                    field_lines.append(f"**Expired:** <t:{int(expires_at.timestamp())}:F>")
            else:
                field_lines.append("**Duration:** Permanent")

            if updated_at:
                field_lines.append(f"**Last Updated:** <t:{int(updated_at.timestamp())}:R>")

            appeal_status = "✅ Allowed" if appealable else "❌ Not Allowed"
            field_lines.append(f"**Appeals:** {appeal_status}")

            banned_by_id = record.get("blacklisted_by")
            if banned_by_id:
                try:
                    banned_by_user = await self.bot.fetch_user(banned_by_id)
                    field_lines.append(f"**Banned By:** {banned_by_user.mention}")
                except Exception:
                    field_lines.append(f"**Banned By:** <@{banned_by_id}>")

            updated_by_id = record.get("updated_by")
            if updated_by_id and updated_by_id != banned_by_id:
                try:
                    updated_by_user = await self.bot.fetch_user(updated_by_id)
                    field_lines.append(f"**Updated By:** {updated_by_user.mention}")
                except Exception:
                    field_lines.append(f"**Updated By:** <@{updated_by_id}>")

            embed.add_field(
                name=f"Ban Record #{record.get('id', i)}",
                value="\n".join(field_lines),
                inline=False
            )

        active_count = sum(1 for r in blacklist_records if r.get("active", False))
        embed.set_footer(text=f"Active bans: {active_count}/{len(blacklist_records)} • Use /epn update to modify active bans")

        await ctx.reply(embed=embed, ephemeral=True)

    @EPN_group.command(name="update", description="Update ban details")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @app_commands.describe(
        user="The user to update",
        new_reason="New reason for the ban",
        new_evidence="New evidence for the ban (optional)",
        new_expires="New expiry time (e.g. 1d, 2h, 30m)",
        new_appealable="Whether the ban can be appealed (optional)"
    )
    async def update(
        self,
        ctx: commands.Context,
        user: Union[discord.Member, discord.User],
        new_reason: str,
        new_evidence: Optional[str] = None,
        new_expires: Optional[str] = None,
        new_appealable: Optional[bool] = None
    ):
        if not await self.bot.db.is_server_authorized(ctx.guild.id):
            await ctx.reply(
                embed=EmbedDesign.error(
                    title="Server Not Authorized",
                    description="This server is not authorized for EPN access. Only authorized servers can use EPN commands."
                ),
                ephemeral=True
            )
            return

        has_admin = ctx.author.guild_permissions.administrator
        has_staff = await StaffUtils.has_staff_permission_cross_guild(self.bot, ctx.author, "ban")

        if not (has_admin or has_staff):
            await ctx.reply(
                embed=EmbedDesign.error(
                    title="Permission Denied",
                    description="You must have either Administrator permissions in this server OR staff permissions to use EPN commands."
                ),
                ephemeral=True
            )
            return

        if has_admin and not has_staff:
            can_proceed, error_msg = await self.check_admin_rate_limit(ctx.author.id)
            if not can_proceed:
                await ctx.reply(
                    embed=EmbedDesign.error(title="Rate Limit Exceeded", description=error_msg),
                    ephemeral=True
                )
                return

        async def command_logic(interaction: discord.Interaction):
            try:
                current_record = await self.bot.db.find_blacklist(user.id, active=True, use_cache=False)

                if not current_record:
                    all_records = await self.bot.db.find_all_blacklist_by_user(user.id, limit=5)
                    if all_records:
                        embed = EmbedDesign.warning(
                            title="No Active Ban",
                            description=f"User {user.display_name} has ban history but no active ban. Cannot update inactive bans."
                        )
                    else:
                        embed = EmbedDesign.error(
                            title="Not Found",
                            description=f"No ban records found for {user.display_name}."
                        )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

                old_reason = current_record.get("reason", "No reason provided")
                old_evidence = current_record.get("evidence", "")
                old_expires = current_record.get("expires_at")
                old_appealable = current_record.get("appeal_allowed", True)

                new_expires_at = None
                if new_expires:
                    try:
                        new_expires_at = self.parse_duration(new_expires)
                    except ValueError as e:
                        await interaction.followup.send(
                            embed=EmbedDesign.error(title="Invalid Expiry Time", description=str(e)),
                            ephemeral=True
                        )
                        return

                update_data = {"reason": new_reason}
                if new_evidence is not None:
                    update_data["evidence"] = new_evidence
                if new_expires_at is not None:
                    update_data["expires_at"] = new_expires_at
                if new_appealable is not None:
                    update_data["appeal_allowed"] = new_appealable

                try:
                    if len(update_data) == 1 and "reason" in update_data:
                        result = await self.bot.db.update_blacklist_reason(user.id, new_reason, interaction.user.id)
                    else:
                        result = await self.bot.db.update_blacklist_full(user.id, interaction.user.id, **update_data)

                    if has_admin and not has_staff:
                        await self.admin_rate_limiter.record_request(interaction.user.id)
                except Exception as e:
                    logger.error(f"EPN Update - Database error for user {user.id}: {e}")
                    await interaction.followup.send(
                        embed=EmbedDesign.error(
                            title="Database Error",
                            description="Failed to update ban details due to a database error."
                        ),
                        ephemeral=True
                    )
                    return

                if not result:
                    await interaction.followup.send(
                        embed=EmbedDesign.error(
                            title="Update Failed",
                            description="Failed to update ban details. The ban may have been modified by another user."
                        ),
                        ephemeral=True
                    )
                    return

                fields = []
                changes = []

                if old_reason.strip() != new_reason.strip():
                    fields.append({
                        "name": "Reason",
                        "value": f"**Old:** {old_reason.strip()}\n**New:** {new_reason.strip()}",
                        "inline": False
                    })
                    changes.append(f"reason: {old_reason.strip()} → {new_reason.strip()}")

                if new_evidence is not None and old_evidence.strip() != new_evidence.strip():
                    fields.append({
                        "name": "Evidence",
                        "value": f"**Old:** {old_evidence.strip() or 'None'}\n**New:** {new_evidence.strip() or 'None'}",
                        "inline": False
                    })
                    changes.append(f"evidence: {old_evidence.strip() or 'None'} → {new_evidence.strip() or 'None'}")

                if new_expires_at is not None:
                    old_expires_str = f"<t:{int(old_expires.timestamp())}:F>" if old_expires else "Permanent"
                    new_expires_str = f"<t:{int(new_expires_at.timestamp())}:F>" if new_expires_at else "Permanent"
                    fields.append({
                        "name": "Expires",
                        "value": f"**Old:** {old_expires_str}\n**New:** {new_expires_str}",
                        "inline": False
                    })
                    changes.append(f"expires: {old_expires_str} → {new_expires_str}")

                if new_appealable is not None and old_appealable != new_appealable:
                    old_appeal_str = "Allowed" if old_appealable else "Not Allowed"
                    new_appeal_str = "Allowed" if new_appealable else "Not Allowed"
                    fields.append({
                        "name": "Appeals",
                        "value": f"**Old:** {old_appeal_str}\n**New:** {new_appeal_str}",
                        "inline": False
                    })
                    changes.append(f"appeals: {old_appeal_str} → {new_appeal_str}")

                fields.append({"name": "Updated by", "value": interaction.user.mention, "inline": True})

                embed = EmbedDesign.success(
                    title="Ban Updated",
                    description=f"Ban details updated for {user.display_name}",
                    fields=fields
                )
                await interaction.followup.send(embed=embed)

                changes_text = " | ".join(changes) if changes else f"reason: {old_reason} → {new_reason}"
                await self.send_ban_notification(
                    action="update",
                    user=user,
                    reason=f"Updated: {changes_text}",
                    staff_member=interaction.user,
                    guild_name=interaction.guild.name
                )

            except Exception as e:
                logger.error(f"Error in update command logic: {e}")
                await interaction.followup.send(
                    embed=EmbedDesign.error(
                        title="Update Operation Failed",
                        description=f"Could not complete the update operation: {str(e)}"
                    ),
                    ephemeral=True
                )

        await self.bot.command_verifier.verify_and_execute(ctx, command_logic)

    @EPN_group.command(name="serverban", description="Ban a server from EPN")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @app_commands.describe(
        guild_id="The guild ID to ban",
        reason="Reason for the server ban",
        evidence="Evidence for the ban",
        expires="When the ban expires",
        appealable="Whether the ban can be appealed"
    )
    async def server_ban(
        self,
        ctx: commands.Context,
        guild_id: str,
        reason: str = "No reason provided",
        evidence: Optional[str] = None,
        expires: Optional[str] = None,
        appealable: bool = True
    ):
        if not await self.bot.db.is_server_authorized(ctx.guild.id):
            await ctx.reply(
                embed=EmbedDesign.error(
                    title="Server Not Authorized",
                    description="This server is not authorized for EPN access. Only authorized servers can use EPN commands."
                ),
                ephemeral=True
            )
            return

        async def command_logic(interaction: discord.Interaction):
            try:
                if not await StaffUtils.has_staff_permission_cross_guild(self.bot, interaction.user, "ban"):
                    await interaction.followup.send(
                        embed=EmbedDesign.error(title="Permission Denied", description="You don't have permission to ban servers."),
                        ephemeral=True
                    )
                    return

                try:
                    guild_id_int = int(guild_id)
                except ValueError:
                    await interaction.followup.send(
                        embed=EmbedDesign.error(title="Invalid Guild ID", description="Please provide a valid numeric guild ID."),
                        ephemeral=True
                    )
                    return

                if await self.bot.db.find_server_ban(guild_id_int, active=True):
                    await interaction.followup.send(
                        embed=EmbedDesign.error(title="Server Already Banned", description="This server is already banned."),
                        ephemeral=True
                    )
                    return

                guild = self.bot.get_guild(guild_id_int)
                guild_name = guild.name if guild else "Unknown Server"

                expires_at = None
                if expires:
                    try:
                        expires_at = self.parse_duration(expires)
                    except ValueError as e:
                        await interaction.followup.send(
                            embed=EmbedDesign.error(title="Invalid Expiry Time", description=str(e)),
                            ephemeral=True
                        )
                        return

                await self.bot.db.insert_server_ban(
                    guild_id_int,
                    guild_name,
                    reason,
                    evidence or "",
                    interaction.user.id,
                    expires_at,
                    appealable
                )

                await interaction.followup.send(
                    embed=EmbedDesign.success(title="Server Banned", description=f"**{guild_name}** has been banned from EPN."),
                    ephemeral=True
                )

                await self.send_server_ban_notification(
                    action="serverban",
                    guild_id=guild_id_int,
                    guild_name=guild_name,
                    reason=reason,
                    staff_member=interaction.user,
                    evidence=evidence,
                    expires_at=expires_at,
                    appealable=appealable
                )

            except Exception as e:
                logger.error(f"Error in server_ban command logic: {e}")
                await interaction.followup.send(
                    embed=EmbedDesign.error(
                        title="Server Ban Operation Failed",
                        description=f"Could not complete the server ban operation: {str(e)}"
                    ),
                    ephemeral=True
                )

        await self.bot.command_verifier.verify_and_execute(ctx, command_logic)

    @EPN_group.command(name="serverunban", description="Unban a server from EPN")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @app_commands.describe(guild_id="The guild ID to unban", reason="Reason for the unban")
    async def server_unban(self, ctx: commands.Context, guild_id: str, *, reason: str = "Appeal accepted"):
        if not await self.bot.db.is_server_authorized(ctx.guild.id):
            await ctx.reply(
                embed=EmbedDesign.error(
                    title="Server Not Authorized",
                    description="This server is not authorized for EPN access. Only authorized servers can use EPN commands."
                ),
                ephemeral=True
            )
            return

        async def command_logic(interaction: discord.Interaction):
            try:
                if not await StaffUtils.has_staff_permission_cross_guild(self.bot, interaction.user, "ban"):
                    await interaction.followup.send(
                        embed=EmbedDesign.error(title="Permission Denied", description="You don't have permission to unban servers."),
                        ephemeral=True
                    )
                    return

                try:
                    guild_id_int = int(guild_id)
                except ValueError:
                    await interaction.followup.send(
                        embed=EmbedDesign.error(title="Invalid Guild ID", description="Please provide a valid numeric guild ID."),
                        ephemeral=True
                    )
                    return

                server_ban = await self.bot.db.find_server_ban(guild_id_int, active=True)
                if not server_ban:
                    await interaction.followup.send(
                        embed=EmbedDesign.error(title="Server Not Banned", description="This server is not currently banned."),
                        ephemeral=True
                    )
                    return

                result = await self.bot.db.deactivate_server_ban(guild_id_int, interaction.user.id, reason)
                if not result:
                    await interaction.followup.send(
                        embed=EmbedDesign.error(title="Database Error", description="Failed to update server ban record."),
                        ephemeral=True
                    )
                    return

                guild_name = server_ban.get("guild_name", "Unknown Server")
                await interaction.followup.send(
                    embed=EmbedDesign.success(title="Server Unbanned", description=f"**{guild_name}** has been unbanned from EPN."),
                    ephemeral=True
                )

                await self.send_server_ban_notification(
                    action="serverunban",
                    guild_id=guild_id_int,
                    guild_name=guild_name,
                    reason=reason,
                    staff_member=interaction.user
                )

            except Exception as e:
                logger.error(f"Error in server_unban command logic: {e}")
                await interaction.followup.send(
                    embed=EmbedDesign.error(
                        title="Server Unban Operation Failed",
                        description=f"Could not complete the server unban operation: {str(e)}"
                    ),
                    ephemeral=True
                )

        await self.bot.command_verifier.verify_and_execute(ctx, command_logic)

    @EPN_group.command(name="servers", description="List all servers the bot is in")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def servers(self, ctx: commands.Context):
        if not await StaffUtils.has_developer_permission_cross_guild(self.bot, ctx.author, "ban"):
            await ctx.reply(
                embed=EmbedDesign.error(
                    title="Permission Denied",
                    description="You don't have permission to view servers. This requires Developer access."
                ),
                ephemeral=True
            )
            return

        guilds = sorted(self.bot.guilds, key=lambda g: g.member_count or 0, reverse=True)

        lines = []
        for g in guilds:
            owner = f"<@{g.owner_id}>" if g.owner_id else "Unknown"
            lines.append(f"• {g.name} ({g.id}) — Members: {g.member_count or 0} — Owner: {owner}")

        page_size = 15
        pages = [lines[i:i + page_size] for i in range(0, len(lines), page_size)] or [[]]

        from utils.pagination import Paginator

        embeds = []
        total = len(guilds)
        for idx, chunk in enumerate(pages, 1):
            embed = EmbedDesign.info(
                title="Bot Servers",
                description=f"Total: {total} servers\n\n" + ("\n".join(chunk) if chunk else "No servers found.")
            )
            embed.set_footer(text=f"Page {idx}/{len(pages)}")
            embeds.append(embed)

        view = Paginator(ctx.author, embeds)
        await ctx.reply(embed=embeds[0], view=view)

    @EPN_group.command(name="authorize", description="Authorize a server for EPN access")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @app_commands.describe(guild_id="The guild ID to authorize", reason="Reason for authorization (optional)")
    async def authorize_server(self, ctx: commands.Context, guild_id: str, *, reason: Optional[str] = None):
        async def command_logic(interaction: discord.Interaction):
            try:
                if not await StaffUtils.has_developer_permission_cross_guild(self.bot, interaction.user, "manage_guild"):
                    await interaction.followup.send(
                        embed=EmbedDesign.error(
                            title="Permission Denied",
                            description="You don't have permission to authorize servers. This requires EPN Developer access."
                        ),
                        ephemeral=True
                    )
                    return

                try:
                    guild_id_int = int(guild_id)
                except ValueError:
                    await interaction.followup.send(
                        embed=EmbedDesign.error(title="Invalid Guild ID", description="Please provide a valid numeric guild ID."),
                        ephemeral=True
                    )
                    return

                try:
                    guild = await self.bot.fetch_guild(guild_id_int)
                    guild_name = guild.name if guild else "Unknown Server"
                except Exception:
                    guild_name = "Unknown Server"

                if await self.bot.db.is_server_authorized(guild_id_int):
                    await interaction.followup.send(
                        embed=EmbedDesign.warning(
                            title="Already Authorized",
                            description=f"Server **{guild_name}** is already authorized for EPN access."
                        ),
                        ephemeral=True
                    )
                    return

                await self.bot.db.authorize_server(guild_id_int, guild_name, interaction.user.id, reason)

                await interaction.followup.send(
                    embed=EmbedDesign.success(
                        title="Server Authorized",
                        description=f"**{guild_name}** has been authorized for EPN access.",
                        fields=[
                            {"name": "Guild ID", "value": str(guild_id_int), "inline": True},
                            {"name": "Authorized by", "value": interaction.user.mention, "inline": True},
                            {"name": "Reason", "value": reason or "No reason provided", "inline": False}
                        ]
                    )
                )

            except Exception as e:
                logger.error(f"Error in authorize_server command logic: {e}")
                await interaction.followup.send(
                    embed=EmbedDesign.error(
                        title="Authorization Operation Failed",
                        description=f"Could not complete the authorization operation: {str(e)}"
                    ),
                    ephemeral=True
                )

        await self.bot.command_verifier.verify_and_execute(ctx, command_logic)

    @EPN_group.command(name="deauthorize", description="Deauthorize a server from EPN access")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @app_commands.describe(guild_id="The guild ID to deauthorize", reason="Reason for deauthorization (optional)")
    async def deauthorize_server(self, ctx: commands.Context, guild_id: str, *, reason: Optional[str] = None):
        async def command_logic(interaction: discord.Interaction):
            try:
                if not await StaffUtils.has_developer_permission_cross_guild(self.bot, interaction.user, "manage_guild"):
                    await interaction.followup.send(
                        embed=EmbedDesign.error(
                            title="Permission Denied",
                            description="You don't have permission to deauthorize servers. This requires EPN Developer access."
                        ),
                        ephemeral=True
                    )
                    return

                try:
                    guild_id_int = int(guild_id)
                except ValueError:
                    await interaction.followup.send(
                        embed=EmbedDesign.error(title="Invalid Guild ID", description="Please provide a valid numeric guild ID."),
                        ephemeral=True
                    )
                    return

                auth_info = await self.bot.db.get_server_authorization(guild_id_int)
                if not auth_info:
                    await interaction.followup.send(
                        embed=EmbedDesign.warning(
                            title="Not Authorized",
                            description=f"Server with ID `{guild_id_int}` is not currently authorized for EPN access."
                        ),
                        ephemeral=True
                    )
                    return

                result = await self.bot.db.deauthorize_server(guild_id_int, interaction.user.id, reason)

                if result:
                    embed = EmbedDesign.success(
                        title="Server Deauthorized",
                        description=f"**{auth_info.get('guild_name', 'Unknown Server')}** has been deauthorized from EPN access.",
                        fields=[
                            {"name": "Guild ID", "value": str(guild_id_int), "inline": True},
                            {"name": "Deauthorized by", "value": interaction.user.mention, "inline": True},
                            {"name": "Reason", "value": reason or "No reason provided", "inline": False}
                        ]
                    )
                else:
                    embed = EmbedDesign.error(
                        title="Deauthorization Failed",
                        description="Failed to deauthorize the server. Please try again."
                    )

                await interaction.followup.send(embed=embed)

            except Exception as e:
                logger.error(f"Error in deauthorize_server command logic: {e}")
                await interaction.followup.send(
                    embed=EmbedDesign.error(
                        title="Deauthorization Operation Failed",
                        description=f"Could not complete the deauthorization operation: {str(e)}"
                    ),
                    ephemeral=True
                )

        await self.bot.command_verifier.verify_and_execute(ctx, command_logic)

    @EPN_group.command(name="authorized", description="List all authorized servers")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def list_authorized_servers(self, ctx: commands.Context):
        if not await StaffUtils.has_developer_permission_cross_guild(self.bot, ctx.author, "manage_guild"):
            await ctx.reply(
                embed=EmbedDesign.error(
                    title="Permission Denied",
                    description="You don't have permission to view authorized servers. This requires EPN Developer access."
                ),
                ephemeral=True
            )
            return

        authorized_servers = await self.bot.db.get_authorized_servers(limit=100)

        if not authorized_servers:
            await ctx.reply(
                embed=EmbedDesign.info(
                    title="No Authorized Servers",
                    description="There are currently no authorized servers for EPN access."
                ),
                ephemeral=True
            )
            return

        lines = []
        for server in authorized_servers:
            guild_id = server.get("guild_id")
            guild_name = server.get("guild_name", "Unknown Server")
            authorized_at = server.get("authorized_at")
            reason_text = server.get("reason", "No reason provided")

            timestamp_str = f"<t:{int(authorized_at.timestamp())}:R>" if authorized_at else "Unknown"
            line = f"• **{guild_name}** (`{guild_id}`) — {timestamp_str}"

            if reason_text and reason_text != "No reason provided":
                short_reason = reason_text[:50] + ("..." if len(reason_text) > 50 else "")
                line += f" — *{short_reason}*"

            lines.append(line)

        page_size = 10
        pages = [lines[i:i + page_size] for i in range(0, len(lines), page_size)] or [[]]

        from utils.pagination import Paginator

        embeds = []
        total = len(authorized_servers)
        for idx, chunk in enumerate(pages, 1):
            embed = EmbedDesign.info(
                title="Authorized Servers",
                description=f"Total: {total} authorized servers\n\n" + ("\n".join(chunk) if chunk else "No servers found.")
            )
            embed.set_footer(text=f"Page {idx}/{len(pages)}")
            embeds.append(embed)

        view = Paginator(ctx.author, embeds)
        await ctx.reply(embed=embeds[0], view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(EPNCommands(bot))
