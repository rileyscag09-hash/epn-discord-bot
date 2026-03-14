"""
Preventative commands for EPN bot.
Handles blocking users and guilds from using the bot.
"""

import discord
from discord.ext import commands
from discord import app_commands
from typing import Union, Optional
from datetime import datetime
from utils.constants import logger, EmbedDesign
from utils.staff import StaffUtils


class PreventativeCommands(commands.Cog):
    """Commands for preventing users and guilds from using the bot."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_group(name="block", description="Commands for blocking users and guilds from using the bot")
    async def block(self, ctx: commands.Context):
        """Commands for blocking users and guilds from using the bot."""
        if ctx.interaction:
            # This is a slash command
            user = ctx.interaction.user
        else:
            # This is a prefix command
            user = ctx.author
        
        if not await StaffUtils.has_developer_permission_cross_guild(self.bot, user, "block"):
            embed = EmbedDesign.error(title="Permission Denied", description="You don't have permission to use block commands. This requires Developer access.")
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        await ctx.send("Use `/block-add`, `/block-remove`, or `/block-status` for specific blocking operations.")
    
    @block.command(name="add", description="Block a user or guild from using the bot")
    @app_commands.describe(
        target="The user or guild ID to block",
        reason="Reason for the block",
        evidence="Evidence supporting the block (optional)",
        expires="When the block expires (e.g., '1d', '2h', '30m' - optional)",
        appealable="Whether the block can be appealed (default: True)"
    )
    async def block_add(
        self, 
        ctx: commands.Context, 
        target: str, 
        reason: str, 
        evidence: str = None, 
        expires: str = None, 
        appealable: bool = True
    ):
        """Block a user or guild from using the bot."""
        if ctx.interaction:
            user = ctx.interaction.user
        else:
            user = ctx.author
            
        if not await StaffUtils.has_developer_permission_cross_guild(self.bot, user, "block"):
            embed = EmbedDesign.error(title="Permission Denied", description="You don't have permission to block users or guilds. This requires Developer access.")
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        try:
            target_id = int(target)
        except ValueError:
            embed = EmbedDesign.error(title="Invalid Target", description="Please provide a valid numeric user or guild ID.")
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        # Check if it's a user or guild by trying to fetch both
        user = None
        guild = None
        
        try:
            user = await self.bot.fetch_user(target_id)
        except:
            pass
        
        if not user:
            guild = self.bot.get_guild(target_id)
        
        if not user and not guild:
            embed = EmbedDesign.error(title="Target Not Found", description="Could not find a user or guild with that ID.")
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        # Parse expiry time
        expires_at = None
        if expires:
            try:
                from cogs.commands.EPN import EPNCommands
                expires_at = EPNCommands.parse_duration(EPNCommands, expires)
            except ValueError as e:
                embed = EmbedDesign.error(title="Invalid Expiry Time", description=str(e))
                await ctx.reply(embed=embed, ephemeral=True)
                return
        
        # Block the target
        if user:
            success = await self.bot.blocking_manager.block_user(
                target_id, reason, evidence or "", user.id, expires_at, appealable
            )
            target_name = user.display_name
            block_type = "user"
        else:
            success = await self.bot.blocking_manager.block_guild(
                target_id, reason, evidence or "", user.id, expires_at, appealable
            )
            target_name = guild.name
            block_type = "guild"
        
        if success:
            embed = EmbedDesign.success(
                title=f"{block_type.title()} Blocked",
                description=f"**{target_name}** has been blocked from using the bot."
            )
        else:
            embed = EmbedDesign.error(
                title="Block Failed",
                description=f"**{target_name}** is already blocked or the block operation failed."
            )
        
        await ctx.reply(embed=embed, ephemeral=True)
    
    @block.command(name="remove", description="Unblock a user or guild from using the bot")
    @app_commands.describe(
        target="The user or guild ID to unblock",
        reason="Reason for the unblock (optional)"
    )
    async def block_remove(
        self, 
        ctx: commands.Context, 
        target: str, 
        reason: str = "Appeal accepted"
    ):
        """Unblock a user or guild from using the bot."""
        if ctx.interaction:
            user = ctx.interaction.user
        else:
            user = ctx.author
            
        if not await StaffUtils.has_developer_permission_cross_guild(self.bot, user, "block"):
            embed = EmbedDesign.error(title="Permission Denied", description="You don't have permission to unblock users or guilds. This requires Developer access.")
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        try:
            target_id = int(target)
        except ValueError:
            embed = EmbedDesign.error(title="Invalid Target", description="Please provide a valid numeric user or guild ID.")
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        # Check if it's a user or guild by trying to fetch both
        user = None
        guild = None
        
        try:
            user = await self.bot.fetch_user(target_id)
        except:
            pass
        
        if not user:
            guild = self.bot.get_guild(target_id)
        
        if not user and not guild:
            embed = EmbedDesign.error(title="Target Not Found", description="Could not find a user or guild with that ID.")
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        # Unblock the target
        if user:
            success = await self.bot.blocking_manager.unblock_user(target_id, reason, user.id)
            target_name = user.display_name
            block_type = "user"
        else:
            success = await self.bot.blocking_manager.unblock_guild(target_id, reason, user.id)
            target_name = guild.name
            block_type = "guild"
        
        if success:
            embed = EmbedDesign.success(
                title=f"{block_type.title()} Unblocked",
                description=f"**{target_name}** has been unblocked from using the bot."
            )
        else:
            embed = EmbedDesign.error(
                title="Unblock Failed",
                description=f"**{target_name}** is not currently blocked or the unblock operation failed."
            )
        
        await ctx.reply(embed=embed, ephemeral=True)
    
    @block.command(name="status", description="Check if a user or guild is blocked")
    @app_commands.describe(target="The user or guild ID to check")
    async def block_status(self, ctx: commands.Context, target: str):
        """Check if a user or guild is blocked from using the bot."""
        if ctx.interaction:
            user = ctx.interaction.user
        else:
            user = ctx.author
            
        if not await StaffUtils.has_developer_permission_cross_guild(self.bot, user, "block"):
            embed = EmbedDesign.error(title="Permission Denied", description="You don't have permission to check block status. This requires Developer access.")
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        try:
            target_id = int(target)
        except ValueError:
            embed = EmbedDesign.error(title="Invalid Target", description="Please provide a valid numeric user or guild ID.")
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        # Check both user and guild blocks
        user_block = await self.bot.blocking_manager.is_user_blocked(target_id)
        guild_block = await self.bot.blocking_manager.is_guild_blocked(target_id)
        
        if user_block:
            # Try to get user info
            try:
                user = await self.bot.fetch_user(target_id)
                target_name = user.display_name
            except:
                target_name = f"User {target_id}"
            
            embed = self.bot.blocking_manager.create_block_embed("user", user or target_id, user_block)
            embed.title = f"Block Status - {target_name}"
        elif guild_block:
            # Try to get guild info
            guild = self.bot.get_guild(target_id)
            target_name = guild.name if guild else f"Guild {target_id}"
            
            embed = self.bot.blocking_manager.create_block_embed("guild", guild or target_id, guild_block)
            embed.title = f"Block Status - {target_name}"
        else:
            embed = EmbedDesign.success(
                title="Not Blocked",
                description=f"Target `{target_id}` is not currently blocked from using the bot."
            )
        
        await ctx.reply(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    """Load the PreventativeCommands cog."""
    await bot.add_cog(PreventativeCommands(bot))
