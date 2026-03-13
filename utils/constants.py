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
        # Check if --dev flag is provided
        if "--dev" in sys.argv:
            return "development"
        return "production"
    
    def embed_color(self):
        DEFAULT_EMBED_COLOR = None
        return DEFAULT_EMBED_COLOR

    def token(self) -> str:
        """Retrieve the Discord bot token based on environment.

        In development we expect TOKEN_DEV; otherwise TOKEN. Raises RuntimeError if missing.
        """
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
        # Check if a full URL is provided based on environment
        if self.environment() == "development":
            # Try development-specific URL first
            dev_url = os.getenv("NEONDB_DEV")
            if dev_url:
                return dev_url
        else:
            # Production environment
            full_url = os.getenv("NEONDB_PROD")
            if full_url:
                return full_url
        
        # Fallback - no database URL configured
        logger.warning("No PostgreSQL database URL configured for current environment.")
        return ""
    
    def mongo_uri(self) -> str:
        """Retrieve MongoDB URI from environment variables."""
        return os.getenv("MONGO_URI", "")

    def sentry_dsn(self) -> str:
        """Retrieve Sentry DSN from environment variables."""
        return os.getenv("SENTRY_DSN", "")

    def sentry_environment(self) -> str:
        """Get Sentry environment based on current environment."""
        return self.environment()

    def bloxlink_api_key(self) -> str:
        """Retrieve Bloxlink API key from environment variables."""
        key = os.getenv("BLOXLINK_API_KEY")
        if not key:
            logger.warning("BLOXLINK_API_KEY environment variable not set. Bloxlink features will be disabled.")
            return ""
        return key

    def web_risk_api_key(self) -> str:
        """Retrieve Google Web Risk API key from environment variables."""
        key = os.getenv("WEB_RISK_API_KEY")
        if not key:
            logger.warning("WEB_RISK_API_KEY environment variable not set. Web Risk features will be disabled.")
            return ""
        return key

    def dev_token(self) -> str:
        """Retrieve dev token from environment variables."""
        token = os.getenv("DEV_TOKEN")
        if not token:
            logger.warning("DEV_TOKEN environment variable not set. Dev features will be disabled.")
            return ""
        return token


    # Dashboard OAuth2 (Discord) configuration
    def dashboard_client_id(self) -> str:
        client_id = os.getenv('DASHBOARD_CLIENT_ID')
        if not client_id:
            logger.error("DASHBOARD_CLIENT_ID environment variable not set. Dashboard OAuth will not work.")
            return ""
        return client_id

    def dashboard_client_secret(self) -> str:
        client_secret = os.getenv('DASHBOARD_CLIENT_SECRET')
        if not client_secret:
            logger.error("DASHBOARD_CLIENT_SECRET environment variable not set. Dashboard OAuth will not work.")
            return ""
        return client_secret

    def dashboard_redirect_uri(self) -> str:
        redirect_uri = os.getenv('DASHBOARD_REDIRECT_URI')
        if not redirect_uri:
            logger.error("DASHBOARD_REDIRECT_URI environment variable not set. Dashboard OAuth will not work.")
            return ""
        return redirect_uri

    # Server and role IDs
    def main_server_id(self) -> int:
        """Get the main server ID."""
        return 1481746915438755932
    
    def uec_user_notification_channel_id(self) -> int:
        """Get the UEC user ban/unban notification channel ID."""
        return 1481746917808537797
    
    def uec_server_notification_channel_id(self) -> int:
        """Get the UEC server ban/unban notification channel ID."""
        return 1481746917808537797

    def developer_role_id(self) -> int:
        """Get the developer role ID."""
        return 1481746915451207785

    def staff_role_id(self) -> int:
        """Get the staff role ID."""
        return 1481746915438755936
    
    def affiliate_server_owner_id(self) -> int:
        """Get the affiliate server owner ID."""
        return 1481746915438755935
    
    def affiliate_hr_id(self) -> int:
        """Get the affiliate HR role ID."""
        return 1481746915438755934

    def report_channel_id(self) -> int:
        """Get the report channel ID in the main server."""
        return 1481986056202096763

    def twilio_account_sid(self) -> str:
        """Get Twilio Account SID."""
        return os.getenv("TWILIO_ACCOUNT_SID", "")
    
    def twilio_auth_token(self) -> str:
        """Get Twilio Auth Token."""
        return os.getenv("TWILIO_AUTH_TOKEN", "")
    
    def twilio_phone_number(self) -> str:
        """Get Twilio phone number for sending SMS."""
        return os.getenv("TWILIO_PHONE_NUMBER", "")
    
    def twilio_verify_service_sid(self) -> str:
        """Get Twilio Verify Service SID for 2FA."""
        return os.getenv("TWILIO_VERIFY_SERVICE_SID", "")

    def twilio_debug_mode(self) -> bool:
        """Check if Twilio debug mode is enabled."""
        return os.getenv("TWILIO_DEBUG_MODE", "False").lower() in ("true", "1", "t")
    
    def melonly_api_key(self) -> str:
        """Retrieve Melonly API key from environment variables."""
        key = os.getenv("MELONLY_API_KEY")
        if not key:
            logger.warning("MELONLY_API_KEY environment variable not set. Melonly features will be disabled.")
            return ""
        return key
    
    def openrouter_api_key(self) -> str:
        """Retrieve OpenRouter API key from environment variables."""
        key = os.getenv("OPENROUTER_API_KEY")
        if not key:
            logger.warning("OPENROUTER_API_KEY environment variable not set. OpenRouter features will be disabled.")
            return ""
        return key
    
    def bot_owner_id(self) -> int:
        """Retrieve bot owner ID from environment variables."""
        owner_id = os.getenv("BOT_OWNER_ID")
        if not owner_id:
            logger.warning("BOT_OWNER_ID environment variable not set. Jishaku and other owner commands may not work.")
            return None
        try:
            return int(owner_id)
        except ValueError:
            logger.error("BOT_OWNER_ID is not a valid integer.")
            return None

    # Internal API configuration
    def internal_api_host(self) -> str:
        """Host interface for the internal HTTP API server."""
        host = os.getenv("UEC_INTERNAL_API_HOST")
        if not host:
            logger.warning("UEC_INTERNAL_API_HOST not set. Internal API will be disabled.")
            return ""
        return host

    def internal_api_port(self) -> int:
        """Port for the internal HTTP API server."""
        port_str = os.getenv("UEC_INTERNAL_API_PORT")
        if not port_str:
            logger.warning("UEC_INTERNAL_API_PORT not set. Internal API will be disabled.")
            return 0
        try:
            return int(port_str)
        except ValueError:
            logger.error("UEC_INTERNAL_API_PORT is not a valid integer. Internal API will be disabled.")
            return 0

    def internal_api_key(self) -> str:
        """API key required to access the internal HTTP API server."""
        key = os.getenv("UEC_INTERNAL_API_KEY", "")
        if not key:
            logger.warning("UEC_INTERNAL_API_KEY is not set. Internal API will reject all requests until configured.")
        return key

# Shared instance for convenience
constants = Constants()

# Uniform embed design system
class EmbedDesign:
    """Uniform embed design system for all bot replies."""
    
    # Soft, professional color scheme
    SUCCESS = 0x4ade80  # Soft green
    ERROR = 0xf87171     # Soft red
    WARNING = 0xfbbf24   # Soft yellow
    INFO = 0x60a5fa      # Soft blue
    NEUTRAL = 0x374151   # Soft dark gray
    PRIMARY = 0x6366f1   # Soft purple/indigo
    SECONDARY = 0x94a3b8 # Soft gray
    
    @staticmethod
    def create_embed(title: str, description: str = None, color: int = None, fields: list = None, thumbnail: str = None, footer: str = None):
        """Create a uniform embed with consistent styling."""
        if color is None:
            color = EmbedDesign.NEUTRAL
            
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.utcnow()
        )
        
        # Add fields if provided
        if fields:
            for field in fields:
                embed.add_field(
                    name=field.get("name", ""),
                    value=field.get("value", ""),
                    inline=field.get("inline", True)
                )
        
        # Add thumbnail if provided
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        
        # Add footer if provided
        if footer:
            embed.set_footer(text=footer)
        
        return embed
    
    @staticmethod
    def success(title: str, description: str = None, fields: list = None, thumbnail: str = None, footer: str = None):
        """Create a success embed (soft green)."""
        return EmbedDesign.create_embed(title, description, EmbedDesign.SUCCESS, fields, thumbnail, footer)
    
    @staticmethod
    def error(title: str, description: str = None, fields: list = None, thumbnail: str = None, footer: str = None):
        """Create an error embed (soft red)."""
        return EmbedDesign.create_embed(title, description, EmbedDesign.ERROR, fields, thumbnail, footer)
    
    @staticmethod
    def warning(title: str, description: str = None, fields: list = None, thumbnail: str = None, footer: str = None):
        """Create a warning embed (soft yellow)."""
        return EmbedDesign.create_embed(title, description, EmbedDesign.WARNING, fields, thumbnail, footer)
    
    @staticmethod
    def info(title: str, description: str = None, fields: list = None, thumbnail: str = None, footer: str = None):
        """Create an info embed (soft blue)."""
        return EmbedDesign.create_embed(title, description, EmbedDesign.INFO, fields, thumbnail, footer)
    
    @staticmethod
    def primary(title: str, description: str = None, fields: list = None, thumbnail: str = None, footer: str = None):
        """Create a primary embed (soft purple/indigo)."""
        return EmbedDesign.create_embed(title, description, EmbedDesign.PRIMARY, fields, thumbnail, footer)


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
