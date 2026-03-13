"""
Blocking utility for UEC bot.
Handles blocking users and guilds from using the bot.
"""

import discord
from discord.ext import commands
from typing import Optional, Dict, Any, Union
from datetime import datetime
from utils.constants import logger, EmbedDesign
from utils.database import DatabaseManager


class BlockingManager:
    """Manages user and guild blocking functionality."""
    
    def __init__(self, bot):
        self.bot = bot
        self.db: DatabaseManager = bot.db
    
    async def is_user_blocked(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Check if a user is blocked from using the bot."""
        try:
            logger.info(f"Blocking system - checking user_blocks table for user_id={user_id}")
            result = await self.db.find_user_block(user_id, active=True)
            logger.info(f"Blocking system - user_blocks result for {user_id}: {result}")
            return result
        except Exception as e:
            logger.error(f"Error checking user block status for {user_id}: {e}")
            return None
    
    async def is_guild_blocked(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Check if a guild is blocked from using the bot."""
        try:
            return await self.db.find_guild_block(guild_id, active=True)
        except Exception as e:
            logger.error(f"Error checking guild block status for {guild_id}: {e}")
            return None
    
    async def block_user(self, user_id: int, reason: str, evidence: str = "", 
                        blocked_by: int = None, expires_at: datetime = None, 
                        appeal_allowed: bool = True) -> bool:
        """Block a user from using the bot."""
        try:
            # Check if already blocked
            existing = await self.db.find_user_block(user_id, active=True)
            if existing:
                return False
            
            await self.db.insert_user_block(
                user_id, reason, evidence, blocked_by or self.bot.user.id, 
                expires_at, appeal_allowed
            )
            return True
        except Exception as e:
            logger.error(f"Error blocking user {user_id}: {e}")
            return False
    
    async def unblock_user(self, user_id: int, reason: str = "Appeal accepted", 
                          unblocked_by: int = None) -> bool:
        """Unblock a user from using the bot."""
        try:
            result = await self.db.deactivate_user_block(
                user_id, unblocked_by or self.bot.user.id, reason
            )
            return result
        except Exception as e:
            logger.error(f"Error unblocking user {user_id}: {e}")
            return False
    
    async def block_guild(self, guild_id: int, reason: str, evidence: str = "",
                         blocked_by: int = None, expires_at: datetime = None,
                         appeal_allowed: bool = True) -> bool:
        """Block a guild from using the bot."""
        try:
            # Check if already blocked
            existing = await self.db.find_guild_block(guild_id, active=True)
            if existing:
                return False
            
            guild = self.bot.get_guild(guild_id)
            guild_name = guild.name if guild else "Unknown Server"
            
            await self.db.insert_guild_block(
                guild_id, guild_name, reason, evidence, 
                blocked_by or self.bot.user.id, expires_at, appeal_allowed
            )
            return True
        except Exception as e:
            logger.error(f"Error blocking guild {guild_id}: {e}")
            return False
    
    async def unblock_guild(self, guild_id: int, reason: str = "Appeal accepted",
                           unblocked_by: int = None) -> bool:
        """Unblock a guild from using the bot."""
        try:
            result = await self.db.deactivate_guild_block(
                guild_id, unblocked_by or self.bot.user.id, reason
            )
            return result
        except Exception as e:
            logger.error(f"Error unblocking guild {guild_id}: {e}")
            return False
    
    def create_block_embed(self, block_type: str, target: Union[discord.User, discord.Member, discord.Guild, int], 
                          block_record: Dict[str, Any]) -> discord.Embed:
        """Create an embed explaining that a user/guild is blocked."""
        if block_type == "user":
            title = "Unauthorized (401)"
            if isinstance(target, int):
                username = f"User {target}"
            else:
                username = target.display_name if hasattr(target, 'display_name') else str(target)
            description = f"Hey {username}, your access to UEC has been terminated and you are no longer authorized to interact with, manipulate or interfere with the service. Please cease use immediately."
        else:
            title = "Unauthorized (401)"
            if isinstance(target, int):
                server_name = f"Server {target}"
            else:
                server_name = target.name if hasattr(target, 'name') else str(target)
            description = f"Hey {server_name}, your access to UEC has been terminated and you are no longer authorized to interact with, manipulate or interfere with the service. Please cease use immediately."
        
        return EmbedDesign.error(
            title=title,
            description=description
        )
    
    async def check_and_handle_block(self, ctx: commands.Context) -> bool:
        """
        Check if the user or guild is blocked and handle the response.
        Returns True if blocked (command should be cancelled), False if allowed.
        """
        try:
            # Check user block
            user_block = await self.is_user_blocked(ctx.author.id)
            if user_block:
                return True
            
            # Check guild block (only if in a guild)
            if ctx.guild:
                guild_block = await self.is_guild_blocked(ctx.guild.id)
                if guild_block:
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error in check_and_handle_block: {e}")
            # If there's an error, allow the command to proceed to avoid breaking the bot
            return False
    
    def block_check(self):
        """Create a check function for blocking users and guilds."""
        async def predicate(ctx: commands.Context) -> bool:
            try:
                # Check user block
                user_block = await self.is_user_blocked(ctx.author.id)
                if user_block:
                    embed = self.create_block_embed("user", ctx.author, user_block)
                    await ctx.reply(embed=embed, ephemeral=True)
                    return False
                
                # Check guild block (only if in a guild)
                if ctx.guild:
                    guild_block = await self.is_guild_blocked(ctx.guild.id)
                    if guild_block:
                        embed = self.create_block_embed("guild", ctx.guild, guild_block)
                        await ctx.reply(embed=embed, ephemeral=True)
                        return False
                
                return True
                
            except Exception as e:
                logger.error(f"Error in block_check: {e}")
                # If there's an error, allow the command to proceed to avoid breaking the bot
                return True
        
        return commands.check(predicate)
