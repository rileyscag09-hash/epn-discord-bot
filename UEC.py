import discord
import asyncio
import os
import sys
import sentry_sdk
import traceback
import logging
from datetime import datetime
from discord.ext import commands
from discord import app_commands
from jishaku import Flags

from utils.constants import logger, Constants, EmbedDesign
from utils.twilio_verification import TwilioVerificationService, CommandVerifier
from utils.blocking import BlockingManager

# Initialize constants and logger
constants = Constants()
logger = logging.getLogger(__name__)


class UEC(commands.Bot):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.synced = False

    async def setup_hook(self):
        """Bot startup tasks: load cogs and sync commands."""
        logger.info("Running setup_hook...")

        # Load cogs first
        await self.load_extensions()

        # Get main server
        main_server = self.get_guild(constants.main_server_id())
        if main_server:
            logger.info(f"Main server found: {main_server.name}")
        else:
            logger.warning("Main server not found, syncing commands globally.")

        # Sync commands
        try:
            if main_server:
                await self.tree.sync(guild=main_server)
                logger.info(f"Commands synced to main server {main_server.name}")
            else:
                await self.tree.sync()
                logger.info("Commands synced globally")

            # DEBUG: log all loaded commands
            for cmd in self.tree.get_commands(guild=main_server):
                logger.info(f"Loaded slash command: {cmd.name}")

            self.synced = True
        except Exception as e:
            logger.error(f"Error syncing commands: {e}")

        logger.info("setup_hook finished")

    async def on_ready(self):
        logger.info(f"Logged in as {self.user} ({self.user.id})")

        # Sentry
        if constants.sentry_dsn():
            sentry_sdk.init(
                dsn=constants.sentry_dsn(),
                environment=constants.sentry_environment(),
                traces_sample_rate=1.0,
                profiles_sample_rate=1.0,
                enable_tracing=True,
                before_send=self.before_send,
                debug=constants.environment() == "development",
            )
            logger.info("Sentry initialized")
        else:
            logger.warning("Sentry DSN not configured")

        # Clear linked roles metadata
        try:
            await self.clear_linked_roles_metadata()
            logger.info("Linked roles metadata cleared")
        except Exception as e:
            logger.error(f"Failed clearing linked roles metadata: {e}")

        # Twilio verification
        try:
            self.verification_service = TwilioVerificationService(self)
            logger.info("Twilio verification service initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Twilio verification service: {e}")
            self.verification_service = None

        self.command_verifier = CommandVerifier(self)
        logger.info("Command verifier initialized")

        # Blocking manager
        self.blocking_manager = BlockingManager(self)
        logger.info("Blocking manager initialized")

        # Add global blocking check
        async def global_block_check(ctx: commands.Context) -> bool:
            if ctx.author.id == constants.bot_owner_id():
                return True
            if not hasattr(ctx.bot, "blocking_manager") or not ctx.bot.blocking_manager:
                return True

            user_block = await ctx.bot.blocking_manager.is_user_blocked(ctx.author.id)
            if user_block:
                embed = ctx.bot.blocking_manager.create_block_embed("user", ctx.author, user_block)
                await ctx.reply(embed=embed, ephemeral=True)
                return False

            if ctx.guild:
                guild_block = await ctx.bot.blocking_manager.is_guild_blocked(ctx.guild.id)
                if guild_block:
                    embed = ctx.bot.blocking_manager.create_block_embed("guild", ctx.guild, guild_block)
                    await ctx.reply(embed=embed, ephemeral=True)
                    return False

            return True

        self.add_check(global_block_check)
        logger.info("Global blocking check added successfully")

    def before_send(self, event, hint):
        """Filter Sentry events before sending."""
        if constants.environment() == "development":
            return None
        if hint and 'exc_info' in hint:
            exc_type, exc_value, exc_traceback = hint['exc_info']
            if "discord.errors" in str(exc_type) or "discord.Forbidden" in str(exc_type):
                return None
        return event

    async def load_extensions(self):
        """Load all cogs asynchronously."""
        Flags.RETAIN = True
        Flags.NO_DM_TRACEBACK = True
        Flags.FORCE_PAGINATOR = True
        Flags.NO_UNDERSCORE = True

        await self.load_extension("jishaku")

        if os.path.exists("cogs"):
            for root, dirs, files in os.walk("cogs"):
                for file in files:
                    if file.endswith(".py"):
                        module_path = os.path.join(root, file).replace(os.sep, ".")[:-3]
                        try:
                            await self.load_extension(module_path)
                            logger.info(f"Loaded extension {module_path}")
                        except Exception as e:
                            logger.error(f"Error loading {module_path}: {e}")
                            traceback.print_exc()
        else:
            logger.critical("No Cog Folder Found")
            sys.exit("No Cog Folder Found")

    async def clear_linked_roles_metadata(self):
        try:
            main_server = self.get_guild(constants.main_server_id())
            if not main_server:
                logger.warning("Main server not found")
                return

            cleared_count = 0
            for member in main_server.members:
                try:
                    await member.edit(role_connections=[])
                    cleared_count += 1
                except discord.Forbidden:
                    logger.warning(f"Cannot clear role connections for {member.display_name}")
                except Exception as e:
                    logger.error(f"Error clearing role connections for {member.display_name}: {e}")

            logger.info(f"Cleared linked roles metadata for {cleared_count} members")
        except Exception as e:
            logger.error(f"Error clearing linked roles metadata: {e}")

    async def on_message(self, message: discord.Message):
        await self.wait_until_ready()
        if message.author.bot or message.guild is None:
            return
        await self.process_commands(message)

    async def close(self):
        try:
            from utils.security_logger import close_security_logger
            await close_security_logger()
        except Exception as e:
            logger.error(f"Error closing security logger: {e}")
        await super().close()


# ------------------------------
# Instantiate bot
# ------------------------------
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
    activity=discord.Activity(
        type=discord.ActivityType.listening,
        name="Protecting the community 1 server at a time%"
    ),
    allowed_mentions=discord.AllowedMentions(
        everyone=False,
        users=True,
        roles=True,
        replied_user=False
    ),
)


# ------------------------------
# Run function
# ------------------------------
async def run():
    dev_mode = "--dev" in sys.argv
    no_auth = "--no-auth" in sys.argv
    uec.no_auth = no_auth

    try:
        token_value = constants.dev_token() if dev_mode else constants.token()
        logger.info(f"Running in {'development' if dev_mode else 'production'} mode")
    except Exception as e:
        logger.critical(f"Failed to get bot token: {e}")
        return

    try:
        async with uec:
            await uec.start(token_value)
    except KeyboardInterrupt:
        logger.info("Bot shutdown requested")
    except Exception as e:
        logger.error(f"Critical error running bot: {e}")
        if constants.sentry_dsn():
            sentry_sdk.capture_exception(e)
        raise
