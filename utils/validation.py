"""
Input validation and sanitization utilities for UEC Bot.

This module provides decorators and functions for validating and sanitizing
user inputs to prevent injection attacks and ensure data integrity.
"""
import re
import html
import unicodedata
from typing import Any, Callable, Optional, Union
from functools import wraps
from discord.ext import commands
from utils.constants import logger


class ValidationError(Exception):
    """Custom exception for validation errors."""
    pass


class InputSanitizer:
    """Utility class for input sanitization."""
    
    # Regex patterns for validation
    PATTERNS = {
        'user_id': re.compile(r'^\d{17,19}$'),  # Discord user ID pattern
        'guild_id': re.compile(r'^\d{17,19}$'),  # Discord guild ID pattern
        'channel_id': re.compile(r'^\d{17,19}$'),  # Discord channel ID pattern
        'safe_text': re.compile(r'^[a-zA-Z0-9\s\-_.,!?()@#$%&*+=<>:;"\']+$'),  # Safe text characters
        'url': re.compile(r'^https?://[^\s<>"\'\\]+$'),  # Basic URL validation
        'email': re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'),  # Email validation
        'alphanumeric': re.compile(r'^[a-zA-Z0-9]+$'),  # Alphanumeric only
        'username': re.compile(r'^[a-zA-Z0-9_-]{1,32}$'),  # Username format
    }
    
    @staticmethod
    def sanitize_text(text: str, max_length: int = 2000, allow_newlines: bool = True) -> str:
        """
        Sanitize text input by removing dangerous characters and limiting length.
        
        Args:
            text: The input text to sanitize
            max_length: Maximum allowed length
            allow_newlines: Whether to allow newline characters
            
        Returns:
            Sanitized text string
        """
        if not isinstance(text, str):
            return ""
        
        # Check for SQL injection patterns before sanitization
        sql_injection_patterns = [
            r"'\s*;\s*drop\s+table",
            r"'\s*;\s*delete\s+from",
            r"'\s*;\s*update\s+.*\s+set",
            r"'\s*;\s*insert\s+into",
            r"union\s+select",
            r"'\s*or\s+'.*'='",
            r"'\s*or\s+1\s*=\s*1",
            r"'\s*and\s+'.*'='",
            r"exec\s*\(",
            r"execute\s*\(",
            r"sp_executesql",
            r"xp_cmdshell",
            r"--\s*$",
            r"/\*.*\*/",
            r"'\s*;\s*--"
        ]
        
        text_lower = text.lower()
        for pattern in sql_injection_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                # Log potential SQL injection attempt
                try:
                    from utils.security_logger import get_security_logger, SecurityEventType, SecurityEventSeverity
                    security_logger = get_security_logger(None)
                    import asyncio
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.create_task(security_logger.log_event(
                                SecurityEventType.DATA_BREACH_ATTEMPT,
                                SecurityEventSeverity.CRITICAL,
                                details={
                                    "attack_type": "sql_injection_attempt",
                                    "malicious_pattern": pattern,
                                    "input_text": text[:200],  # Truncated for logging
                                    "breach_indicator": "sql_injection_pattern_detected"
                                },
                                action_taken="Input sanitized and logged for investigation"
                            ))
                    except RuntimeError:
                        # No event loop running, skip logging
                        pass
                except Exception:
                    pass
                break
        
        # Remove null bytes and control characters
        text = ''.join(char for char in text if ord(char) >= 32 or char in '\n\r\t')
        
        # Remove newlines if not allowed
        if not allow_newlines:
            text = text.replace('\n', ' ').replace('\r', ' ')
        
        # HTML escape to prevent XSS
        text = html.escape(text)
        
        # Normalize unicode characters
        text = unicodedata.normalize('NFKC', text)
        
        # Trim to max length
        if len(text) > max_length:
            text = text[:max_length]
        
        # Strip leading/trailing whitespace
        text = text.strip()
        
        return text
    
    @staticmethod
    def sanitize_reason(reason: str) -> str:
        """Sanitize reason text for database storage."""
        return InputSanitizer.sanitize_text(reason, max_length=2000, allow_newlines=False)
    
    @staticmethod
    def sanitize_evidence(evidence: str) -> str:
        """Sanitize evidence text for database storage."""
        return InputSanitizer.sanitize_text(evidence, max_length=4000, allow_newlines=True)
    
    @staticmethod
    def sanitize_username(username: str) -> str:
        """Sanitize username input."""
        if not isinstance(username, str):
            return ""
        
        # Remove dangerous characters, keep only alphanumeric, underscore, hyphen
        username = re.sub(r'[^a-zA-Z0-9_-]', '', username)
        
        # Limit length
        if len(username) > 32:
            username = username[:32]
        
        return username.strip()
    
    @staticmethod
    def sanitize_url(url: str) -> str:
        """Sanitize URL input."""
        if not isinstance(url, str):
            return ""
        
        # Basic URL sanitization
        url = url.strip()
        
        # Check if it's a valid URL format
        if not InputSanitizer.PATTERNS['url'].match(url):
            return ""
        
        # Limit length
        if len(url) > 2000:
            return ""
        
        return url
    
    @staticmethod
    def validate_discord_id(discord_id: Union[str, int]) -> int:
        """
        Validate and convert Discord ID.
        
        Args:
            discord_id: The Discord ID to validate
            
        Returns:
            Validated Discord ID as integer
            
        Raises:
            ValidationError: If ID is invalid
        """
        try:
            # Convert to string for pattern matching
            id_str = str(discord_id)
            
            if not InputSanitizer.PATTERNS['user_id'].match(id_str):
                raise ValidationError(f"Invalid Discord ID format: {discord_id}")
            
            # Convert back to int
            return int(id_str)
        except (ValueError, TypeError) as e:
            raise ValidationError(f"Invalid Discord ID: {discord_id}") from e
    
    @staticmethod
    def validate_pattern(text: str, pattern_name: str) -> bool:
        """
        Validate text against a predefined pattern.
        
        Args:
            text: Text to validate
            pattern_name: Name of the pattern from PATTERNS dict
            
        Returns:
            True if text matches pattern, False otherwise
        """
        if pattern_name not in InputSanitizer.PATTERNS:
            logger.error(f"Unknown validation pattern: {pattern_name}")
            return False
        
        if not isinstance(text, str):
            return False
        
        return bool(InputSanitizer.PATTERNS[pattern_name].match(text))


def validate_input(
    max_length: Optional[int] = None,
    pattern: Optional[str] = None,
    required: bool = True,
    sanitize: bool = True
):
    """
    Decorator for validating command input parameters.
    
    Args:
        max_length: Maximum length for string inputs
        pattern: Pattern name from InputSanitizer.PATTERNS to validate against
        required: Whether the input is required (non-empty)
        sanitize: Whether to sanitize the input
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Get the command context or interaction
            ctx_or_interaction = args[1] if len(args) > 1 else None
            
            try:
                # Validate and sanitize string arguments
                new_args = list(args)
                for i, arg in enumerate(args[2:], start=2):  # Skip self and ctx/interaction
                    if isinstance(arg, str):
                        # Check if required
                        if required and not arg.strip():
                            raise ValidationError("This field is required and cannot be empty.")
                        
                        # Sanitize if requested
                        if sanitize:
                            arg = InputSanitizer.sanitize_text(arg, max_length or 2000)
                        
                        # Check length
                        if max_length and len(arg) > max_length:
                            raise ValidationError(f"Input too long. Maximum length is {max_length} characters.")
                        
                        # Validate pattern
                        if pattern and not InputSanitizer.validate_pattern(arg, pattern):
                            raise ValidationError(f"Input format is invalid.")
                        
                        new_args[i] = arg
                
                # Call the original function with validated arguments
                return await func(*new_args, **kwargs)
                
            except ValidationError as e:
                logger.warning(f"Validation error in {func.__name__}: {e}")
                
                # Log security event for input validation failure
                try:
                    from utils.security_logger import get_security_logger, SecurityEventType, SecurityEventSeverity
                    security_logger = get_security_logger(None)  # Bot instance not available here
                    
                    user_id = None
                    guild_id = None
                    if hasattr(ctx_or_interaction, 'author'):
                        user_id = ctx_or_interaction.author.id
                        guild_id = ctx_or_interaction.guild.id if ctx_or_interaction.guild else None
                    elif hasattr(ctx_or_interaction, 'user'):
                        user_id = ctx_or_interaction.user.id
                        guild_id = ctx_or_interaction.guild_id
                    
                    await security_logger.log_input_validation_failure(
                        user_id=user_id,
                        guild_id=guild_id,
                        command_name=func.__name__,
                        validation_error=str(e)
                    )
                except Exception as log_error:
                    logger.error(f"Failed to log input validation failure: {log_error}")
                
                # Send error response
                if hasattr(ctx_or_interaction, 'reply'):
                    from utils.constants import EmbedDesign
                    embed = EmbedDesign.error(
                        title="Invalid Input",
                        description=str(e)
                    )
                    await ctx_or_interaction.reply(embed=embed, ephemeral=True)
                return
            
            except Exception as e:
                logger.error(f"Unexpected error in validation decorator for {func.__name__}: {e}")
                raise
        
        return wrapper
    return decorator


def validate_discord_id(func: Callable) -> Callable:
    """Decorator for validating Discord ID parameters."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        ctx_or_interaction = args[1] if len(args) > 1 else None
        
        try:
            new_args = list(args)
            for i, arg in enumerate(args[2:], start=2):
                # Check if this looks like a Discord ID parameter
                if isinstance(arg, (str, int)) and str(arg).isdigit():
                    try:
                        validated_id = InputSanitizer.validate_discord_id(arg)
                        new_args[i] = validated_id
                    except ValidationError:
                        # If it's not a valid Discord ID, leave it as is
                        # (might be some other numeric parameter)
                        pass
            
            return await func(*new_args, **kwargs)
            
        except ValidationError as e:
            logger.warning(f"Discord ID validation error in {func.__name__}: {e}")
            
            # Log security event for Discord ID validation failure
            try:
                from utils.security_logger import get_security_logger, SecurityEventType, SecurityEventSeverity
                security_logger = get_security_logger(None)  # Bot instance not available here
                
                user_id = None
                guild_id = None
                if hasattr(ctx_or_interaction, 'author'):
                    user_id = ctx_or_interaction.author.id
                    guild_id = ctx_or_interaction.guild.id if ctx_or_interaction.guild else None
                elif hasattr(ctx_or_interaction, 'user'):
                    user_id = ctx_or_interaction.user.id
                    guild_id = ctx_or_interaction.guild_id
                
                await security_logger.log_input_validation_failure(
                    user_id=user_id,
                    guild_id=guild_id,
                    command_name=func.__name__,
                    validation_error=f"Invalid Discord ID: {str(e)}"
                )
            except Exception as log_error:
                logger.error(f"Failed to log Discord ID validation failure: {log_error}")
            
            if hasattr(ctx_or_interaction, 'reply'):
                from utils.constants import EmbedDesign
                embed = EmbedDesign.error(
                    title="Invalid Discord ID",
                    description=str(e)
                )
                await ctx_or_interaction.reply(embed=embed, ephemeral=True)
            return
        
        except Exception as e:
            logger.error(f"Unexpected error in Discord ID validation for {func.__name__}: {e}")
            raise
    
    return wrapper


def sanitize_database_input(data: dict) -> dict:
    """
    Sanitize dictionary data for database operations.
    
    Args:
        data: Dictionary containing data to sanitize
        
    Returns:
        Dictionary with sanitized values
    """
    sanitized = {}
    
    for key, value in data.items():
        if isinstance(value, str):
            # Apply appropriate sanitization based on field name
            if key in ['reason', 'appeal_reason']:
                sanitized[key] = InputSanitizer.sanitize_reason(value)
            elif key in ['evidence']:
                sanitized[key] = InputSanitizer.sanitize_evidence(value)
            elif key in ['username', 'display_name']:
                sanitized[key] = InputSanitizer.sanitize_username(value)
            elif key in ['url', 'avatar_url', 'invite_url']:
                sanitized[key] = InputSanitizer.sanitize_url(value)
            else:
                # Default text sanitization
                sanitized[key] = InputSanitizer.sanitize_text(value)
        elif isinstance(value, (int, float, bool, type(None))):
            # Numeric and boolean values don't need sanitization
            sanitized[key] = value
        elif isinstance(value, (list, dict)):
            # For complex types, recursively sanitize if they contain strings
            sanitized[key] = value  # For now, just pass through
        else:
            # Unknown type, convert to string and sanitize
            sanitized[key] = InputSanitizer.sanitize_text(str(value))
    
    return sanitized