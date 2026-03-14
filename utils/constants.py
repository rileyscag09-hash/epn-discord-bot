import os
import colorlog
import logging
import asyncio
import discord
from dotenv import load_dotenv
import sys
from datetime import datetime

load_dotenv()


class Constants():
    def __init__(self):
        self.Auth_list = []

    def environment(self) -> str:
        """Get the current environment."""
        if "--dev" in sys.argv:
            return "development"
        return "production"

    def embed_color(self):
        DEFAULT_EMBED_COLOR = None
        return DEFAULT_EMBED_COLOR

    def token(self) -> str:
        """Retrieve the Discord bot token based on environment."""
        env = self.environment().lower()
        token_env_var = 'TOKEN_DEV' if env == 'development' else 'TOKEN'
        token_val = os.getenv(token_env_var)

        if not token_val:
            raise RuntimeError(f"{token_env_var} environment variable not set.")

        return token_val

    def openai_api_key(self) -> str:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            logger.warning("OPENAI_API_KEY environment variable not set. OpenAI features will be disabled.")
            return ""
        return key

    def postgres_url(self) -> str:
        """Retrieve PostgreSQL URL from environment variables."""
        if self.environment() == "development":
            dev_url = os.getenv("NEONDB_DEV")
            if dev_url:
                return dev_url
        else:
            full_url = os.getenv("NEONDB_PROD")
            if full_url:
                return full_url

        logger.warning("No PostgreSQL database URL configured for current environment.")
        return ""

    # -------------------------
    # FIX: DATABASE URL FOR BOT
    # -------------------------
    def database_url(self) -> str:
        """
        Universal database URL used by the bot.
        Falls back to SQLite if PostgreSQL is not configured.
        """
        postgres = self.postgres_url()

        if postgres:
            return postgres

        logger.warning("No PostgreSQL URL found, falling back to SQLite database.")
        return "sqlite:///data/database.db"

    def mongo_uri(self) -> str:
        return os.getenv("MONGO_URI", "")

    def sentry_dsn(self) -> str:
        return os.getenv("SENTRY_DSN", "")

    def sentry_environment(self) -> str:
        return self.environment()

    def bloxlink_api_key(self) -> str:
        key = os.getenv("BLOXLINK_API_KEY")
        if not key:
            logger.warning("BLOXLINK_API_KEY environment variable not set. Bloxlink features will be disabled.")
            return ""
        return key

    def web_risk_api_key(self) -> str:
        key = os.getenv("WEB_RISK_API_KEY")
        if not key:
            logger.warning("WEB_RISK_API_KEY environment variable not set. Web Risk features will be disabled.")
            return ""
        return key

    def dev_token(self) -> str:
        token = os.getenv("DEV_TOKEN")
        if not token:
            logger.warning("DEV_TOKEN environment variable not set.")
            return ""
        return token

    # Dashboard OAuth2 configuration

    def dashboard_client_id(self) -> str:
        client_id = os.getenv('DASHBOARD_CLIENT_ID')
        if not client_id:
            logger.error("DASHBOARD_CLIENT_ID environment variable not set.")
            return ""
        return client_id

    def dashboard_client_secret(self) -> str:
        client_secret = os.getenv('DASHBOARD_CLIENT_SECRET')
        if not client_secret:
            logger.error("DASHBOARD_CLIENT_SECRET environment variable not set.")
            return ""
        return client_secret

    def dashboard_redirect_uri(self) -> str:
        redirect_uri = os.getenv('DASHBOARD_REDIRECT_URI')
        if not redirect_uri:
            logger.error("DASHBOARD_REDIRECT_URI environment variable not set.")
            return ""
        return redirect_uri

    # -------------------------
    # SERVER IDS
    # -------------------------

    def main_server_id(self) -> int:
        return 1481746915438755932

    def uec_user_notification_channel_id(self) -> int:
        return 1481746917808537797

    def uec_server_notification_channel_id(self) -> int:
        return 1481746917808537797

    def developer_role_id(self) -> int:
        return 1481746915451207785

    def staff_role_id(self) -> int:
        return 1481746915438755936

    def affiliate_server_owner_id(self) -> int:
        return 1481746915438755935

    def affiliate_hr_id(self) -> int:
        return 1481746915438755934

    def report_channel_id(self) -> int:
        return 1481986056202096763

    # -------------------------
    # TWILIO
    # -------------------------

    def twilio_account_sid(self) -> str:
        return os.getenv("TWILIO_ACCOUNT_SID", "")

    def twilio_auth_token(self) -> str:
        return os.getenv("TWILIO_AUTH_TOKEN", "")

    def twilio_phone_number(self) -> str:
        return os.getenv("TWILIO_PHONE_NUMBER", "")

    def twilio_verify_service_sid(self) -> str:
        return os.getenv("TWILIO_VERIFY_SERVICE_SID", "")

    def twilio_debug_mode(self) -> bool:
        return os.getenv("TWILIO_DEBUG_MODE", "False").lower() in ("true", "1", "t")

    # -------------------------
    # OTHER API KEYS
    # -------------------------

    def melonly_api_key(self) -> str:
        key = os.getenv("MELONLY_API_KEY")
        if not key:
            logger.warning("MELONLY_API_KEY not set.")
            return ""
        return key

    def openrouter_api_key(self) -> str:
        key = os.getenv("OPENROUTER_API_KEY")
        if not key:
            logger.warning("OPENROUTER_API_KEY not set.")
            return ""
        return key

    def bot_owner_id(self) -> int:
        owner_id = os.getenv("BOT_OWNER_ID")

        if not owner_id:
            logger.warning("BOT_OWNER_ID environment variable not set.")
            return None

        try:
            return int(owner_id)
        except ValueError:
            logger.error("BOT_OWNER_ID is not a valid integer.")
            return None

    # -------------------------
    # INTERNAL API
    # -------------------------

    def internal_api_host(self) -> str:
        host = os.getenv("UEC_INTERNAL_API_HOST")
        if not host:
            logger.warning("UEC_INTERNAL_API_HOST not set.")
            return ""
        return host

    def internal_api_port(self) -> int:
        port_str = os.getenv("UEC_INTERNAL_API_PORT")

        if not port_str:
            logger.warning("UEC_INTERNAL_API_PORT not set.")
            return 0

        try:
            return int(port_str)
        except ValueError:
            logger.error("UEC_INTERNAL_API_PORT is not a valid integer.")
            return 0

    def internal_api_key(self) -> str:
        key = os.getenv("UEC_INTERNAL_API_KEY", "")

        if not key:
            logger.warning("UEC_INTERNAL_API_KEY not set.")

        return key


# Shared instance
constants = Constants()


# -------------------------
# EMBED DESIGN SYSTEM
# -------------------------

class EmbedDesign:

    SUCCESS = 0x4ade80
    ERROR = 0xf87171
    WARNING = 0xfbbf24
    INFO = 0x60a5fa
    NEUTRAL = 0x374151
    PRIMARY = 0x6366f1
    SECONDARY = 0x94a3b8

    @staticmethod
    def create_embed(title: str, description: str = None, color: int = None, fields: list = None, thumbnail: str = None, footer: str = None):

        if color is None:
            color = EmbedDesign.NEUTRAL

        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.utcnow()
        )

        if fields:
            for field in fields:
                embed.add_field(
                    name=field.get("name", ""),
                    value=field.get("value", ""),
                    inline=field.get("inline", True)
                )

        if thumbnail:
            embed.set_thumbnail(url=thumbnail)

        if footer:
            embed.set_footer(text=footer)

        return embed

    @staticmethod
    def success(title, description=None, fields=None):
        return EmbedDesign.create_embed(title, description, EmbedDesign.SUCCESS, fields)

    @staticmethod
    def error(title, description=None, fields=None):
        return EmbedDesign.create_embed(title, description, EmbedDesign.ERROR, fields)

    @staticmethod
    def warning(title, description=None, fields=None):
        return EmbedDesign.create_embed(title, description, EmbedDesign.WARNING, fields)

    @staticmethod
    def info(title, description=None, fields=None):
        return EmbedDesign.create_embed(title, description, EmbedDesign.INFO, fields)


# -------------------------
# LOGGER
# -------------------------

log = colorlog.ColoredFormatter(
    "%(blue)s[%(asctime)s]%(reset)s - %(filename)s - %(log_color)s%(levelname)s%(reset)s - %(message)s",
    datefmt='%Y-%m-%d %H:%M:%S',
    log_colors={
        'DEBUG': 'cyan',
        'INFO': 'green',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'bold_red',
    }
)

handler = logging.StreamHandler()
handler.setFormatter(log)

logger = logging.getLogger(__name__)
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)
