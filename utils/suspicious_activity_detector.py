"""
Suspicious Activity Detection System for EPN Bot.

This module implements various triggers for detecting and logging suspicious activities.
"""

import discord
from discord.ext import commands
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque
from typing import Dict, List, Set, Optional, Union
import re
import asyncio

from utils.security_logger import get_security_logger, SecurityEventType, SecurityEventSeverity
from utils.constants import logger


class SuspiciousActivityDetector:
    """Detects and logs suspicious activities."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.security_logger = get_security_logger(bot)
        
        # Tracking dictionaries for pattern detection
        self.user_command_usage = defaultdict(lambda: deque(maxlen=50))  # Last 50 commands per user
        self.user_message_patterns = defaultdict(lambda: deque(maxlen=100))  # Last 100 messages per user
        self.failed_commands = defaultdict(int)  # Failed command attempts per user
        self.unusual_activity_scores = defaultdict(int)  # Suspicious activity scores
        self.first_seen_users = {}  # Track when users first appeared
        
        # Patterns for detection
        self.suspicious_patterns = [
            r'discord\.gg/[A-Za-z0-9]+',  # Discord invites
            r'@(everyone|here)',          # Mass mentions
            r'(hack|crack|exploit|bot|spam)',  # Suspicious keywords
            r'(free|nitro|gift)',         # Common scam words
            r'http[s]?://bit\.ly/',       # Shortened URLs
            r'http[s]?://tinyurl\.com/',  # Shortened URLs
        ]
        
    async def check_command_spam(self, ctx: commands.Context) -> bool:
        """Check for command spam patterns."""
        user_id = ctx.author.id
        current_time = datetime.now(timezone.utc)
        
        # Add command to user's history
        self.user_command_usage[user_id].append({
            'command': ctx.command.name,
            'timestamp': current_time,
            'channel': ctx.channel.id,
            'guild': ctx.guild.id if ctx.guild else None
        })
        
        # Check for rapid command usage (more than 10 commands in 60 seconds)
        recent_commands = [
            cmd for cmd in self.user_command_usage[user_id] 
            if (current_time - cmd['timestamp']).total_seconds() < 60
        ]
        
        if len(recent_commands) > 10:
            await self.security_logger.log_event(
                SecurityEventType.SUSPICIOUS_ACTIVITY,
                SecurityEventSeverity.HIGH,
                user_id=user_id,
                guild_id=ctx.guild.id if ctx.guild else None,
                channel_id=ctx.channel.id,
                details={
                    "activity_type": "command_spam",
                    "commands_per_minute": len(recent_commands),
                    "recent_commands": [cmd['command'] for cmd in recent_commands[-5:]],
                    "detection_reason": "Excessive command usage detected"
                },
                action_taken="Activity flagged for review"
            )
            return True
        
        # Check for repeated failed commands
        same_command_fails = sum(
            1 for cmd in recent_commands 
            if cmd['command'] == ctx.command.name
        )
        
        if same_command_fails > 5:
            await self.security_logger.log_event(
                SecurityEventType.SUSPICIOUS_ACTIVITY,
                SecurityEventSeverity.MEDIUM,
                user_id=user_id,
                guild_id=ctx.guild.id if ctx.guild else None,
                details={
                    "activity_type": "repeated_command_failures",
                    "failed_command": ctx.command.name,
                    "failure_count": same_command_fails,
                    "detection_reason": "Repeated execution of same command"
                },
                action_taken="Pattern flagged for monitoring"
            )
            return True
        
        return False
    
    async def check_message_patterns(self, message) -> bool:
        """Check message content for suspicious patterns. Works with both discord.Message and mock message objects."""
        if not hasattr(message, 'content') or not message.content or (hasattr(message, 'bot') and message.bot):
            return False
        
        # Handle both real Discord messages and mock message objects
        user_id = message.author.id
        current_time = datetime.now(timezone.utc)
        
        # Add message to user's history
        self.user_message_patterns[user_id].append({
            'content': message.content[:500],  # Truncate long messages
            'timestamp': current_time,
            'channel': getattr(message.channel, 'id', None) if hasattr(message, 'channel') else None,
            'guild': getattr(message.guild, 'id', None) if hasattr(message, 'guild') else None
        })
        
        suspicious_flags = []
        
        # Check for suspicious patterns
        for pattern in self.suspicious_patterns:
            if re.search(pattern, message.content, re.IGNORECASE):
                suspicious_flags.append(f"Pattern: {pattern}")
        
        # Check for repeated identical messages
        recent_messages = [
            msg for msg in self.user_message_patterns[user_id]
            if (current_time - msg['timestamp']).total_seconds() < 300  # 5 minutes
        ]
        
        identical_count = sum(
            1 for msg in recent_messages 
            if msg['content'].lower() == message.content.lower()
        )
        
        if identical_count > 3:
            suspicious_flags.append(f"Repeated identical messages: {identical_count}")
        
        # Check for excessive caps
        if len(message.content) > 20:
            caps_ratio = sum(1 for c in message.content if c.isupper()) / len(message.content)
            if caps_ratio > 0.7:
                suspicious_flags.append(f"Excessive caps usage: {caps_ratio:.1%}")
        
        # Check for mass mentions (handle both real and mock message objects)
        mention_count = 0
        if hasattr(message, 'mentions') and hasattr(message, 'role_mentions'):
            mention_count = len(message.mentions) + len(message.role_mentions)
        else:
            # For mock messages, count @mentions in content
            mention_count = len(re.findall(r'@\w+', message.content))
        
        if mention_count > 5:
            suspicious_flags.append(f"Mass mentions: {mention_count}")
        
        # Check for new user sending suspicious content
        account_age = (current_time - message.author.created_at).days
        if account_age < 7 and suspicious_flags:  # Account less than 7 days old
            suspicious_flags.append(f"New account ({account_age} days old)")
        
        # Log if suspicious patterns found
        if suspicious_flags:
            severity = SecurityEventSeverity.HIGH if len(suspicious_flags) > 2 else SecurityEventSeverity.MEDIUM
            
            await self.security_logger.log_event(
                SecurityEventType.SUSPICIOUS_ACTIVITY,
                severity,
                user_id=user_id,
                guild_id=message.guild.id if message.guild else None,
                channel_id=message.channel.id,
                message_id=message.id,
                details={
                    "activity_type": "suspicious_message_pattern",
                    "flags": suspicious_flags,
                    "message_content": message.content[:200],  # First 200 chars
                    "account_age_days": account_age,
                    "detection_reason": f"{len(suspicious_flags)} suspicious patterns detected"
                },
                action_taken="Message flagged for review"
            )
            return True
        
        return False
    
    async def check_unusual_join_pattern(self, member: discord.Member) -> bool:
        """Check for suspicious member join patterns."""
        current_time = datetime.now(timezone.utc)
        user_id = member.id
        guild_id = member.guild.id
        
        # Track first time seeing this user
        if user_id not in self.first_seen_users:
            self.first_seen_users[user_id] = current_time
        
        suspicious_flags = []
        account_age = (current_time - member.created_at).days
        
        # Very new accounts
        if account_age < 1:
            suspicious_flags.append(f"Very new account: {account_age} days")
        
        # Default profile picture and username patterns
        if member.avatar is None:
            suspicious_flags.append("Default avatar")
        
        # Suspicious username patterns
        username_lower = member.name.lower()
        suspicious_username_patterns = [
            r'discord',
            r'nitro',
            r'admin',
            r'mod',
            r'bot',
            r'[0-9]{4,}$',  # Ends with many numbers
            r'^[a-z]{2,3}[0-9]{4,}$'  # Short letters + numbers
        ]
        
        for pattern in suspicious_username_patterns:
            if re.search(pattern, username_lower):
                suspicious_flags.append(f"Suspicious username pattern: {pattern}")
        
        # Check if joining during off-hours (potential bot)
        hour = current_time.hour
        if hour < 6 or hour > 23:  # Late night/early morning
            suspicious_flags.append(f"Off-hours join: {hour}:00")
        
        # Log if multiple red flags
        if len(suspicious_flags) >= 2:
            await self.security_logger.log_event(
                SecurityEventType.SUSPICIOUS_ACTIVITY,
                SecurityEventSeverity.MEDIUM,
                user_id=user_id,
                guild_id=guild_id,
                details={
                    "activity_type": "suspicious_member_join",
                    "flags": suspicious_flags,
                    "account_age_days": account_age,
                    "join_time": current_time.isoformat(),
                    "username": member.name,
                    "detection_reason": f"{len(suspicious_flags)} suspicious join indicators"
                },
                action_taken="New member flagged for monitoring"
            )
            return True
        
        return False
    
    async def check_permission_escalation_attempt(self, ctx: commands.Context, error: Exception) -> bool:
        """Check for repeated permission escalation attempts."""
        if not isinstance(error, (commands.MissingPermissions, commands.NotOwner, commands.MissingRole)):
            return False
        
        user_id = ctx.author.id
        self.failed_commands[user_id] += 1
        
        # Reset counter after 1 hour
        asyncio.create_task(self.reset_failed_counter(user_id))
        
        if self.failed_commands[user_id] >= 5:
            await self.security_logger.log_event(
                SecurityEventType.SUSPICIOUS_ACTIVITY,
                SecurityEventSeverity.HIGH,
                user_id=user_id,
                guild_id=ctx.guild.id if ctx.guild else None,
                channel_id=ctx.channel.id,
                details={
                    "activity_type": "permission_escalation_attempts",
                    "failed_attempts": self.failed_commands[user_id],
                    "last_command": ctx.command.name if ctx.command else "unknown",
                    "error_type": type(error).__name__,
                    "detection_reason": "Repeated permission-denied command attempts"
                },
                action_taken="User flagged for potential privilege escalation"
            )
            return True
        
        return False
    
    async def reset_failed_counter(self, user_id: int):
        """Reset failed command counter after delay."""
        await asyncio.sleep(3600)  # 1 hour
        if user_id in self.failed_commands:
            del self.failed_commands[user_id]
    
    async def check_dm_spam(self, message: discord.Message) -> bool:
        """Check for suspicious DM activity."""
        if message.guild is not None:  # Not a DM
            return False
        
        user_id = message.author.id
        current_time = datetime.now(timezone.utc)
        
        # Add to DM history
        if user_id not in self.user_message_patterns:
            self.user_message_patterns[user_id] = deque(maxlen=100)
        
        self.user_message_patterns[user_id].append({
            'content': message.content[:200],
            'timestamp': current_time,
            'is_dm': True
        })
        
        # Check recent DM activity
        recent_dms = [
            msg for msg in self.user_message_patterns[user_id]
            if msg.get('is_dm') and (current_time - msg['timestamp']).total_seconds() < 3600
        ]
        
        if len(recent_dms) > 10:  # More than 10 DMs in an hour
            await self.security_logger.log_event(
                SecurityEventType.SUSPICIOUS_ACTIVITY,
                SecurityEventSeverity.HIGH,
                user_id=user_id,
                details={
                    "activity_type": "excessive_dm_activity",
                    "dm_count_per_hour": len(recent_dms),
                    "detection_reason": "Excessive DM activity detected",
                    "recent_messages": [msg['content'][:50] for msg in recent_dms[-3:]]
                },
                action_taken="DM activity flagged for review"
            )
            return True
        
        return False


# Global detector instance
_detector = None

def get_suspicious_activity_detector(bot: commands.Bot) -> SuspiciousActivityDetector:
    """Get the global suspicious activity detector."""
    global _detector
    if _detector is None:
        _detector = SuspiciousActivityDetector(bot)
    return _detector
