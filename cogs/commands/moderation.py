import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta
from typing import Optional
from utils.constants import logger, EmbedDesign
from utils.staff import StaffUtils

class ModerationCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot



    @commands.hybrid_command(name="dm", description="Send a DM to a user")
    @app_commands.guilds(discord.Object(id=1367173562971983963))
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @app_commands.describe(
        user="The user to DM",
        message="The message to send"
    )
    async def dm(
        self,
        ctx: commands.Context,
        user: discord.Member,
        *, message: str
    ):
        """Send a DM to a user."""
        if not await StaffUtils.has_staff_permission_cross_guild(self.bot, ctx.author, "block"):
            embed = EmbedDesign.error(
                title="Permission Denied",
                description="You don't have permission to send DMs. This requires Developer access."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return

        try:
            embed = EmbedDesign.info(
                title="Message from Staff",
                description=message,
                fields=[
                    {"name": "From", "value": f"{ctx.guild.name} - {ctx.author.display_name}", "inline": False}
                ]
            )
            
            await user.send(embed=embed)
            
            confirm_embed = EmbedDesign.success(
                title="DM Sent",
                description=f"Message sent to **{user.display_name}**",
                fields=[
                    {"name": "Message", "value": message[:100] + "..." if len(message) > 100 else message, "inline": False}
                ]
            )
            await ctx.reply(embed=confirm_embed, ephemeral=True)
            
        except discord.Forbidden:
            embed = EmbedDesign.error(
                title="DM Failed",
                description="I cannot send a DM to this user. They may have DMs disabled."
            )
            await ctx.reply(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Error sending DM: {e}")
            embed = EmbedDesign.error(
                title="Error",
                description="An error occurred while sending the DM."
            )
            await ctx.reply(embed=embed, ephemeral=True)

    # Ignore command group
    @commands.hybrid_group(name="ignore", description="Manage ignored channels/users")
    @app_commands.guilds(discord.Object(id=1367173562971983963))
    async def ignore(self, ctx: commands.Context):
        """Manage ignored channels/users"""
        pass

    @ignore.command(name="add", description="Add a channel or user to ignore list")
    @app_commands.guilds(discord.Object(id=1367173562971983963))
    @app_commands.describe(
        target_id="The ID of the channel or user to ignore",
        reason="Reason for ignoring"
    )
    async def ignore_add(
        self,
        ctx: commands.Context,
        target_id: int,
        reason: str = "No reason provided"
    ):
        """Add a channel or user to the ignore list."""
        if not await StaffUtils.has_staff_permission_cross_guild(self.bot, ctx.author, "ignore"):
            embed = EmbedDesign.error(
                title="Permission Denied",
                description="You don't have permission to manage ignore list. This requires Developer access."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return

        # Try to find the target as a channel first, then as a member
        target = ctx.guild.get_channel(target_id)
        target_type = "channel"
        
        if not target:
            target = ctx.guild.get_member(target_id)
            target_type = "user"
            
        if not target:
            embed = EmbedDesign.error(
                title="Target Not Found",
                description=f"Could not find a channel or user with ID `{target_id}` in this server."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return

        # Store ignore record in MongoDB
        ignore_data = {
            "target_id": target.id,
            "target_type": target_type,
            "guild_id": ctx.guild.id,
            "added_by": ctx.author.id,
            "reason": reason,
            "timestamp": datetime.utcnow(),
            "active": True
        }
        
        await self.bot.db.insert_ignore(
            guild_id=ctx.guild.id,
            reason=reason,
            ignored_by=ctx.author.id,
            user_id=target.id if target_type == "user" else None,
            channel_id=target.id if target_type == "channel" else None
        )

        target_name = target.name if target_type == "channel" else target.display_name
        
        embed = EmbedDesign.warning(
            title="Added to Ignore List",
            description=f"**{target_name}** ({target_type}) has been added to the ignore list.",
            fields=[
                {"name": "Reason", "value": reason, "inline": False},
                {"name": "Added by", "value": ctx.author.mention, "inline": True},
                {"name": "Target ID", "value": target.id, "inline": True}
            ]
        )
        await ctx.reply(embed=embed)

    @ignore.command(name="list", description="List all ignored channels and users")
    @app_commands.guilds(discord.Object(id=1367173562971983963))
    async def ignore_list(self, ctx: commands.Context):
        """List all ignored channels and users."""
        if not await StaffUtils.has_developer_permission_cross_guild(self.bot, ctx.author, "ignore"):
            embed = EmbedDesign.error(
                title="Permission Denied",
                description="You don't have permission to view ignore list. This requires Developer access."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return

        # Get ignore list from PostgreSQL
        ignores = await self.bot.db.find_all_ignores(ctx.guild.id)

        if not ignores:
            embed = EmbedDesign.success(
                title="Ignore List",
                description="No ignored items found."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return

        embed = EmbedDesign.warning(
            title="Ignore List",
            description=f"Found {len(ignores)} ignored items:"
        )

        for i, ignore in enumerate(ignores[:10], 1):
            target_type = ignore.get("target_type", "unknown")
            reason = ignore.get("reason", "No reason provided")
            added_by = f"<@{ignore['added_by']}>" if ignore.get("added_by") else "Unknown"
            timestamp = ignore["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
            
            embed.add_field(
                name=f"{i}. {target_type.title()} - ID: {ignore['target_id']}",
                value=f"**Reason:** {reason}\n**Added by:** {added_by}\n**Date:** {timestamp}",
                inline=False
            )

        if len(ignores) > 10:
            embed.set_footer(text=f"And {len(ignores) - 10} more items...")

        await ctx.reply(embed=embed)

    @ignore.command(name="remove", description="Remove a channel or user from ignore list")
    @app_commands.guilds(discord.Object(id=1367173562971983963))
    @app_commands.describe(
        target_id="The ID of the channel or user to remove from ignore list"
    )
    async def ignore_remove(
        self,
        ctx: commands.Context,
        target_id: int
    ):
        """Remove a channel or user from the ignore list."""
        if not await StaffUtils.has_developer_permission_cross_guild(self.bot, ctx.author, "ignore"):
            embed = EmbedDesign.error(
                title="Permission Denied",
                description="You don't have permission to manage ignore list. This requires Developer access."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return

        # Update ignore record in PostgreSQL
        rows_affected = await self.bot.db.remove_ignore_by_target(ctx.guild.id, target_id)

        if rows_affected == 0:
            embed = EmbedDesign.error(
                title="Not Found",
                description="No active ignore found for this target."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return

        embed = EmbedDesign.success(
            title="Removed from Ignore List",
            description=f"Target ID **{target_id}** has been removed from the ignore list.",
            fields=[
                {"name": "Removed by", "value": ctx.author.mention, "inline": True}
            ]
        )
        await ctx.reply(embed=embed)

    def parse_duration(self, duration_str: str) -> timedelta:
        """Parse a duration string like '1d', '2h', '30m' into a timedelta."""
        import re
        
        # Remove any whitespace
        duration_str = duration_str.strip().lower()
        
        # Parse the duration
        match = re.match(r'^(\d+)([dhms])$', duration_str)
        if not match:
            raise ValueError(f"Invalid duration format: {duration_str}. Use format like '1d', '2h', '30m', '45s'")
        
        value, unit = match.groups()
        value = int(value)
        
        # Convert to timedelta
        if unit == 's':
            return timedelta(seconds=value)
        elif unit == 'm':
            return timedelta(minutes=value)
        elif unit == 'h':
            return timedelta(hours=value)
        elif unit == 'd':
            return timedelta(days=value)
        else:
            raise ValueError(f"Invalid time unit: {unit}")


async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationCommands(bot)) 