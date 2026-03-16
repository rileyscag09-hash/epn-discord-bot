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
        duration_str = duration_str.strip().lower()
        match = re.match(r'^(\d+)([dhms])$', duration_str)

        if not match:
            raise ValueError(
                f"Invalid duration format: {duration_str}. Use format like '1d', '2h', '30m', '45s'"
            )

        value, unit = match.groups()
        value = int(value)

        if unit == 's':
            seconds = value
        elif unit == 'm':
            seconds = value * 60
        elif unit == 'h':
            seconds = value * 3600
        elif unit == 'd':
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
                time_str = f"{wait_minutes}m {wait_seconds}s" if wait_minutes > 0 else f"{wait_seconds}s"
                error_msg = f"You have reached the rate limit for EPN commands (3 per hour). Try again in {time_str}."
            else:
                error_msg = f"You have reached the rate limit for EPN commands (3 per hour). {remaining} requests remaining."

            return False, error_msg

        return True, None

    async def _safe_dm_user(self, user: Union[discord.User, discord.Member], embed: discord.Embed):
        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            logger.info(f"Could not DM user {user} ({user.id})")
        except Exception as e:
            logger.error(f"Error sending DM to user {user.id}: {e}")

    async def send_staff_log(self, guild: discord.Guild, embed: discord.Embed):
        """Send to the configured log channel for this guild."""
        try:
            log_config = await self.bot.db.find_log_config(guild.id)

            if log_config:
                channel = guild.get_channel(log_config["channel_id"])
                if channel and isinstance(channel, discord.TextChannel):
                    await channel.send(embed=embed)
                    return

            logger.warning(f"No valid configured log channel found for guild {guild.name} ({guild.id})")

        except Exception as e:
            logger.error(f"Error sending staff log for guild {guild.id}: {e}")

    async def log_cross_guild_action(
        self,
        action: str,
        guild: discord.Guild,
        user: Union[discord.User, discord.Member],
        moderator: Union[discord.User, discord.Member],
        reason: str,
        evidence: str = None,
        expires_at: datetime = None,
        appealable: bool = True,
        failed: bool = False,
        error_text: str = None
    ):
        """Log cross-guild ban/unban to that guild's configured log channel."""
        try:
            if action.lower() == "ban":
                title = "🚫 EPN User Ban Failed" if failed else "🚫 EPN User Ban"
                color = EmbedDesign.ERROR
                description = (
                    f"{user.mention} ({user.id}) failed to ban in Cross-Guild Ban by {moderator.mention}"
                    if failed else
                    f"{user.mention} ({user.id}) was banned in Cross-Guild Ban by {moderator.mention}"
                )
            else:
                title = "✅ EPN User Unban Failed" if failed else "✅ EPN User Unban"
                color = EmbedDesign.WARNING if failed else EmbedDesign.SUCCESS
                description = (
                    f"{user.mention} ({user.id}) failed to unban in Cross-Guild Unban by {moderator.mention}"
                    if failed else
                    f"{user.mention} ({user.id}) was unbanned in Cross-Guild Unban by {moderator.mention}"
                )

            parts = [description, f"**Reason:** {reason}"]

            if evidence:
                parts.append(f"**Evidence:** {evidence}")

            if action.lower() == "ban":
                if expires_at:
                    parts.append(f"**Expires:** <t:{int(expires_at.timestamp())}:F>")
                else:
                    parts.append("**Duration:** Permanent")
                parts.append(f"**Appeals:** {'Allowed' if appealable else 'Not allowed'}")

            if error_text:
                parts.append(f"**Error:** {error_text[:1000]}")

            embed = EmbedDesign.create_embed(
                title=title,
                description="\n".join(parts),
                color=color
            )

            await self.send_staff_log(guild, embed)

        except Exception as e:
            logger.error(f"Error logging cross-guild action in {guild.name}: {e}")

    async def send_ban_notification(
        self,
        action: str,
        user: Union[discord.User, discord.Member],
        reason: str,
        staff_member: discord.Member,
        guild_name: str = None,
        evidence: str = None,
        expires_at: datetime = None,
        appealable: bool = True
    ):
        """Central EPN notification channel."""
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

    @commands.hybrid_group(name="epn", description="EPN moderation commands")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def EPN_group(self, ctx: commands.Context):
        if not ctx.invoked_subcommand:
            embed = EmbedDesign.info(
                title="EPN Commands",
                description="Available EPN moderation commands:"
            )
            await ctx.reply(embed=embed, ephemeral=True)

    @EPN_group.command(name="ban", description="Ban a user across all authorized guilds")
    @app_commands.describe(
        user="The user to ban",
        reason="Reason for the ban",
        evidence="Evidence supporting the ban (optional)",
        expires="When the ban expires (e.g., '1d', '2h', '30m' - optional)",
        appealable="Whether the ban can be appealed (default: True)"
    )
    async def ban(
        self,
        ctx: commands.Context,
        user: Union[discord.Member, discord.User],
        reason: str = "No reason provided",
        evidence: str = None,
        expires: str = None,
        appealable: bool = True
    ):
        if not await self.bot.db.is_server_authorized(ctx.guild.id):
            embed = EmbedDesign.error(
                title="Server Not Authorized",
                description="This server is not authorized for EPN access."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return

        has_admin = ctx.author.guild_permissions.administrator
        has_staff = await StaffUtils.has_staff_permission_cross_guild(self.bot, ctx.author, "ban")

        if not (has_admin or has_staff):
            embed = EmbedDesign.error(
                title="Permission Denied",
                description="You must have Administrator or staff permissions to use this command."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return

        async def command_logic(interaction: discord.Interaction):
            try:
                if user.bot:
                    await interaction.followup.send(
                        embed=EmbedDesign.error(title="Invalid Target", description="You cannot ban bots."),
                        ephemeral=True
                    )
                    return

                if user == interaction.user:
                    await interaction.followup.send(
                        embed=EmbedDesign.error(title="Invalid Target", description="You cannot ban yourself."),
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

                authorized_servers = await self.bot.db.get_authorized_servers(limit=500)
                authorized_ids = {server["guild_id"] for server in authorized_servers}

                banned_guilds = []
                failed_guilds = []

                for guild in self.bot.guilds:
                    if guild.id not in authorized_ids:
                        continue

                    try:
                        await guild.ban(user, reason=f"EPN Blacklist: {reason}")
                        banned_guilds.append(guild.name)

                        await self.log_cross_guild_action(
                            action="ban",
                            guild=guild,
                            user=user,
                            moderator=interaction.user,
                            reason=reason,
                            evidence=evidence,
                            expires_at=expires_at,
                            appealable=appealable,
                            failed=False
                        )

                    except Exception as e:
                        failed_guilds.append(guild.name)
                        logger.error(f"Failed to ban user from {guild.name}: {e}")

                        await self.log_cross_guild_action(
                            action="ban",
                            guild=guild,
                            user=user,
                            moderator=interaction.user,
                            reason=reason,
                            evidence=evidence,
                            expires_at=expires_at,
                            appealable=appealable,
                            failed=True,
                            error_text=str(e)
                        )

                embed = EmbedDesign.success(
                    title="User Blacklisted",
                    description=f"**{user.display_name}** has been added to the EPN blacklist."
                )
                embed.add_field(name="Successful Guilds", value=str(len(banned_guilds)), inline=True)
                embed.add_field(name="Failed Guilds", value=str(len(failed_guilds)), inline=True)

                await interaction.followup.send(embed=embed)

                dm_embed = EmbedDesign.create_embed(
                    title="You have been blacklisted in ER:LC Partner Network",
                    description=(
                        f"Hello, **{user.display_name}**. You have been banned from EPN.\n"
                        f"**Reason:** {reason}\n\n"
                        f"Appeal at: https://discord.gg/SKVuBHWKCP"
                    )
                )
                await self._safe_dm_user(user, dm_embed)

                await self.send_ban_notification(
                    "ban",
                    user,
                    reason,
                    interaction.user,
                    "Cross-Guild Ban",
                    evidence,
                    expires_at,
                    appealable
                )

            except Exception as e:
                logger.error(f"Error in ban command logic: {e}")
                await interaction.followup.send(
                    embed=EmbedDesign.error("Ban Operation Failed", f"Could not complete the ban operation: {str(e)}"),
                    ephemeral=True
                )

        await self.bot.command_verifier.verify_and_execute(ctx, command_logic)

    @EPN_group.command(name="unban", description="Unban a user across all authorized guilds")
    @app_commands.describe(user="The user to unban", reason="Reason for the unban")
    async def unban(self, ctx: commands.Context, user: Union[discord.Member, discord.User], *, reason: str = "Appeal accepted"):
        if not await self.bot.db.is_server_authorized(ctx.guild.id):
            embed = EmbedDesign.error(
                title="Server Not Authorized",
                description="This server is not authorized for EPN access."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return

        has_admin = ctx.author.guild_permissions.administrator
        has_staff = await StaffUtils.has_staff_permission_cross_guild(self.bot, ctx.author, "ban")

        if not (has_admin or has_staff):
            embed = EmbedDesign.error(
                title="Permission Denied",
                description="You must have Administrator or staff permissions to use this command."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return

        async def command_logic(interaction: discord.Interaction):
            try:
                authorized_servers = await self.bot.db.get_authorized_servers(limit=500)
                authorized_ids = {server["guild_id"] for server in authorized_servers}

                unbanned_guilds = []
                failed_guilds = []

                for guild in self.bot.guilds:
                    if guild.id not in authorized_ids:
                        continue

                    try:
                        await guild.unban(user, reason=f"EPN Unblacklist: {reason}")
                        unbanned_guilds.append(guild.name)

                        await self.log_cross_guild_action(
                            action="unban",
                            guild=guild,
                            user=user,
                            moderator=interaction.user,
                            reason=reason,
                            failed=False
                        )

                    except discord.NotFound:
                        pass
                    except Exception as e:
                        failed_guilds.append(guild.name)
                        logger.error(f"Failed to unban user from {guild.name}: {e}")

                        await self.log_cross_guild_action(
                            action="unban",
                            guild=guild,
                            user=user,
                            moderator=interaction.user,
                            reason=reason,
                            failed=True,
                            error_text=str(e)
                        )

                active_ban = await self.bot.db.find_blacklist(user.id, active=True, use_cache=False)
                if active_ban:
                    await self.bot.db.deactivate_blacklist(user.id, interaction.user.id, reason)

                embed = EmbedDesign.success(
                    title="User Unbanned",
                    description=f"{user.mention} was unbanned."
                )
                embed.add_field(name="Successful Guilds", value=str(len(unbanned_guilds)), inline=True)
                embed.add_field(name="Failed Guilds", value=str(len(failed_guilds)), inline=True)

                await interaction.followup.send(embed=embed)

                dm_embed = EmbedDesign.create_embed(
                    title="You have been unblacklisted in ER:LC Partner Network",
                    description=(
                        f"Hello, **{user.display_name}**. You have been unbanned from EPN.\n"
                        f"**Reason:** {reason}\n\n"
                        f"You may rejoin our servers at: https://discord.gg/SKVuBHWKCP"
                    )
                )
                await self._safe_dm_user(user, dm_embed)

                await self.send_ban_notification("unban", user, reason, interaction.user, "Cross-Guild Unban")

            except Exception as e:
                logger.error(f"Error in unban command logic: {e}")
                await interaction.followup.send(
                    embed=EmbedDesign.error("Unban Operation Failed", f"Could not complete the unban operation: {str(e)}"),
                    ephemeral=True
                )

        await self.bot.command_verifier.verify_and_execute(ctx, command_logic)


async def setup(bot: commands.Bot):
    await bot.add_cog(EPNCommands(bot))
