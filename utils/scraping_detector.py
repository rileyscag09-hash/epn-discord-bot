"""
Scraping Detection System
Detects automated user data harvesting attempts through rapid sequential lookups.
"""

import asyncio
import time
from collections import defaultdict, deque
from typing import Dict, Set, Optional, List
from dataclasses import dataclass, field

@dataclass
class UserLookupEvent:
    """Represents a user lookup event for scraping detection."""
    user_id: int
    command: str
    target_user_id: int
    timestamp: float
    guild_id: Optional[int] = None

@dataclass
class ScrapingPattern:
    """Tracks scraping patterns for a user."""
    user_id: int
    recent_lookups: deque = field(default_factory=lambda: deque(maxlen=50))
    unique_targets: Set[int] = field(default_factory=set)
    commands_used: Set[str] = field(default_factory=set)
    first_lookup_time: float = 0
    last_lookup_time: float = 0
    total_lookups: int = 0

class ScrapingDetector:
    """
    Detects automated user data harvesting attempts by monitoring:
    - Rapid sequential user lookups
    - Large numbers of unique target users
    - Consistent time intervals between requests
    - Use of multiple data extraction commands
    """
    
    def __init__(self):
        self.user_patterns: Dict[int, ScrapingPattern] = {}
        self.cleanup_interval = 3600  # Clean old data every hour
        self.last_cleanup = time.time()
        
        # Thresholds for scraping detection
        self.rapid_lookup_threshold = 10  # lookups per minute
        self.unique_targets_threshold = 20  # unique users looked up
        self.time_window = 300  # 5 minutes
        self.bot_interval_threshold = 2.0  # consistent intervals under 2 seconds
        
        # Commands that access user data
        self.user_lookup_commands = {
            'userinfo', 'whois', 'profile', 'history', 'messages', 
            'warnings', 'notes', 'avatar', 'banner', 'status',
            'roles', 'permissions', 'joined', 'activity', 'mutual'
        }
    
    async def track_user_lookup(self, user_id: int, command: str, target_user_id: int, guild_id: Optional[int] = None) -> bool:
        """
        Track a user lookup command and check for scraping patterns.
        
        Args:
            user_id: ID of the user performing the lookup
            command: Name of the command used
            target_user_id: ID of the user being looked up
            guild_id: Optional guild ID where command was used
            
        Returns:
            True if scraping behavior is detected, False otherwise
        """
        # Only track known user lookup commands
        if command not in self.user_lookup_commands:
            return False
        
        current_time = time.time()
        
        # Clean up old data periodically
        if current_time - self.last_cleanup > self.cleanup_interval:
            await self._cleanup_old_patterns()
        
        # Get or create pattern tracker for user
        if user_id not in self.user_patterns:
            self.user_patterns[user_id] = ScrapingPattern(
                user_id=user_id,
                first_lookup_time=current_time
            )
        
        pattern = self.user_patterns[user_id]
        
        # Update pattern data
        lookup_event = UserLookupEvent(
            user_id=user_id,
            command=command,
            target_user_id=target_user_id,
            timestamp=current_time,
            guild_id=guild_id
        )
        
        pattern.recent_lookups.append(lookup_event)
        pattern.unique_targets.add(target_user_id)
        pattern.commands_used.add(command)
        pattern.last_lookup_time = current_time
        pattern.total_lookups += 1
        
        # Check for scraping patterns
        is_scraping = await self._analyze_scraping_patterns(pattern)
        
        if is_scraping:
            await self._log_scraping_attempt(pattern, lookup_event)
        
        return is_scraping
    
    async def _analyze_scraping_patterns(self, pattern: ScrapingPattern) -> bool:
        """
        Analyze user patterns to detect automated scraping behavior.
        
        Args:
            pattern: The user's lookup pattern data
            
        Returns:
            True if scraping behavior is detected
        """
        current_time = time.time()
        
        # Filter recent lookups within time window
        recent_lookups = [
            lookup for lookup in pattern.recent_lookups
            if current_time - lookup.timestamp <= self.time_window
        ]
        
        if len(recent_lookups) < 5:  # Need minimum lookups to analyze
            return False
        
        # Check for rapid lookup rate
        if len(recent_lookups) >= self.rapid_lookup_threshold:
            return True
        
        # Check for excessive unique targets
        recent_targets = {lookup.target_user_id for lookup in recent_lookups}
        if len(recent_targets) >= self.unique_targets_threshold:
            return True
        
        # Check for bot-like consistent intervals
        if len(recent_lookups) >= 5:
            intervals = []
            for i in range(1, len(recent_lookups)):
                interval = recent_lookups[i].timestamp - recent_lookups[i-1].timestamp
                intervals.append(interval)
            
            # Check if intervals are suspiciously consistent (bot behavior)
            if intervals:
                avg_interval = sum(intervals) / len(intervals)
                if avg_interval <= self.bot_interval_threshold:
                    # Check variance - bots tend to have very consistent timing
                    variance = sum((x - avg_interval) ** 2 for x in intervals) / len(intervals)
                    if variance < 0.1:  # Very low variance indicates automation
                        return True
        
        # Check for systematic enumeration (sequential user IDs)
        if len(recent_targets) >= 10:
            sorted_targets = sorted(recent_targets)
            sequential_count = 0
            for i in range(1, len(sorted_targets)):
                if sorted_targets[i] - sorted_targets[i-1] <= 5:  # Close sequential IDs
                    sequential_count += 1
            
            # High percentage of sequential lookups indicates enumeration
            if sequential_count / len(sorted_targets) > 0.7:
                return True
        
        return False
    
    async def _log_scraping_attempt(self, pattern: ScrapingPattern, latest_lookup: UserLookupEvent):
        """
        Log a detected scraping attempt as a data breach attempt.
        
        Args:
            pattern: The user's scraping pattern data
            latest_lookup: The most recent lookup that triggered detection
        """
        try:
            from utils.security_logger import get_security_logger, SecurityEventType, SecurityEventSeverity
            
            security_logger = get_security_logger(None)
            
            recent_lookups = [
                lookup for lookup in pattern.recent_lookups
                if time.time() - lookup.timestamp <= self.time_window
            ]
            
            await security_logger.log_event(
                SecurityEventType.DATA_BREACH_ATTEMPT,
                SecurityEventSeverity.HIGH,
                user_id=pattern.user_id,
                guild_id=latest_lookup.guild_id,
                details={
                    "attack_type": "user_data_scraping",
                    "scraping_indicators": {
                        "rapid_lookups": len(recent_lookups),
                        "unique_targets": len(pattern.unique_targets),
                        "commands_used": list(pattern.commands_used),
                        "total_lookups": pattern.total_lookups,
                        "time_span_minutes": (pattern.last_lookup_time - pattern.first_lookup_time) / 60
                    },
                    "latest_command": latest_lookup.command,
                    "target_user_id": latest_lookup.target_user_id,
                    "breach_indicator": "automated_user_data_harvesting"
                },
                action_taken="User flagged for automated scraping behavior, monitoring increased"
            )
        except Exception as e:
            # Fail silently to not disrupt normal operations
            pass
    
    async def _cleanup_old_patterns(self):
        """Clean up old pattern data to prevent memory leaks."""
        current_time = time.time()
        cutoff_time = current_time - (self.cleanup_interval * 2)  # Keep 2 hours of data
        
        users_to_remove = []
        for user_id, pattern in self.user_patterns.items():
            if pattern.last_lookup_time < cutoff_time:
                users_to_remove.append(user_id)
        
        for user_id in users_to_remove:
            del self.user_patterns[user_id]
        
        self.last_cleanup = current_time
    
    def get_user_stats(self, user_id: int) -> Optional[Dict]:
        """
        Get scraping statistics for a user.
        
        Args:
            user_id: The user ID to get stats for
            
        Returns:
            Dictionary with user's lookup statistics or None if no data
        """
        if user_id not in self.user_patterns:
            return None
        
        pattern = self.user_patterns[user_id]
        current_time = time.time()
        
        recent_lookups = [
            lookup for lookup in pattern.recent_lookups
            if current_time - lookup.timestamp <= self.time_window
        ]
        
        return {
            "user_id": user_id,
            "total_lookups": pattern.total_lookups,
            "recent_lookups": len(recent_lookups),
            "unique_targets": len(pattern.unique_targets),
            "commands_used": list(pattern.commands_used),
            "first_lookup": pattern.first_lookup_time,
            "last_lookup": pattern.last_lookup_time,
            "is_active": len(recent_lookups) > 0
        }

# Global instance
_scraping_detector = None

def get_scraping_detector() -> ScrapingDetector:
    """Get the global scraping detector instance."""
    global _scraping_detector
    if _scraping_detector is None:
        _scraping_detector = ScrapingDetector()
    return _scraping_detector