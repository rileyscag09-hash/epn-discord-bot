import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta
from typing import Optional, Union
import aiohttp
import re
import logging
from utils.constants import Constants, EmbedDesign
from utils.staff import StaffUtils
from utils.rate_limiter import UserCommandRateLimiter
from utils.validation import validate_input, validate_discord_id, InputSanitizer
from utils.security_logger import get_security_logger

# Define logger for this module
logger = logging.getLogger(__name__)

# Initialize constants
constants = Constants()

class UECCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.security_logger = get_security_logger(bot)
        
        # Rate limiter for non-staff users (3 commands per hour)
        self.admin_rate_limiter = UserCommandRateLimiter(
            max_requests=3,
            time_window=3600,  # 1 hour in seconds
            command_name="uec_admin_commands"
        )

    def parse_duration(self, duration_str: str) -> datetime:
        """Parse a duration string like '1d', '2h', '30m' into a datetime."""
        import re
        
        # Remove any whitespace
        duration_str = duration_str.strip().lower()
        
        # Parse the duration
        match = re.match(r'^(\d+)([dhms])$', duration_str)
        if not match:
            raise ValueError(f"Invalid duration format: {duration_str}. Use format like '1d', '2h', '30m', '45s'")
        
        value, unit = match.groups()
        value = int(value)
        
        # Convert to seconds
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
        
        # Add to current time
        return datetime.utcnow() + timedelta(seconds=seconds)
    
    async def check_admin_rate_limit(self, user_id: int) -> tuple[bool, Optional[str]]:
        """
        Check if a non-staff user has exceeded their rate limit.
        
        Args:
            user_id: Discord user ID
            
        Returns:
            Tuple of (can_proceed, error_message)
        """
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
                
                error_msg = f"You have reached the rate limit for UEC commands (3 per hour). Try again in {time_str}."
            else:
                error_msg = f"You have reached the rate limit for UEC commands (3 per hour). {remaining} requests remaining."
            
            return False, error_msg
        
        return True, None

    @commands.hybrid_group(name="uec", description="UEC moderation commands")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def uec_group(self, ctx: commands.Context):
        """UEC moderation commands."""
        if not ctx.invoked_subcommand:
            embed = EmbedDesign.info(
                title="UEC Commands",
                description="Available UEC moderation commands:",
                fields=[
                    {"name": "ban", "value": "Ban a user across all guilds", "inline": True},
                    {"name": "unban", "value": "Unban a user across all guilds", "inline": True},
                    {"name": "serverban", "value": "Ban a server from UEC", "inline": True},
                    {"name": "serverunban", "value": "Unban a server from UEC", "inline": True},
                    {"name": "history", "value": "View ban history for a user", "inline": True},
                    {"name": "update", "value": "Update ban details", "inline": True},
                    {"name": "sync", "value": "Force sync commands (Dev)", "inline": True},
                    {"name": "alts", "value": "View all alt accounts for a Roblox ID", "inline": True}
                ]
            )
            await ctx.reply(embed=embed, ephemeral=True)

    async def send_ban_notification(self, action: str, user: Union[discord.User, discord.Member], reason: str, staff_member: discord.Member, guild_name: str = None, evidence: str = None, expires_at: datetime = None, appealable: bool = True):
        """Send ban notification to the specified channel."""
        try:
            # Get the notification channel
            notification_channel = self.bot.get_channel(constants.uec_user_notification_channel_id())
            if not notification_channel:
                logger.error("Notification channel not found")
                return
            
            # Determine color based on action using softer colors
            color = EmbedDesign.ERROR if action.lower() == "ban" else EmbedDesign.SUCCESS if action.lower() == "unban" else EmbedDesign.WARNING
            
            # Get current timestamp
            current_time = datetime.utcnow()
            
            # Build description with additional details
            description_parts = [f"{user.mention} ({user.id}) was {action.lower()} in {guild_name or 'UEC'} by {staff_member.mention}"]
            description_parts.append(f"**Reason:** {reason}")
            
            if evidence:
                description_parts.append(f"**Evidence:** {evidence}")
            
            if expires_at:
                description_parts.append(f"**Expires:** <t:{int(expires_at.timestamp())}:F>")
            
            if not appealable:
                description_parts.append("**Appeals:** Not allowed")
            
            # Create clean title for user actions
            if action.lower() == "ban":
                title = "🚫 UEC User Ban"
            elif action.lower() == "unban":
                title = "✅ UEC User Unban"
            elif action.lower() == "update":
                title = "📝 UEC Ban Update"
            else:
                title = f"UEC {action.title()}"
            
            # Create notification embed
            embed = EmbedDesign.create_embed(
                title=title,
                description="\n".join(description_parts),
                color=color
            )
            
            await notification_channel.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error sending ban notification: {e}")

    async def send_server_ban_notification(self, action: str, guild_id: int, guild_name: str, reason: str, staff_member: discord.Member, evidence: str = None, expires_at: datetime = None, appealable: bool = True):
        """Send server ban notification to the specified channel."""
        try:
            # Get the notification channel
            notification_channel = self.bot.get_channel(constants.uec_server_notification_channel_id())
            if not notification_channel:
                logger.error("Notification channel not found")
                return
            
            # Determine color based on action
            color = EmbedDesign.ERROR if action.lower() in ["ban", "serverban"] else EmbedDesign.SUCCESS if action.lower() in ["unban", "serverunban"] else EmbedDesign.WARNING
            
            # Build description with server details
            description_parts = [f"Server **{guild_name}** (`{guild_id}`) was {action.lower()} by {staff_member.mention}"]
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
            
            # Create clean title for server actions
            if action.lower() in ["serverban", "ban"]:
                title = "🚫 UEC Server Ban"
            elif action.lower() in ["serverunban", "unban"]:
                title = "✅ UEC Server Unban"
            else:
                title = f"UEC Server {action.title()}"
            
            # Create notification embed
            embed = EmbedDesign.create_embed(
                title=title,
                description="\n".join(description_parts),
                color=color
            )
            
            await notification_channel.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error sending server ban notification: {e}")

    @uec_group.command(name="ban", description="Ban a user across all guilds")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @app_commands.describe(
        user="The user to ban",
        reason="Reason for the ban",
        evidence="Evidence supporting the ban (optional)",
        expires="When the ban expires (e.g., '1d', '2h', '30m' - optional)",
        appealable="Whether the ban can be appealed (default: True)"
    )
    async def ban(self, ctx: commands.Context, user: Union[discord.Member, discord.User], reason: str = "No reason provided", evidence: str = None, expires: str = None, appealable: bool = True):
        """Ban a user across all guilds."""
        # Check if server is authorized before starting verification
        if not await self.bot.db.is_server_authorized(ctx.guild.id):
            embed = EmbedDesign.error(
                title="Server Not Authorized",
                description="This server is not authorized for UEC access. Only authorized servers can use UEC commands."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        # Check if user has either admin permissions in this server OR staff permissions
        has_admin = ctx.author.guild_permissions.administrator
        has_staff = await StaffUtils.has_staff_permission_cross_guild(self.bot, ctx.author, "ban")
        
        if not (has_admin or has_staff):
            embed = EmbedDesign.error(
                title="Permission Denied",
                description="You must have either Administrator permissions in this server OR staff permissions to use UEC commands."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        # Rate limit check for non-staff users
        if has_admin and not has_staff:
            can_proceed, error_msg = await self.check_admin_rate_limit(ctx.author.id)
            if not can_proceed:
                embed = EmbedDesign.error(
                    title="Rate Limit Exceeded",
                    description=error_msg
                )
                await ctx.reply(embed=embed, ephemeral=True)
                return
        
        async def command_logic(interaction: discord.Interaction):
            try:

                if user.bot:
                    embed = EmbedDesign.error(title="Invalid Target", description="You cannot ban bots.")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

                if user == interaction.user:
                    embed = EmbedDesign.error(title="Invalid Target", description="You cannot ban yourself.")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

                # Check if target user is core staff or developer (protected from UEC bans)
                target_is_core_staff = await StaffUtils.has_core_staff_permission_cross_guild(self.bot, user, "ban")
                if target_is_core_staff:
                    embed = EmbedDesign.error(title="Protected User", description="You cannot ban staff members or developers.")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

                if await self.bot.db.find_blacklist(user.id, active=True):
                    embed = EmbedDesign.error(title="User Already Blacklisted", description="This user is already blacklisted.")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

                expires_at = None
                if expires:
                    try:
                        expires_at = self.parse_duration(expires)
                    except ValueError as e:
                        embed = EmbedDesign.error(title="Invalid Expiry Time", description=str(e))
                        await interaction.followup.send(embed=embed, ephemeral=True)
                        return
                
                await self.bot.db.insert_blacklist(user.id, reason, evidence or "", interaction.user.id, expires_at, appealable)
                
                # Record the command usage for rate limiting
                if has_admin and not has_staff:
                    await self.admin_rate_limiter.record_request(interaction.user.id)
                
                banned_guilds, failed_guilds = [], []
                for guild in self.bot.guilds:
                    if guild.id != constants.main_server_id():
                        try:
                            await guild.ban(user, reason=f"UEC Blacklist: {reason}")
                            banned_guilds.append(guild.name)
                        except Exception as e:
                            failed_guilds.append(guild.name)
                            logger.error(f"Failed to ban user from {guild.name}: {e}")

                embed = EmbedDesign.success(title="User Blacklisted", description=f"**{user.display_name}** has been added to the UEC blacklist.")
                await interaction.followup.send(embed=embed)
                await self.send_ban_notification("ban", user, reason, interaction.user, "Cross-Guild Ban", evidence, expires_at, appealable)

            except Exception as e:
                logger.error(f"Error in ban command logic: {e}")
                embed = EmbedDesign.error("Ban Operation Failed", f"Could not complete the ban operation: {str(e)}")
                await interaction.followup.send(embed=embed, ephemeral=True)

        await self.bot.command_verifier.verify_and_execute(ctx, command_logic)

    @uec_group.command(name="unban", description="Unban a user across all guilds")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @app_commands.describe(user="The user to unban", reason="Reason for the unban")
    async def unban(self, ctx: commands.Context, user: Union[discord.Member, discord.User], *, reason: str = "Appeal accepted"):
        """Unban a user across all guilds."""
        # Check if server is authorized before starting verification
        if not await self.bot.db.is_server_authorized(ctx.guild.id):
            embed = EmbedDesign.error(
                title="Server Not Authorized",
                description="This server is not authorized for UEC access. Only authorized servers can use UEC commands."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        # Check if user has either admin permissions in this server OR staff permissions
        has_admin = ctx.author.guild_permissions.administrator
        has_staff = await StaffUtils.has_staff_permission_cross_guild(self.bot, ctx.author, "ban")
        
        if not (has_admin or has_staff):
            embed = EmbedDesign.error(
                title="Permission Denied",
                description="You must have either Administrator permissions in this server OR staff permissions to use UEC commands."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        # Rate limit check for non-staff users
        if has_admin and not has_staff:
            can_proceed, error_msg = await self.check_admin_rate_limit(ctx.author.id)
            if not can_proceed:
                embed = EmbedDesign.error(
                    title="Rate Limit Exceeded",
                    description=error_msg
                )
                await ctx.reply(embed=embed, ephemeral=True)
                return
        
        async def command_logic(interaction: discord.Interaction):
            try:

                unbanned_guilds, failed_guilds = [], []
                for guild in self.bot.guilds:
                    try:
                        await guild.unban(user, reason="UEC Unblacklist")
                        unbanned_guilds.append(guild.name)
                    except discord.NotFound:
                        pass
                    except Exception as e:
                        failed_guilds.append(guild.name)
                        logger.error(f"Failed to unban user from {guild.name}: {e}")

                result = await self.bot.db.deactivate_blacklist(user.id, interaction.user.id, reason)
                if not result:
                    embed = EmbedDesign.warning(title="Database Record Not Found", description="User unbanned, but no active ban record was found.")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

                # Record the command usage for rate limiting
                if has_admin and not has_staff:
                    await self.admin_rate_limiter.record_request(interaction.user.id)

                embed = EmbedDesign.success(title="User Unbanned", description=f"{user.mention} was unbanned by {interaction.user.mention}.")
                await interaction.followup.send(embed=embed)
                await self.send_ban_notification("unban", user, reason, interaction.user, "Cross-Guild Unban")

            except Exception as e:
                logger.error(f"Error in unban command logic: {e}")
                embed = EmbedDesign.error("Unban Operation Failed", f"Could not complete the unban operation: {str(e)}")
                await interaction.followup.send(embed=embed, ephemeral=True)

        await self.bot.command_verifier.verify_and_execute(ctx, command_logic)

    @uec_group.command(name="history", description="View ban history for a user")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @app_commands.describe(
        user="The user to check history for"
    )
    async def history(
        self,
        ctx: commands.Context,
        user: Union[discord.Member, discord.User]
    ):
        """View ban history for a user."""
        # Check if server is authorized before starting verification
        if not await self.bot.db.is_server_authorized(ctx.guild.id):
            embed = EmbedDesign.error(
                title="Server Not Authorized",
                description="This server is not authorized for UEC access. Only authorized servers can use UEC commands."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        # Check if user has either admin permissions in this server OR staff permissions
        has_admin = ctx.author.guild_permissions.administrator
        has_staff = await StaffUtils.has_staff_permission_cross_guild(self.bot, ctx.author, "ban")
        
        if not (has_admin or has_staff):
            embed = EmbedDesign.error(
                title="Permission Denied",
                description="You must have either Administrator permissions in this server OR staff permissions to use UEC commands."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return

        # Get blacklist history from PostgreSQL
        blacklist_records = await self.bot.db.find_all_blacklist_by_user(user.id, limit=10)

        if not blacklist_records:
            embed = EmbedDesign.info(
                title="No History Found",
                description=f"No ban history found for **{user.display_name}**."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return

        # Create history embed with rich information
        embed = EmbedDesign.info(
            title=f"Ban History for {user.display_name}",
            description=f"User ID: `{user.id}`\nShowing {len(blacklist_records)} most recent ban record(s)"
        )
        embed.set_thumbnail(url=user.display_avatar.url)

        for i, record in enumerate(blacklist_records, 1):
            # Status and basic info
            status = "🔴 Active" if record.get("active", False) else "🟢 Inactive"
            reason = record.get("reason", "No reason provided")
            evidence = record.get("evidence", "")
            appealable = record.get("appeal_allowed", True)
            
            # Timestamps
            timestamp = record.get("timestamp")
            expires_at = record.get("expires_at")
            updated_at = record.get("updated_at")
            
            # Build field content
            field_lines = [f"**Status:** {status}"]
            field_lines.append(f"**Reason:** {reason}")
            
            if evidence:
                # Truncate evidence if too long
                evidence_display = evidence if len(evidence) <= 100 else evidence[:97] + "..."
                field_lines.append(f"**Evidence:** {evidence_display}")
            
            # Timestamps
            if timestamp:
                field_lines.append(f"**Banned:** <t:{int(timestamp.timestamp())}:F>")
            
            # Expiry information with time remaining
            if expires_at:
                now = datetime.utcnow()
                if expires_at and expires_at > now:
                    # Active temp ban - show time remaining
                    field_lines.append(f"**Expires:** <t:{int(expires_at.timestamp())}:F>")
                    time_left = expires_at - now
                    if time_left.days > 0:
                        field_lines.append(f"**Time Left:** {time_left.days}d {time_left.seconds//3600}h")
                    elif time_left.seconds > 3600:
                        field_lines.append(f"**Time Left:** {time_left.seconds//3600}h {(time_left.seconds%3600)//60}m")
                    else:
                        field_lines.append(f"**Time Left:** {time_left.seconds//60}m")
                else:
                    # Expired temp ban
                    field_lines.append(f"**Expired:** <t:{int(expires_at.timestamp())}:F>")
            else:
                field_lines.append("**Duration:** Permanent")
            
            if updated_at:
                field_lines.append(f"**Last Updated:** <t:{int(updated_at.timestamp())}:R>")
            
            # Appeal status
            appeal_status = "✅ Allowed" if appealable else "❌ Not Allowed"
            field_lines.append(f"**Appeals:** {appeal_status}")

            # Staff info
            banned_by_id = record.get("blacklisted_by")
            if banned_by_id:
                try:
                    banned_by_user = await self.bot.fetch_user(banned_by_id)
                    field_lines.append(f"**Banned By:** {banned_by_user.mention}")
                except:
                    field_lines.append(f"**Banned By:** <@{banned_by_id}>")
            
            updated_by_id = record.get("updated_by")
            if updated_by_id and updated_by_id != banned_by_id:
                try:
                    updated_by_user = await self.bot.fetch_user(updated_by_id)
                    field_lines.append(f"**Updated By:** {updated_by_user.mention}")
                except:
                    field_lines.append(f"**Updated By:** <@{updated_by_id}>")

            embed.add_field(
                name=f"Ban Record #{record.get('id', i)}",
                value="\n".join(field_lines),
                inline=False
            )

        # Add footer with useful info
        active_count = sum(1 for r in blacklist_records if r.get("active", False))
        embed.set_footer(text=f"Active bans: {active_count}/{len(blacklist_records)} • Use /uec update to modify active bans")

        await ctx.reply(embed=embed, ephemeral=True)

    @uec_group.command(name="update", description="Update ban details")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @app_commands.describe(
        user="The user to update",
        new_reason="New reason for the ban",
        new_evidence="New evidence for the ban (optional)",
        new_expires="New expiry time (e.g., '1d', '2h', '30m' - optional)",
        new_appealable="Whether the ban can be appealed (optional)"
    )
    async def update(
        self,
        ctx: commands.Context,
        user: Union[discord.Member, discord.User],
        new_reason: str,
        new_evidence: str = None,
        new_expires: str = None,
        new_appealable: bool = None
    ):
        """Update ban details including reason, evidence, expiry, and appeal status."""
        # Check if server is authorized before starting verification
        if not await self.bot.db.is_server_authorized(ctx.guild.id):
            embed = EmbedDesign.error(
                title="Server Not Authorized",
                description="This server is not authorized for UEC access. Only authorized servers can use UEC commands."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        # Check if user has either admin permissions in this server OR staff permissions
        has_admin = ctx.author.guild_permissions.administrator
        has_staff = await StaffUtils.has_staff_permission_cross_guild(self.bot, ctx.author, "ban")
        
        if not (has_admin or has_staff):
            embed = EmbedDesign.error(
                title="Permission Denied",
                description="You must have either Administrator permissions in this server OR staff permissions to use UEC commands."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        # Rate limit check for non-staff users
        if has_admin and not has_staff:
            can_proceed, error_msg = await self.check_admin_rate_limit(ctx.author.id)
            if not can_proceed:
                embed = EmbedDesign.error(
                    title="Rate Limit Exceeded",
                    description=error_msg
                )
                await ctx.reply(embed=embed, ephemeral=True)
                return
        
        async def command_logic(interaction: discord.Interaction):
            try:

                # Get current blacklist record (bypass cache to ensure fresh data)
                current_record = await self.bot.db.find_blacklist(user.id, active=True, use_cache=False)
                logger.info(f"UEC Update - Looking for active ban for user {user.id}: {current_record is not None}")
                
                if not current_record:
                    # Try to find any blacklist record for this user (active or inactive)
                    all_records = await self.bot.db.find_all_blacklist_by_user(user.id, limit=5)
                    logger.info(f"UEC Update - All blacklist records for user {user.id}: {len(all_records)} records found")
                    
                    if all_records:
                        # User has ban history but no active ban
                        embed = EmbedDesign.warning(
                            title="No Active Ban",
                            description=f"User {user.display_name} has ban history but no active ban. Cannot update inactive bans."
                        )
                    else:
                        # User has no ban history at all
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

                # Parse new expiry time if provided
                new_expires_at = None
                if new_expires:
                    try:
                        new_expires_at = self.parse_duration(new_expires)
                    except ValueError as e:
                        embed = EmbedDesign.error(title="Invalid Expiry Time", description=str(e))
                        await interaction.followup.send(embed=embed, ephemeral=True)
                        return

                # Prepare update data
                update_data = {"reason": new_reason}
                if new_evidence is not None:
                    update_data["evidence"] = new_evidence
                if new_expires_at is not None:
                    update_data["expires_at"] = new_expires_at
                if new_appealable is not None:
                    update_data["appeal_allowed"] = new_appealable

                # Note: We removed the double-check here since the database layer handles it

                # Update blacklist in PostgreSQL
                try:
                    if len(update_data) == 1 and "reason" in update_data:
                        # Only reason is being updated, use the simpler method
                        result = await self.bot.db.update_blacklist_reason(user.id, new_reason, interaction.user.id)
                    else:
                        # Multiple fields being updated, use the full update method
                        result = await self.bot.db.update_blacklist_full(user.id, interaction.user.id, **update_data)
                    
                    logger.info(f"UEC Update - Database update result for user {user.id}: {result}")
                    
                    # Record the command usage for rate limiting
                    if has_admin and not has_staff:
                        await self.admin_rate_limiter.record_request(interaction.user.id)
                        
                except Exception as e:
                    logger.error(f"UEC Update - Database error for user {user.id}: {e}")
                    embed = EmbedDesign.error(
                        title="Database Error",
                        description="Failed to update ban details due to a database error."
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

                if not result:
                    embed = EmbedDesign.error(
                        title="Update Failed",
                        description="Failed to update ban details. The ban may have been modified by another user."
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

                # Build success message with changes
                fields = []
                changes = []
                
                if old_reason.strip() != new_reason.strip():
                    fields.append({"name": "Reason", "value": f"**Old:** {old_reason.strip()}\n**New:** {new_reason.strip()}", "inline": False})
                    changes.append(f"reason: {old_reason.strip()} → {new_reason.strip()}")
                
                if new_evidence is not None and old_evidence.strip() != new_evidence.strip():
                    fields.append({"name": "Evidence", "value": f"**Old:** {old_evidence.strip() or 'None'}\n**New:** {new_evidence.strip() or 'None'}", "inline": False})
                    changes.append(f"evidence: {old_evidence.strip() or 'None'} → {new_evidence.strip() or 'None'}")
                
                if new_expires_at is not None:
                    old_expires_str = f"<t:{int(old_expires.timestamp())}:F>" if old_expires else "Permanent"
                    new_expires_str = f"<t:{int(new_expires_at.timestamp())}:F>" if new_expires_at else "Permanent"
                    fields.append({"name": "Expires", "value": f"**Old:** {old_expires_str}\n**New:** {new_expires_str}", "inline": False})
                    changes.append(f"expires: {old_expires_str} → {new_expires_str}")
                
                if new_appealable is not None and old_appealable != new_appealable:
                    old_appeal_str = "Allowed" if old_appealable else "Not Allowed"
                    new_appeal_str = "Allowed" if new_appealable else "Not Allowed"
                    fields.append({"name": "Appeals", "value": f"**Old:** {old_appeal_str}\n**New:** {new_appeal_str}", "inline": False})
                    changes.append(f"appeals: {old_appeal_str} → {new_appeal_str}")
                
                fields.append({"name": "Updated by", "value": interaction.user.mention, "inline": True})
                
                embed = EmbedDesign.success(
                    title="Ban Updated",
                    description=f"Ban details updated for {user.display_name}",
                    fields=fields
                )
                await interaction.followup.send(embed=embed)
                
                # Send notification
                changes_text = " | ".join(changes) if changes else f"reason: {old_reason} → {new_reason}"
                await self.send_ban_notification("update", user, f"Updated: {changes_text}", interaction.user, interaction.guild.name)

            except Exception as e:
                logger.error(f"Error in update command logic: {e}")
                embed = EmbedDesign.error("Update Operation Failed", f"Could not complete the update operation: {str(e)}")
                await interaction.followup.send(embed=embed, ephemeral=True)

        await self.bot.command_verifier.verify_and_execute(ctx, command_logic)

    @uec_group.command(name="serverban", description="Ban a server from UEC")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @app_commands.describe(guild_id="The guild ID to ban", reason="Reason for the server ban", evidence="Evidence for the ban", expires="When the ban expires", appealable="Whether the ban can be appealed")
    async def server_ban(self, ctx: commands.Context, guild_id: str, reason: str = "No reason provided", evidence: str = None, expires: str = None, appealable: bool = True):
        """Ban a server from UEC."""
        # Check if server is authorized before starting verification
        if not await self.bot.db.is_server_authorized(ctx.guild.id):
            embed = EmbedDesign.error(
                title="Server Not Authorized",
                description="This server is not authorized for UEC access. Only authorized servers can use UEC commands."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        async def command_logic(interaction: discord.Interaction):
            try:
                if not await StaffUtils.has_staff_permission_cross_guild(self.bot, interaction.user, "ban"):
                    embed = EmbedDesign.error(title="Permission Denied", description="You don't have permission to ban servers.")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return
            
                try:
                    guild_id_int = int(guild_id)
                except ValueError:
                    embed = EmbedDesign.error(title="Invalid Guild ID", description="Please provide a valid numeric guild ID.")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

                if await self.bot.db.find_server_ban(guild_id_int, active=True):
                    embed = EmbedDesign.error(title="Server Already Banned", description="This server is already banned.")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return
                
                guild = self.bot.get_guild(guild_id_int)
                guild_name = guild.name if guild else "Unknown Server"
                
                expires_at = None
                if expires:
                    try:
                        expires_at = self.parse_duration(expires)
                    except ValueError as e:
                        embed = EmbedDesign.error(title="Invalid Expiry Time", description=str(e))
                        await interaction.followup.send(embed=embed, ephemeral=True)
                        return

                await self.bot.db.insert_server_ban(guild_id_int, guild_name, reason, evidence or "", interaction.user.id, expires_at, appealable)
                
                embed = EmbedDesign.success(title="Server Banned", description=f"**{guild_name}** has been banned from UEC.")
                await interaction.followup.send(embed=embed, ephemeral=True)
                await self.send_server_ban_notification("serverban", guild_id_int, guild_name, reason, interaction.user, evidence, expires_at, appealable)
            except Exception as e:
                logger.error(f"Error in server_ban command logic: {e}")
                embed = EmbedDesign.error("Server Ban Operation Failed", f"Could not complete the server ban operation: {str(e)}")
                await interaction.followup.send(embed=embed, ephemeral=True)

        await self.bot.command_verifier.verify_and_execute(ctx, command_logic)

    @uec_group.command(name="serverunban", description="Unban a server from UEC")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @app_commands.describe(guild_id="The guild ID to unban", reason="Reason for the unban")
    async def server_unban(self, ctx: commands.Context, guild_id: str, *, reason: str = "Appeal accepted"):
        """Unban a server from UEC."""
        # Check if server is authorized before starting verification
        if not await self.bot.db.is_server_authorized(ctx.guild.id):
            embed = EmbedDesign.error(
                title="Server Not Authorized",
                description="This server is not authorized for UEC access. Only authorized servers can use UEC commands."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        async def command_logic(interaction: discord.Interaction):
            try:
                if not await StaffUtils.has_staff_permission_cross_guild(self.bot, interaction.user, "ban"):
                    embed = EmbedDesign.error(title="Permission Denied", description="You don't have permission to unban servers.")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

                try:
                    guild_id_int = int(guild_id)
                except ValueError:
                    embed = EmbedDesign.error(title="Invalid Guild ID", description="Please provide a valid numeric guild ID.")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

                server_ban = await self.bot.db.find_server_ban(guild_id_int, active=True)
                if not server_ban:
                    embed = EmbedDesign.error(title="Server Not Banned", description="This server is not currently banned.")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

                result = await self.bot.db.deactivate_server_ban(guild_id_int, interaction.user.id, reason)
                if not result:
                    embed = EmbedDesign.error(title="Database Error", description="Failed to update server ban record.")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

                guild_name = server_ban.get("guild_name", "Unknown Server")
                embed = EmbedDesign.success(title="Server Unbanned", description=f"**{guild_name}** has been unbanned from UEC.")
                await interaction.followup.send(embed=embed, ephemeral=True)
                await self.send_server_ban_notification("serverunban", guild_id_int, guild_name, reason, interaction.user)
            except Exception as e:
                logger.error(f"Error in server_unban command logic: {e}")
                embed = EmbedDesign.error("Server Unban Operation Failed", f"Could not complete the server unban operation: {str(e)}")
                await interaction.followup.send(embed=embed, ephemeral=True)

        await self.bot.command_verifier.verify_and_execute(ctx, command_logic)
    
    @uec_group.command(name="servers", description="List all servers the bot is in")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def servers(self, ctx: commands.Context):
        """Show all servers the bot is in, with pagination if needed."""
        if not await StaffUtils.has_developer_permission_cross_guild(self.bot, ctx.author, "ban"):
            embed = EmbedDesign.error(
                title="Permission Denied",
                description="You don't have permission to view servers. This requires Developer access."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return

        # Sort guilds by member count desc
        guilds = sorted(self.bot.guilds, key=lambda g: g.member_count or 0, reverse=True)

        lines = []
        for g in guilds:
            owner = f"<@{g.owner_id}>" if g.owner_id else "Unknown"
            line = f"• {g.name} ({g.id}) — Members: {g.member_count or 0} — Owner: {owner}"
            lines.append(line)

        # Build pages (15 lines per page)
        page_size = 15
        pages = [lines[i:i+page_size] for i in range(0, len(lines), page_size)] or [[]]

        from utils.pagination import Paginator

        embeds = []
        total = len(guilds)
        for idx, chunk in enumerate(pages, 1):
            embed = EmbedDesign.info(
                title="Bot Servers",
                description=f"Total: {total} servers\n\n" + ("\n".join(chunk) if chunk else "No servers found."),
            )
            embeds.append(embed)

        view = Paginator(ctx.author, embeds)
        await ctx.reply(embed=embeds[0], view=view)
    
    @uec_group.command(name="authorize", description="Authorize a server for UEC access")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @app_commands.describe(
        guild_id="The guild ID to authorize",
        reason="Reason for authorization (optional)"
    )
    async def authorize_server(self, ctx: commands.Context, guild_id: str, *, reason: str = None):
        """Authorize a server for UEC access."""
        async def command_logic(interaction: discord.Interaction):
            try:
                # Check if user is UEC developer
                if not await StaffUtils.has_developer_permission_cross_guild(self.bot, interaction.user, "manage_guild"):
                    embed = EmbedDesign.error(
                        title="Permission Denied",
                        description="You don't have permission to authorize servers. This requires UEC Developer access."
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return
                
                try:
                    guild_id_int = int(guild_id)
                except ValueError:
                    embed = EmbedDesign.error(title="Invalid Guild ID", description="Please provide a valid numeric guild ID.")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return
                
                # Get guild name
                try:
                    guild = await self.bot.fetch_guild(guild_id_int)
                    guild_name = guild.name if guild else "Unknown Server"
                except:
                    guild_name = "Unknown Server"
                
                # Check if already authorized
                if await self.bot.db.is_server_authorized(guild_id_int):
                    embed = EmbedDesign.warning(
                        title="Already Authorized",
                        description=f"Server **{guild_name}** is already authorized for UEC access."
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return
                
                # Authorize the server
                await self.bot.db.authorize_server(guild_id_int, guild_name, interaction.user.id, reason)
                
                embed = EmbedDesign.success(
                    title="Server Authorized",
                    description=f"**{guild_name}** has been authorized for UEC access.",
                    fields=[
                        {"name": "Guild ID", "value": str(guild_id_int), "inline": True},
                        {"name": "Authorized by", "value": interaction.user.mention, "inline": True},
                        {"name": "Reason", "value": reason or "No reason provided", "inline": False}
                    ]
                )
                await interaction.followup.send(embed=embed)
                
            except Exception as e:
                logger.error(f"Error in authorize_server command logic: {e}")
                embed = EmbedDesign.error("Authorization Operation Failed", f"Could not complete the authorization operation: {str(e)}")
                await interaction.followup.send(embed=embed, ephemeral=True)

        await self.bot.command_verifier.verify_and_execute(ctx, command_logic)
    
    @uec_group.command(name="deauthorize", description="Deauthorize a server from UEC access")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @app_commands.describe(
        guild_id="The guild ID to deauthorize",
        reason="Reason for deauthorization (optional)"
    )
    async def deauthorize_server(self, ctx: commands.Context, guild_id: str, *, reason: str = None):
        """Deauthorize a server from UEC access."""
        async def command_logic(interaction: discord.Interaction):
            try:
                # Check if user is UEC developer
                if not await StaffUtils.has_developer_permission_cross_guild(self.bot, interaction.user, "manage_guild"):
                    embed = EmbedDesign.error(
                        title="Permission Denied",
                        description="You don't have permission to deauthorize servers. This requires UEC Developer access."
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return
                
                try:
                    guild_id_int = int(guild_id)
                except ValueError:
                    embed = EmbedDesign.error(title="Invalid Guild ID", description="Please provide a valid numeric guild ID.")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return
                
                # Check if server is authorized
                auth_info = await self.bot.db.get_server_authorization(guild_id_int)
                if not auth_info:
                    embed = EmbedDesign.warning(
                        title="Not Authorized",
                        description=f"Server with ID `{guild_id_int}` is not currently authorized for UEC access."
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return
                
                # Deauthorize the server
                result = await self.bot.db.deauthorize_server(guild_id_int, interaction.user.id, reason)
                
                if result:
                    embed = EmbedDesign.success(
                        title="Server Deauthorized",
                        description=f"**{auth_info.get('guild_name', 'Unknown Server')}** has been deauthorized from UEC access.",
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
                embed = EmbedDesign.error("Deauthorization Operation Failed", f"Could not complete the deauthorization operation: {str(e)}")
                await interaction.followup.send(embed=embed, ephemeral=True)

        await self.bot.command_verifier.verify_and_execute(ctx, command_logic)
    
    @uec_group.command(name="authorized", description="List all authorized servers")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def list_authorized_servers(self, ctx: commands.Context):
        """List all authorized servers."""
        if not await StaffUtils.has_developer_permission_cross_guild(self.bot, ctx.author, "manage_guild"):
            embed = EmbedDesign.error(
                title="Permission Denied",
                description="You don't have permission to view authorized servers. This requires UEC Developer access."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return

        # Get authorized servers
        authorized_servers = await self.bot.db.get_authorized_servers(limit=100)
        
        if not authorized_servers:
            embed = EmbedDesign.info(
                title="No Authorized Servers",
                description="There are currently no authorized servers for UEC access."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return

        # Build server list
        lines = []
        for server in authorized_servers:
            guild_id = server.get('guild_id')
            guild_name = server.get('guild_name', 'Unknown Server')
            authorized_at = server.get('authorized_at')
            reason = server.get('reason', 'No reason provided')
            
            # Format timestamp
            if authorized_at:
                timestamp_str = f"<t:{int(authorized_at.timestamp())}:R>"
            else:
                timestamp_str = "Unknown"
            
            line = f"• **{guild_name}** (`{guild_id}`) — {timestamp_str}"
            if reason and reason != "No reason provided":
                line += f" — *{reason[:50]}{'...' if len(reason) > 50 else ''}*"
            lines.append(line)

        # Build pages (10 lines per page)
        page_size = 10
        pages = [lines[i:i+page_size] for i in range(0, len(lines), page_size)] or [[]]

        from utils.pagination import Paginator

        embeds = []
        total = len(authorized_servers)
        for idx, chunk in enumerate(pages, 1):
            embed = EmbedDesign.info(
                title="Authorized Servers",
                description=f"Total: {total} authorized servers\n\n" + ("\n".join(chunk) if chunk else "No servers found."),
            )
            embed.set_footer(text=f"Page {idx}/{len(pages)}")
            embeds.append(embed)

        view = Paginator(ctx.author, embeds)
        await ctx.reply(embed=embeds[0], view=view)



async def setup(bot: commands.Bot):
    await bot.add_cog(UECCommands(bot)) 