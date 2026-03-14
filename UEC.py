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
from utils.database import DatabaseManager

constants = Constants()
logger = logging.getLogger(__name__)


class UEC(commands.Bot):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.synced = False
        self.db: DatabaseManager | None = None
        self.verification_service = None
        self.command_verifier = None
        self.blocking_manager = None

    async def setup_hook(self):

        logger.info("Running setup_hook...")

        # -------------------------
        # DATABASE CONNECTION
        # -------------------------
        try:

            self.db = DatabaseManager(constants.database_url())
            await self.db.connect()

            logger.info("Database connected successfully")

        except Exception as e:

            logger.critical(f"Database connection failed: {e}")
            raise

        # -------------------------
        # LOAD COGS
        # -------------------------
        await self.load_extensions()

        # -------------------------
        # SYNC COMMANDS
        # -------------------------
        main_server = self.get_guild(constants.main_server_id())

        try:

            if main_server:

                await self.tree.sync(guild=main_server)
                logger.info(f"Commands synced to {main_server.name}")

            else:

                await self.tree.sync()
                logger.info("Commands synced globally")

            self.synced = True

        except Exception as e:

            logger.error(f"Command sync failed: {e}")

        logger.info("setup_hook completed")

    async def on_ready(self):

        logger.info(f"Logged in as {self.user} ({self.user.id})")

        # -------------------------
        # SENTRY
        # -------------------------
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

        # -------------------------
        # TWILIO
        # -------------------------
        try:

            self.verification_service = TwilioVerificationService(self)
            logger.info("Twilio verification service ready")

        except Exception as e:

            logger.error(f"Twilio failed: {e}")
            self.verification_service = None

        # -------------------------
        # COMMAND VERIFIER
        # -------------------------
        self.command_verifier = CommandVerifier(self)
        logger.info("Command verifier initialized")

        # -------------------------
        # BLOCKING MANAGER
        # -------------------------
        self.blocking_manager = BlockingManager(self)
        logger.info("Blocking manager ready")

        # -------------------------
        # GLOBAL BLOCK CHECK
        # -------------------------
        async def global_block_check(ctx: commands.Context):

            if ctx.author.id == constants.bot_owner_id():
                return True

            if not self.blocking_manager:
                return True

            user_block = await self.blocking_manager.is_user_blocked(ctx.author.id)

            if user_block:

                embed = self.blocking_manager.create_block_embed(
                    "user",
                    ctx.author,
                    user_block
                )

                await ctx.reply(embed=embed)
                return False

            if ctx.guild:

                guild_block = await self.blocking_manager.is_guild_blocked(ctx.guild.id)

                if guild_block:

                    embed = self.blocking_manager.create_block_embed(
                        "guild",
                        ctx.guild,
                        guild_block
                    )

                    await ctx.reply(embed=embed)
                    return False

            return True

        self.add_check(global_block_check)

        logger.info("Global blocking check registered")

    # -------------------------
    # SENTRY FILTER
    # -------------------------
    def before_send(self, event, hint):

        if constants.environment() == "development":
            return None

        if hint and "exc_info" in hint:

            exc_type, exc_value, exc_traceback = hint["exc_info"]

            if "discord.errors" in str(exc_type):
                return None

        return event

    # -------------------------
    # LOAD COGS
    # -------------------------
    async def load_extensions(self):

        Flags.RETAIN = True
        Flags.NO_DM_TRACEBACK = True
        Flags.FORCE_PAGINATOR = True
        Flags.NO_UNDERSCORE = True

        await self.load_extension("jishaku")

        if not os.path.exists("cogs"):

            logger.critical("No Cog Folder Found")
            sys.exit()

        for root, dirs, files in os.walk("cogs"):

            for file in files:

                if file.endswith(".py"):

                    module = os.path.join(root, file).replace(os.sep, ".")[:-3]

                    try:

                        await self.load_extension(module)
                        logger.info(f"Loaded {module}")

                    except Exception as e:

                        logger.error(f"Failed loading {module}: {e}")
                        traceback.print_exc()

    # -------------------------
    # MESSAGE HANDLER
    # -------------------------
    async def on_message(self, message: discord.Message):

        if message.author.bot:
            return

        if not message.guild:
            return

        await self.process_commands(message)

    # -------------------------
    # CLEAN SHUTDOWN
    # -------------------------
    async def close(self):

        try:

            if self.db:

                await self.db.disconnect()
                logger.info("Database disconnected")

        except Exception as e:

            logger.error(f"Error closing DB: {e}")

        await super().close()


# -------------------------
# BOT SETUP
# -------------------------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.presences = True


uec = UEC(
    command_prefix=commands.when_mentioned_or(";"),
    help_command=None,
    intents=intents,
    chunk_guilds_at_startup=False,
    owner_id=constants.bot_owner_id(),
    activity=discord.Activity(
        type=discord.ActivityType.listening,
        name="Protecting the community"
    ),
    allowed_mentions=discord.AllowedMentions(
        everyone=False,
        users=True,
        roles=True,
        replied_user=False
    ),
)


# -------------------------
# RUN BOT
# -------------------------
async def run():

    dev_mode = "--dev" in sys.argv

    try:

        token = constants.dev_token() if dev_mode else constants.token()

        logger.info(
            f"Running in {'development' if dev_mode else 'production'} mode"
        )

    except Exception as e:

        logger.critical(f"Token error: {e}")
        return

    try:

        async with uec:
            await uec.start(token)

    except KeyboardInterrupt:

        logger.info("Bot shutting down")

    except Exception as e:

        logger.error(f"Fatal bot error: {e}")

        if constants.sentry_dsn():
            sentry_sdk.capture_exception(e)

        raise


if __name__ == "__main__":
    asyncio.run(run())
