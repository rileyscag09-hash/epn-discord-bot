import discord
import asyncio
import os
import sys
import sentry_sdk
import traceback
import pathlib
from utils.constants import logger, Constants, EmbedDesign
from utils.database import DatabaseManager
from utils.twilio_verification import TwilioVerificationService, CommandVerifier
from utils.blocking import BlockingManager
from discord.ext import commands
from discord import app_commands
from datetime import datetime
from cogwatch import watch
from typing import Any, Optional
from jishaku import Flags
# API module removed for security

# Initialize constants
constants = Constants()

import discord
import logging
from discord.ext import commands
from constants import constants

logger = logging.getLogger(__name__)

class UEC(commands.Bot):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.synced = False

    async def setup_hook(self):
        """Bot startup tasks: syncing slash commands."""
        logger.info("Running setup_hook...")

        # Try to get main server
        main_server = self.get_guild(constants.main_server_id())
        if main_server is None:
            logger.warning("Main server not found, commands will sync globally.")
        else:
            logger.info(f"Main server found: {main_server.name}")

        # Sync commands
        if not self.synced:
            try:
                guild_id = constants.main_server_id()
                if guild_id:
                    await self.tree.sync(guild=discord.Object(id=guild_id))
                    logger.info(f"Commands synced to main server {guild_id}")
                else:
                    await self.tree.sync()
                    logger.info("Commands synced globally")
                self.synced = True
            except Exception as e:
                logger.error(f"Error syncing commands: {e}")

        logger.info("setup_hook finished")

async def on_ready(self):
    logger.info(f"Logged in as {self.user} ({self.user.id})")

    # Sentry Setup
    if constants.sentry_dsn():
                sentry_sdk.init(
                    dsn=constants.sentry_dsn(),
                    environment=constants.sentry_environment(),
                    traces_sample_rate=1.0,
                    profiles_sample_rate=1.0,
                    enable_tracing=True,
                    before_send=self.before_send,
                    debug=constants.environment() == "development"
                )
                logger.info("Sentry initialized")
            else:
                logger.warning("Sentry DSN not configured - error tracking disabled")
            
            # Clear linked roles metadata on startup
            await self.clear_linked_roles_metadata()
            logger.info("Linked roles metadata cleared on startup")
            
            # Initialize Twilio verification service
            try:
                self.verification_service = TwilioVerificationService(self)
                logger.info("Twilio verification service initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Twilio verification service: {e}")
                self.verification_service = None
            
            self.command_verifier = CommandVerifier(self)
            logger.info("Command verifier initialized")
            
            # Initialize blocking manager
            self.blocking_manager = BlockingManager(self)
            logger.info("Blocking manager initialized")
            

            await self.load_extensions()
            
            # Add global blocking check after everything is loaded
            async def global_block_check(ctx: commands.Context) -> bool:
                """Global check to prevent blocked users/guilds from using commands."""
                logger.info(f"=== GLOBAL CHECK RUNNING for user {ctx.author.id} on command {ctx.command} ===")
                
                # Bot owner bypasses all blocking checks (important for jishaku and other owner commands)
                if ctx.author.id == constants.bot_owner_id():
                    logger.info(f"User {ctx.author.id} is bot owner, bypassing blocking checks")
                    return True
                
                # Check if blocking manager is available
                if not hasattr(ctx.bot, 'blocking_manager') or not ctx.bot.blocking_manager:
                    logger.warning("Blocking manager not available in global check")
                    return True
                
                # Check user block
                user_block = await ctx.bot.blocking_manager.is_user_blocked(ctx.author.id)
                logger.info(f"User block result for {ctx.author.id}: {user_block}")
                if user_block:
                    logger.info(f"User {ctx.author.id} is blocked, preventing command execution")
                    embed = ctx.bot.blocking_manager.create_block_embed("user", ctx.author, user_block)
                    await ctx.reply(embed=embed, ephemeral=True)
                    return False
                
                # Check guild block (only if in a guild)
                if ctx.guild:
                    guild_block = await ctx.bot.blocking_manager.is_guild_blocked(ctx.guild.id)
                    logger.info(f"Guild block result for {ctx.guild.id}: {guild_block}")
                    if guild_block:
                        logger.info(f"Guild {ctx.guild.id} is blocked, preventing command execution")
                        embed = ctx.bot.blocking_manager.create_block_embed("guild", ctx.guild, guild_block)
                        await ctx.reply(embed=embed, ephemeral=True)
                        return False
                
                logger.info(f"User {ctx.author.id} is not blocked, allowing command execution")
                return True
            
            # Add the global check
            self.add_check(global_block_check)
            logger.info("Global blocking check added successfully")
        except Exception as e:
            logger.error(f"Error in setup_hook: {e}")
            raise e

    def before_send(self, event, hint):
        """Filter Sentry events before sending."""
        # Don't send events in development mode
        if constants.environment() == "development":
            return None
        
        # Filter out certain error types
        if hint and 'exc_info' in hint:
            exc_type, exc_value, exc_traceback = hint['exc_info']
            # Don't send Discord API errors
            if "discord.errors" in str(exc_type):
                return None
            # Don't send permission errors
            if "discord.Forbidden" in str(exc_type):
                return None
        
        return event
    
    async def load_extensions(self):
        Flags.RETAIN = True
        Flags.NO_DM_TRACEBACK = True
        Flags.FORCE_PAGINATOR = True
        Flags.NO_UNDERSCORE = True
        
        await self.load_extension("jishaku")
        
        if os.path.exists("cogs"):
            for root, dirs, files in os.walk("cogs"):
                for file in files:
                    if file.endswith(".py"):
                        rel_path = os.path.join(root, file)
                        module_path = rel_path.replace(os.sep, ".")[:-3]
                        try:
                            await self.load_extension(module_path)
                        except Exception as e:
                            logger.error(f"Error loading extension {rel_path}: {e}")
                            traceback.print_exc()
        else:
            logger.critical("No Cog Folder Found")
            sys.exit("No Cog Folder Found")

    if not self.synced:
        try:
            # Sync commands only to main server (faster, avoids global rate limits)
            main_guild = discord.Object(id=constants.main_server_id())
            await self.tree.sync(guild=main_guild)
            
            logger.info(f"Command tree synced for main server: {main_guild.id}")
        except Exception as e:
            logger.error(f"Error syncing command tree: {e}")
            if constants.sentry_dsn():
                sentry_sdk.capture_exception(e)

        self.synced = True
        
    async def on_error(self, event_method: str, *args, **kwargs):
        """Global error handler for bot events."""
        import uuid
        import traceback
        
        exc_info = sys.exc_info()
        error_id = str(uuid.uuid4())[:8].upper()
        
        logger.error(f"Error in {event_method}: {exc_info[1]} (ID: {error_id})")
        
        if constants.sentry_dsn():
            sentry_sdk.capture_exception(exc_info[1])
        
        # Log error to dev server channel
        await self.log_error_to_dev_server(event_method, exc_info[1], error_id, exc_info[2])
        
        # Re-raise the exception for proper handling
        raise exc_info[1]

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """Global error handler for commands."""
        import uuid
        
        # Don't handle CheckFailure errors as they're expected for blacklisted users
        if isinstance(error, commands.CommandNotFound):
            # Safely ignore command not found errors
            return
        
        if isinstance(error, commands.BadArgument):
            # Safely ignore invalid argument errors
            return
        
        if isinstance(error, commands.MissingRequiredArgument):
            # Safely ignore missing argument errors
            return
        
        if isinstance(error, commands.TooManyArguments):
            # Safely ignore too many arguments errors
            return
        
        if isinstance(error, commands.CheckFailure):
            # Check if this is a blocking-related CheckFailure from our global check
            # Our global check sends the embed and returns False, which causes CheckFailure
            # We can detect this by checking if the error message is generic
            if "check functions" in str(error):
                # This is likely from our global check, which already sent the embed
                # Just return silently to avoid the duplicate "Permission Denied" message
                # This is the same as the global check
                return
            # For other CheckFailure errors, send a generic permission denied message
            embed = EmbedDesign.error(title="Permission Denied", description=str(error))
            await ctx.reply(embed=embed, ephemeral=True)
            
            # Check for suspicious permission escalation attempts
            try:
                from utils.suspicious_activity_detector import get_suspicious_activity_detector
                detector = get_suspicious_activity_detector(self)
                await detector.check_permission_escalation_attempt(ctx, error)
            except Exception as e:
                logger.error(f"Error in suspicious activity detection: {e}")
            return
        
        error_id = str(uuid.uuid4())[:8].upper()
        logger.error(f"Command error in {ctx.command}: {error} (ID: {error_id})")
        
        if constants.sentry_dsn():
            sentry_sdk.capture_exception(error)
        
        # Log error to dev server channel
        await self.log_error_to_dev_server(f"Command: {ctx.command}", error, error_id)
        
        # Send simple error message to user
        embed = EmbedDesign.error(
            title="Something went wrong",
            description="We're sorry, but an error occurred while processing your command.",
            fields=[
                {"name": "Error ID", "value": f"`{error_id}`", "inline": True},
                {"name": "Support", "value": "Please provide this Error ID when reporting the issue.", "inline": True}
            ]
        )
        
        try:
            msg = await ctx.reply(embed=embed, ephemeral=True)
            # Delete error message after 15 seconds
            await asyncio.sleep(15)
            try:
                await msg.delete()
            except:
                pass
        except:
            # Fallback if we can't reply
            pass
        
        # Don't re-raise command errors to prevent bot crashes
        pass

    async def close(self):
        # Close security logger
        try:
            from utils.security_logger import close_security_logger
            await close_security_logger()
        except Exception as e:
            logger.error(f"Error closing security logger: {e}")
        await super().close()

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Global error handler for slash commands."""
        import uuid
        
        error_id = str(uuid.uuid4())[:8].upper()
        logger.error(f"Slash command error in {interaction.command}: {error} (ID: {error_id})")
        
        if constants.sentry_dsn():
            sentry_sdk.capture_exception(error)
        
        # Log error to dev server channel
        await self.log_error_to_dev_server(f"Slash Command: {interaction.command}", error, error_id)
        
        # Send simple error message to user
        embed = EmbedDesign.error(
            title="Something went wrong",
            description="We're sorry, but an error occurred while processing your command.",
            fields=[
                {"name": "Error ID", "value": f"`{error_id}`", "inline": True},
                {"name": "Support", "value": "Please provide this Error ID when reporting the issue.", "inline": True}
            ]
        )
        
        try:
            if interaction.response.is_done():
                msg = await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                msg = await interaction.response.send_message(embed=embed, ephemeral=True)
            
            # Delete error message after 15 seconds
            await asyncio.sleep(15)
            try:
                await msg.delete()
            except:
                pass
        except:
            # Fallback if we can't reply
            pass
        
        # Don't re-raise command errors to prevent bot crashes
        pass

    async def log_error_to_dev_server(self, event_method: str, error: Exception, error_id: str, traceback_obj=None):
        """Log error to the dev server channel."""
        try:
            # Get the dev server and error channel
            dev_server = self.get_guild(constants.main_server_id())
            if not dev_server:
                logger.error("Dev server not found")
                return
                
            error_channel = dev_server.get_channel(1402154863034372238)
            if not error_channel:
                logger.error("Error channel not found")
                return
            
            # Prepare fields for error embed
            fields = [
                {"name": "Error ID", "value": f"`{error_id}`", "inline": True},
                {"name": "Error Type", "value": f"`{type(error).__name__}`", "inline": True},
                {"name": "Error Message", "value": f"```{str(error)[:1000]}```", "inline": False}
            ]
            
            if traceback_obj:
                # Get traceback as string
                import traceback as tb
                tb_str = ''.join(tb.format_tb(traceback_obj))
                if len(tb_str) > 1000:
                    tb_str = tb_str[:1000] + "..."
                fields.append({"name": "Traceback", "value": f"```{tb_str}```", "inline": False})
            
            fields.extend([
                {"name": "Environment", "value": constants.environment(), "inline": True},
                {"name": "Timestamp", "value": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), "inline": True}
            ])
            
            # Create error embed using EmbedDesign system
            embed = EmbedDesign.error(
                title="Bot Error",
                description=f"Error occurred in `{event_method}`",
                fields=fields
            )
            
            await error_channel.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error logging to dev server: {e}")
    
    async def clear_linked_roles_metadata(self):
        """Clear all linked roles metadata from Discord."""
        try:
            # Get the main server
            main_server = self.get_guild(constants.main_server_id())
            if not main_server:
                logger.warning("Main server not found, cannot clear linked roles metadata")
                return
            
            # Clear role connections for all members
            cleared_count = 0
            for member in main_server.members:
                try:
                    # Clear role connections metadata
                    await member.edit(role_connections=[])
                    cleared_count += 1
                except discord.Forbidden:
                    logger.warning(f"Cannot clear role connections for {member.display_name} - missing permissions")
                except Exception as e:
                    logger.error(f"Error clearing role connections for {member.display_name}: {e}")
            
            logger.info(f"Cleared linked roles metadata for {cleared_count} members")
            
        except Exception as e:
            logger.error(f"Error clearing linked roles metadata: {e}")
    
    async def on_message(self, message: discord.Message):
        await self.wait_until_ready()
        if message.author.bot or message.guild is None:
            return
        
        async def chunk_guild(guild: discord.Guild):
            try:
                await asyncio.sleep(1.5)
                
                if guild.chunked is False:
                    await guild.chunk(cache=True)
            except Exception as e:
                logger.error(f"Error chunking guild {guild.id}: {e}")
                # Don't send apology for chunking errors as they're internal

        try:
            for guild in sorted(
                self.guilds,
                key=lambda g: g.member_count or 0,
                reverse=True
            ):
                if guild.chunked is False:
                    await asyncio.sleep(1e-3)
                    await self.loop.create_task(chunk_guild(guild))
                    
            self.guilds_chunked.set()
            self.loop.create_task(self.process_commands(message))
        except Exception as e:
            error_id = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{hash(str(e)) % 10000:04d}"
            logger.error(f"Error in on_message: {e} (ID: {error_id})")
            
            # Send apology to the user
            try:
                embed = EmbedDesign.error(
                    title="Bot Error",
                    description="Oopsie, an error occurred while processing your message.",
                    fields=[
                        {"name": "Error ID", "value": f"`{error_id}`", "inline": True},
                        {"name": "Error Type", "value": f"`{type(e).__name__}`", "inline": True},
                        {"name": "What happened?", "value": "The bot encountered an unexpected error. This has been logged and will be investigated.", "inline": False}
                    ]
                )
                await message.channel.send(embed=embed)
            except Exception as send_error:
                logger.error(f"Failed to send error apology: {send_error}")


# Create intents with members enabled
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.presences = True
uec = UEC(
    command_prefix=commands.when_mentioned_or(";"),
    chunk_guilds_at_startup=False,
    help_command=None,
    intents=intents,
    owner_id=constants.bot_owner_id(),
    activity=discord.Activity(type=discord.ActivityType.listening, name="Protecting the community 1 server at a time%"),
    allowed_mentions=discord.AllowedMentions(
        everyone=False,
        users=True,
        roles=True,
        replied_user=False
    ),
)

# Global check function will be defined in setup_hook

# Add the before_invoke decorator to the bot instance
@uec.before_invoke
async def before_invoke(ctx: commands.Context):
    """Automatically defer commands unless they need an immediate initial response (e.g., commands that open modals)."""
    try:
        # Blocking is now handled by the global check function
        
        # Check for suspicious command usage patterns
        try:
            from utils.suspicious_activity_detector import get_suspicious_activity_detector
            detector = get_suspicious_activity_detector(uec)
            await detector.check_command_spam(ctx)
        except Exception as e:
            logger.error(f"Error in suspicious activity detection: {e}")
        
        # Commands that respond with a modal must not bimage.png deferred, because showing a modal must be the first response.
        # Also includes commands that use 2FA verification as they need to send initial response immediately.
        modal_commands = {
            "tag create",
            "tag edit", 
            "test verification", 
            "my account",
            "uec authorize",
            "uec unauthorize"
        }
        
        # UEC commands that use verification should not be deferred here as they handle deferral in verification flow
        uec_verification_commands = {
            "uec ban",
            "uec unban", 
            "uec serverban",
            "uec serverunban",
            "uec update"
        }
        if ctx.command.qualified_name in modal_commands or ctx.command.qualified_name in uec_verification_commands:
            return
        # Defer the command response for all other commands to give the bot more processing time.
        await ctx.defer()
    except Exception as e:
        logger.error(f"Error in before_invoke for command {ctx.command}: {e}")        


async def run():
    # Parse command line arguments
    dev_mode = "--dev" in sys.argv
    no_auth = "--no-auth" in sys.argv
    
    # Set the no_auth flag on the bot instance
    uec.no_auth = no_auth
    
    if constants.environment() == "production" and constants.sentry_dsn():
        # Sentry is already initialized in setup_hook
        pass
    
    try:
        # Set token based on mode
        if dev_mode:
            token_value = constants.dev_token()
            logger.info("Running in development mode with dev token")
        else:
            token_value = constants.token()
            logger.info("Running in production mode")
        
        # Log OAuth server status
        if no_auth:
            logger.info("OAuth server disabled via --no-auth flag")
        
    except RuntimeError as e:
        logger.critical(e)
        return

    try:
        async with uec:
            await uec.start(token_value)
    except KeyboardInterrupt:
        logger.info("Bot shutdown requested")
    except Exception as e:
        logger.error(f"Critical error running bot: {e}")
        # Capture the error in Sentry if configured
        if constants.sentry_dsn():
            sentry_sdk.capture_exception(e)
        raise 
