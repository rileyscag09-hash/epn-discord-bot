"""
Security logging system for EPN Bot.

This module provides comprehensive security event logging including
authentication failures, permission violations, and suspicious activities.
"""
import asyncio
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional, Union
from dataclasses import dataclass, asdict

import discord
from discord.ext import commands

from utils.constants import logger, Constants, EmbedDesign


class SecurityEventType(Enum):
    """Types of security events that can be logged."""
    AUTHENTICATION_FAILURE = "auth_failure"
    PERMISSION_DENIED = "permission_denied"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    INPUT_VALIDATION_FAILURE = "input_validation_failure"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    NSFW_CONTENT_DETECTED = "nsfw_detected"
    SPAM_DETECTED = "spam_detected"
    RAID_DETECTED = "raid_detected"
    MALICIOUS_URL_DETECTED = "malicious_url_detected"
    BANNED_SERVER_INVITE = "banned_server_invite"
    BLACKLIST_EVASION = "blacklist_evasion"
    UNAUTHORIZED_API_ACCESS = "unauthorized_api"
    DATA_BREACH_ATTEMPT = "data_breach_attempt"


class SecurityEventSeverity(Enum):
    """Severity levels for security events."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class SecurityEvent:
    """Data class representing a security event."""
    event_type: SecurityEventType
    severity: SecurityEventSeverity
    timestamp: datetime
    user_id: Optional[int] = None
    guild_id: Optional[int] = None
    channel_id: Optional[int] = None
    message_id: Optional[int] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    action_taken: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the security event to a dictionary for logging."""
        data = asdict(self)
        # Convert datetime to ISO format
        data['timestamp'] = self.timestamp.isoformat()
        # Convert enums to their values
        data['event_type'] = self.event_type.value
        data['severity'] = self.severity.value
        return data


class SecurityLogger:
    """Main security logging class."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.constants = Constants()
        
        # Security events buffer for batch processing
        self._event_buffer: list[SecurityEvent] = []
        self._buffer_lock = asyncio.Lock()
        self._max_buffer_size = 50
        
        # Start the buffer flushing task
        self._flush_task = None
        self._start_flush_task()
    
    def _start_flush_task(self):
        """Start the periodic buffer flushing task."""
        async def flush_periodically():
            while True:
                try:
                    await asyncio.sleep(60)  # Flush every minute
                    await self.flush_buffer()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in security logger flush task: {e}")
        
        self._flush_task = asyncio.create_task(flush_periodically())
    
    async def log_event(
        self,
        event_type: SecurityEventType,
        severity: SecurityEventSeverity = SecurityEventSeverity.MEDIUM,
        user_id: Optional[int] = None,
        guild_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        message_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        action_taken: Optional[str] = None
    ):
        """
        Log a security event.
        
        Args:
            event_type: Type of security event
            severity: Severity level of the event
            user_id: Discord user ID if applicable
            guild_id: Discord guild ID if applicable
            channel_id: Discord channel ID if applicable
            message_id: Discord message ID if applicable
            ip_address: IP address if available
            user_agent: User agent string if available
            details: Additional details about the event
            action_taken: Description of action taken in response
        """
        event = SecurityEvent(
            event_type=event_type,
            severity=severity,
            timestamp=datetime.now(timezone.utc),
            user_id=user_id,
            guild_id=guild_id,
            channel_id=channel_id,
            message_id=message_id,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details or {},
            action_taken=action_taken
        )
        
        # Add to buffer
        async with self._buffer_lock:
            self._event_buffer.append(event)
            
            # Flush if buffer is full or event is critical
            if (len(self._event_buffer) >= self._max_buffer_size or 
                severity == SecurityEventSeverity.CRITICAL):
                await self._flush_buffer_unsafe()
        
        # Also log to standard logger immediately
        await self._log_to_standard_logger(event)
        
        # Send immediate alerts for high/critical events
        if severity in [SecurityEventSeverity.HIGH, SecurityEventSeverity.CRITICAL]:
            await self._send_security_alert(event)
    
    async def _log_to_standard_logger(self, event: SecurityEvent):
        """Log event to the standard Python logger."""
        event_data = event.to_dict()
        log_message = f"SECURITY EVENT: {event.event_type.value} | "
        log_message += f"Severity: {event.severity.value} | "
        log_message += f"User: {event.user_id} | "
        log_message += f"Guild: {event.guild_id} | "
        log_message += f"Details: {json.dumps(event.details, default=str)}"
        
        if event.severity == SecurityEventSeverity.CRITICAL:
            logger.critical(log_message)
        elif event.severity == SecurityEventSeverity.HIGH:
            logger.error(log_message)
        elif event.severity == SecurityEventSeverity.MEDIUM:
            logger.warning(log_message)
        else:
            logger.info(log_message)
    
    async def _send_security_alert(self, event: SecurityEvent):
        """Send security alert to the designated security channel."""
        try:
            # Get security alerts channel (using the same as error channel for now)
            security_channel_id = 1481986056202096763  # Error channel ID from EPN.py
            security_channel = self.bot.get_channel(security_channel_id)
            
            if not security_channel:
                logger.error("Security alerts channel not found")
                return
            
            # Create alert embed
            color = {
                SecurityEventSeverity.LOW: 0x3498db,      # Blue
                SecurityEventSeverity.MEDIUM: 0xf39c12,   # Orange
                SecurityEventSeverity.HIGH: 0xe74c3c,     # Red
                SecurityEventSeverity.CRITICAL: 0x8e44ad  # Purple
            }.get(event.severity, 0x95a5a6)
            
            embed = discord.Embed(
                title="🚨 Security Alert",
                description=f"**Event Type:** {event.event_type.value.replace('_', ' ').title()}",
                color=color,
                timestamp=event.timestamp
            )
            
            # Add basic info
            embed.add_field(
                name="Severity",
                value=event.severity.value.upper(),
                inline=True
            )
            
            if event.user_id:
                embed.add_field(
                    name="User",
                    value=f"<@{event.user_id}> (`{event.user_id}`)",
                    inline=True
                )
            
            if event.guild_id:
                guild = self.bot.get_guild(event.guild_id)
                guild_name = guild.name if guild else "Unknown"
                embed.add_field(
                    name="Server",
                    value=f"{guild_name} (`{event.guild_id}`)",
                    inline=True
                )
            
            if event.channel_id:
                embed.add_field(
                    name="Channel",
                    value=f"<#{event.channel_id}>",
                    inline=True
                )
            
            if event.action_taken:
                embed.add_field(
                    name="Action Taken",
                    value=event.action_taken,
                    inline=False
                )
            
            # Add details if present
            if event.details:
                details_text = ""
                for key, value in event.details.items():
                    if len(details_text) + len(f"{key}: {value}\n") > 1000:
                        details_text += "... (truncated)"
                        break
                    details_text += f"**{key.replace('_', ' ').title()}:** {value}\n"
                
                if details_text:
                    embed.add_field(
                        name="Details",
                        value=details_text,
                        inline=False
                    )
            
            await security_channel.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Failed to send security alert: {e}")
    
    async def flush_buffer(self):
        """Flush the event buffer to persistent storage."""
        async with self._buffer_lock:
            await self._flush_buffer_unsafe()
    
    async def _flush_buffer_unsafe(self):
        """Flush buffer without acquiring lock (internal use)."""
        if not self._event_buffer:
            return
        
        try:
            # For now, we'll just log the events
            # In a production system, you'd want to store these in a database
            events_to_flush = self._event_buffer.copy()
            self._event_buffer.clear()
            
            # Log batch info
            logger.info(f"Flushing {len(events_to_flush)} security events to storage")
            
            # Here you would typically:
            # 1. Insert events into a security events database table
            # 2. Send to external security monitoring system
            # 3. Archive to secure log files
            
            # For now, just log the count
            event_counts = {}
            for event in events_to_flush:
                event_type = event.event_type.value
                event_counts[event_type] = event_counts.get(event_type, 0) + 1
            
            logger.info(f"Security events flushed: {event_counts}")
            
        except Exception as e:
            logger.error(f"Failed to flush security events buffer: {e}")
    
    async def close(self):
        """Close the security logger and clean up resources."""
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        
        # Final buffer flush
        await self.flush_buffer()
    
    # Convenience methods for common security events
    
    async def log_permission_denied(
        self,
        user_id: int,
        guild_id: Optional[int] = None,
        command_name: Optional[str] = None,
        required_permission: Optional[str] = None
    ):
        """Log a permission denied event."""
        await self.log_event(
            SecurityEventType.PERMISSION_DENIED,
            SecurityEventSeverity.MEDIUM,
            user_id=user_id,
            guild_id=guild_id,
            details={
                "command": command_name,
                "required_permission": required_permission
            },
            action_taken="Command execution blocked"
        )
    
    async def log_authentication_failure(
        self,
        user_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        reason: Optional[str] = None
    ):
        """Log an authentication failure."""
        await self.log_event(
            SecurityEventType.AUTHENTICATION_FAILURE,
            SecurityEventSeverity.HIGH,
            user_id=user_id,
            ip_address=ip_address,
            details={"reason": reason},
            action_taken="Access denied"
        )
    
    async def log_input_validation_failure(
        self,
        user_id: int,
        guild_id: Optional[int] = None,
        command_name: Optional[str] = None,
        validation_error: Optional[str] = None
    ):
        """Log an input validation failure."""
        await self.log_event(
            SecurityEventType.INPUT_VALIDATION_FAILURE,
            SecurityEventSeverity.LOW,
            user_id=user_id,
            guild_id=guild_id,
            details={
                "command": command_name,
                "validation_error": validation_error
            },
            action_taken="Input rejected"
        )
    
    async def log_nsfw_detection(
        self,
        user_id: int,
        guild_id: int,
        channel_id: int,
        message_id: Optional[int] = None,
        urls: Optional[list] = None,
        content_length: Optional[int] = None
    ):
        """Log NSFW content detection."""
        await self.log_event(
            SecurityEventType.NSFW_CONTENT_DETECTED,
            SecurityEventSeverity.HIGH,
            user_id=user_id,
            guild_id=guild_id,
            channel_id=channel_id,
            message_id=message_id,
            details={
                "malicious_urls": urls,
                "content_length": content_length
            },
            action_taken="Message deleted, user timed out"
        )
    
    async def log_spam_detection(
        self,
        user_id: int,
        guild_id: int,
        channel_id: int,
        message_count: Optional[int] = None,
        time_window: Optional[str] = None
    ):
        """Log spam detection."""
        await self.log_event(
            SecurityEventType.SPAM_DETECTED,
            SecurityEventSeverity.MEDIUM,
            user_id=user_id,
            guild_id=guild_id,
            channel_id=channel_id,
            details={
                "message_count": message_count,
                "time_window": time_window
            },
            action_taken="User warned or timed out"
        )
    
    async def log_raid_detection(
        self,
        guild_id: int,
        join_count: int,
        time_window: str = "30 seconds"
    ):
        """Log raid detection."""
        await self.log_event(
            SecurityEventType.RAID_DETECTED,
            SecurityEventSeverity.HIGH,
            guild_id=guild_id,
            details={
                "join_count": join_count,
                "time_window": time_window
            },
            action_taken="Recent joiners timed out"
        )
    
    async def log_blacklist_evasion(
        self,
        user_id: int,
        guild_id: int,
        original_user_id: Optional[int] = None,
        detection_method: Optional[str] = None
    ):
        """Log blacklist evasion attempt."""
        await self.log_event(
            SecurityEventType.BLACKLIST_EVASION,
            SecurityEventSeverity.CRITICAL,
            user_id=user_id,
            guild_id=guild_id,
            details={
                "original_user_id": original_user_id,
                "detection_method": detection_method
            },
            action_taken="User banned automatically"
        )

    async def log_rate_limit_exceeded(
        self,
        user_id: Optional[int] = None,
        api_name: Optional[str] = None,
        current_requests: Optional[int] = None,
        max_requests: Optional[int] = None,
        time_window: Optional[str] = None
    ):
        """Log rate limit exceeded event."""
        await self.log_event(
            SecurityEventType.RATE_LIMIT_EXCEEDED,
            SecurityEventSeverity.MEDIUM,
            user_id=user_id,
            details={
                "api_name": api_name,
                "current_requests": current_requests,
                "max_requests": max_requests,
                "time_window": time_window
            },
            action_taken="Request blocked due to rate limiting"
        )

    async def log_unauthorized_api_access(
        self,
        user_id: Optional[int] = None,
        guild_id: Optional[int] = None,
        access_type: Optional[str] = None,
        required_permission: Optional[str] = None,
        access_attempt: Optional[str] = None
    ):
        """Log unauthorized API access attempt."""
        await self.log_event(
            SecurityEventType.UNAUTHORIZED_API_ACCESS,
            SecurityEventSeverity.HIGH,
            user_id=user_id,
            guild_id=guild_id,
            details={
                "access_type": access_type,
                "required_permission": required_permission,
                "access_attempt": access_attempt
            },
            action_taken="Access denied - unauthorized"
        )

    async def log_data_breach_attempt(
        self,
        user_id: Optional[int] = None,
        operation: Optional[str] = None,
        breach_indicator: Optional[str] = None,
        target_data: Optional[str] = None
    ):
        """Log data breach attempt."""
        await self.log_event(
            SecurityEventType.DATA_BREACH_ATTEMPT,
            SecurityEventSeverity.CRITICAL,
            user_id=user_id,
            details={
                "operation": operation,
                "breach_indicator": breach_indicator,
                "target_data": target_data
            },
            action_taken="Activity logged and flagged for investigation"
        )

    async def log_malicious_url_detected(
        self,
        user_id: int,
        guild_id: int,
        channel_id: int,
        message_id: Optional[int] = None,
        urls: Optional[list] = None,
        detection_method: Optional[str] = None
    ):
        """Log malicious URL detection."""
        await self.log_event(
            SecurityEventType.MALICIOUS_URL_DETECTED,
            SecurityEventSeverity.HIGH,
            user_id=user_id,
            guild_id=guild_id,
            channel_id=channel_id,
            message_id=message_id,
            details={
                "malicious_urls": urls,
                "detection_method": detection_method
            },
            action_taken="Message deleted, user warned"
        )

    async def log_banned_server_invite(
        self,
        user_id: int,
        guild_id: int,
        channel_id: int,
        message_id: Optional[int] = None,
        banned_guild_info: Optional[dict] = None
    ):
        """Log banned server invite detection."""
        await self.log_event(
            SecurityEventType.BANNED_SERVER_INVITE,
            SecurityEventSeverity.HIGH,
            user_id=user_id,
            guild_id=guild_id,
            channel_id=channel_id,
            message_id=message_id,
            details={
                "banned_guild_info": banned_guild_info
            },
            action_taken="Message deleted, user notified"
        )


# Global security logger instance
_security_logger: Optional[SecurityLogger] = None


def get_security_logger(bot: commands.Bot) -> SecurityLogger:
    """Get the global security logger instance."""
    global _security_logger
    if _security_logger is None:
        _security_logger = SecurityLogger(bot)
    return _security_logger


async def close_security_logger():
    """Close the global security logger."""
    global _security_logger
    if _security_logger:
        await _security_logger.close()
        _security_logger = None
